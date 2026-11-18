"""Сборка ролика из готового сценария (JSON): голос, картинки, анимация, монтаж."""

import hashlib
import shutil
import threading
import time
from concurrent.futures import as_completed
from .execution import (
    ThreadPoolExecutor,
    check_cancelled,
    Cancelled,
    OfflineOnly,
    UncertainRequest,
)
from pathlib import Path

from . import alignment, images, render, subtitles, tts, video
from .audio import mix
from .execution import CURRENT
from .files import atomic_json, fingerprint, valid_audio
from .config import (
    CHARACTER,
    FORMATS,
    FPS,
    NET_IMAGES,
    NET_VIDEO,
    SCENE_PAD,
    STYLE,
    STYLES,
)

HUD_DEFAULT = {
    "label": "",
    "icon": "dot",
    "unit": "",
    "from": 0,
    "to": 0,
    "decimals": 0,
    "danger": False,
}


def seed_of(data: dict) -> int:
    return int(
        data.get(
            "seed",
            int(hashlib.sha1(data.get("title", "video").encode()).hexdigest()[:6], 16),
        )
    )


def pick_clips(scenes: list, animate: str, limit: int) -> list[int]:
    """Какие сцены оживить: сначала ключевые, остальные — равномерно по ролику, не больше limit."""
    if animate == "none" or limit <= 0:
        return []
    key = [i for i, s in enumerate(scenes) if s.get("animate")]
    if animate == "key":
        pool = key
    else:
        pool = key + [i for i in range(len(scenes)) if i not in key]
    if len(pool) <= limit:
        return sorted(pool)
    if animate == "all" and len(key) < limit:  # ключевые + равномерно из остальных
        rest = [i for i in range(len(scenes)) if i not in key]
        k = limit - len(key)
        return sorted(
            key + [rest[round(j * (len(rest) - 1) / max(1, k - 1))] for j in range(k)]
        )
    step = len(pool) / limit  # ключевых больше лимита — берём равномерно
    return sorted({pool[int(j * step)] for j in range(limit)})


def _timeline(sc: list, voices: list) -> tuple[list, list, list, float]:
    """Раскладка сцен по времени: старт, длительность, плашка, звуки."""
    scenes, voice_parts, sfx_events = [], [], []
    t, hud = 0.0, None
    for i, s in enumerate(sc):
        wav, dur = voices[i]
        speech_duration = dur
        dur += max(0.05, float(s.get("pause", SCENE_PAD)))
        voice_parts.append((wav, t + 0.05))
        if (
            "hud" in s
        ):  # плашка переходит из сцены в сцену, пока её не заменят или не уберут (null)
            if not s["hud"]:
                hud = None
            else:
                prev = hud or HUD_DEFAULT
                hud = {
                    **HUD_DEFAULT,
                    **{k: prev[k] for k in ("label", "icon", "unit", "to", "decimals")},
                    **s["hud"],
                }
                if "from" not in s["hud"]:
                    hud["from"] = prev["to"] if prev is not HUD_DEFAULT else hud["to"]
                if isinstance(hud["from"], float) or isinstance(hud["to"], float):
                    hud["decimals"] = max(
                        hud["decimals"], 1 if (hud["from"] % 1 or hud["to"] % 1) else 0
                    )
        elif hud:
            hud = {**hud, "from": hud["to"]}
        sfx = s.get("sfx")
        if sfx:
            sfx_events.append((sfx, t))
        if s.get("caption"):
            sfx_events.append(("hit", t + 0.02))
        scenes.append(
            {
                "start": t,
                "dur": dur,
                "text": s.get("text", ""),
                "speech_start": t + 0.05,
                "speech_end": t + 0.05 + speech_duration,
                "camera": s.get("camera", "zoom_in"),
                "caption": s.get("caption", ""),
                "hud": dict(hud) if hud else None,
                "danger": bool(s.get("danger", False)),
                "sfx": sfx,
                "flash": s.get("flash") or ("white" if sfx == "boom" else None),
            }
        )
        t += dur
    return scenes, voice_parts, sfx_events, t + 0.4


def assemble(
    data: dict,
    fmt: str,
    animate: str,
    out: Path,
    log=print,
    preview: bool = False,
    clip_limit: int | None = None,
) -> Path:
    """animate: all — все сцены, key — сцены с "animate": true, none — без анимации.
    clip_limit — сколько клипов можно оплатить.

    Всё идёт внахлёст: голос и картинки качаются параллельно; анимация сцены стартует, как только
    готова её картинка; кусок видео монтируется, как только готовы все его сцены — не дожидаясь остальных."""
    t0 = time.time()
    f = FORMATS[fmt]
    size = f["size"] if not preview else (f["size"][0] // 2, f["size"][1] // 2)
    style = data.get("style", STYLE) + (
        ", vertical 9:16 composition"
        if fmt == "vertical"
        else ", wide 16:9 composition"
    )
    character = data.get("character", CHARACTER)
    seed = seed_of(data)
    sc = data["scenes"]
    n = len(sc)
    st = STYLES.get(data.get("style_key", "2d"), STYLES["2d"])
    if animate == "key" and st.get("camera_fly"):
        animate = "all"  # 3D — полёты камеры во всех сценах, сколько позволяет бюджет
    chosen = set(pick_clips(sc, animate, n if clip_limit is None else clip_limit))
    if animate != "none":
        log(f"анимация: {len(chosen)} из {n} сцен")
    motion = {
        i: (
            sc[i].get("motion")
            or f"Natural movement in the scene: {sc[i].get('image', '')}"
        )
        + ". "
        + st["motion"]
        for i in chosen
    }

    pics: dict[int, Path] = {}
    clips: dict[int, str | None] = {}
    lock = threading.Lock()
    identity = fingerprint(
        {
            "version": 2,
            "data": data,
            "format": fmt,
            "size": size,
            "animate": animate,
            "limit": clip_limit,
        }
    )
    tmp = out.parent / ".render" / identity
    tmp.mkdir(parents=True, exist_ok=True)
    stopped = threading.Event()
    img_pool = None
    counts = {"img": 0, "clip": 0}
    errors: list[BaseException] = []

    net = ThreadPoolExecutor(1)
    vid_pool = ThreadPoolExecutor(NET_VIDEO)
    try:

        def clip_job(i: int) -> None:
            try:
                if stopped.is_set():
                    return
                check_cancelled()
                r = video.animate(
                    pics[i], motion[i], f["aspect"], log, data.get("video_model", "wan")
                )
            except (Cancelled, OfflineOnly, UncertainRequest) as error:
                with lock:
                    errors.append(error)
                return
            except Exception as e:  # сцена останется картинкой
                log(f"анимация: ошибка ({str(e)[:100]})")
                r = None
            with lock:
                clips[i] = str(r) if r else None
                counts["clip"] += 1
                log(f"анимация {counts['clip']}/{len(chosen)}")

        def img_job(i: int) -> None:
            try:
                if stopped.is_set():
                    return
                check_cancelled()
                p = images.fetch(
                    sc[i].get("image", ""),
                    style,
                    character,
                    seed,
                    f["image"],
                    data.get("reference_url"),
                )
            except Exception as e:
                with lock:
                    errors.append(e)
                return
            with lock:
                pics[i] = p
                counts["img"] += 1
                if counts["img"] % 5 == 0 or counts["img"] == n:
                    log(f"картинки {counts['img']}/{n}")
            if (
                i in chosen and not stopped.is_set()
            ):  # анимация — сразу, не дожидаясь остальных картинок
                vid_pool.submit(clip_job, i)

        img_pool = ThreadPoolExecutor(NET_IMAGES)
        for i in range(n):
            img_pool.submit(img_job, i)
        voices = tts.synthesize_all(
            [s["text"] for s in sc],
            data.get("voice_provider", "gemini"),
            data.get("voice"),
            log,
        )
        scenes, voice_parts, sfx_events, total = _timeline(sc, voices)
        subtitle_options = subtitles.normalize(data.get("subtitles"))
        if subtitle_options.get("timing") == "words" and not data.get("subtitle_cues"):
            alignment.align(
                scenes,
                voices,
                data.get("lang", "ru"),
                out.parent / ".stages" / "alignment",
                log,
            )
        custom = data.get("subtitle_cues")
        if custom and custom[-1]["end"] > total + 0.1:
            raise RuntimeError("Субтитры выходят за длительность ролика")
        cues = subtitles.prepare(scenes, size, subtitle_options, custom)
        atomic_json(out.parent / "timeline.json", {"duration": total, "cues": cues})
        subtitle_path = out.parent / "subtitles.srt"
        if subtitle_options["mode"] != "off":
            subtitles.write_srt(cues, subtitle_path)
            subtitles.write_ass(
                cues, size, subtitle_options, out.parent / "subtitles.ass"
            )
            log(f"субтитры: {len(cues)} блоков, до двух строк")
        else:
            subtitle_path.unlink(missing_ok=True)
            (out.parent / "subtitles.ass").unlink(missing_ok=True)
        audio = tmp / "audio.wav"
        audio_f = (
            None
            if valid_audio(audio)
            else net.submit(mix, voice_parts, sfx_events, total, str(audio))
        )
        for scene in scenes:
            scene["cancel_path"] = str(CURRENT.get().cancel_path or "")
            scene["run_id"] = CURRENT.get().run_id

        chunks = render.split(scenes, total, FPS)
        files = [str(tmp / f"part{k:03d}.mp4") for k in range(len(chunks))]
        started, futs = set(), []
        with render.pool() as rp:
            while len(started) < len(chunks):
                check_cancelled()
                with lock:
                    for k, (a, b, f0, f1) in enumerate(chunks):
                        if k in started:
                            continue
                        if all(
                            i in pics and (i not in chosen or i in clips)
                            for i in range(a, b)
                        ):
                            part = []
                            for i in range(a, b):
                                s = dict(
                                    scenes[i], image=str(pics[i]), clip=clips.get(i)
                                )
                                if s["clip"] and st.get("camera_fly"):
                                    s["camera"] = (
                                        "none"  # в 3D камера летает в самом клипе
                                    )
                                part.append(s)
                            if not render.chunk_ready(
                                files[k], part, f0, f1, total, size, FPS
                            ):
                                futs.append(
                                    rp.submit(
                                        render.render_chunk,
                                        part,
                                        f0,
                                        f1,
                                        total,
                                        size,
                                        FPS,
                                        files[k],
                                    )
                                )
                            started.add(k)
                    if errors:
                        raise errors[0]
                if len(started) < len(chunks):
                    time.sleep(0.5)
            log(f"монтаж: {sum(1 for c in clips.values() if c)}/{n} сцен анимированы")
            for k, fut in enumerate(as_completed(futs), 1):
                fut.result()
                log(f"монтаж {100 * k // len(chunks)}%")
        img_pool.shutdown()
        if audio_f is not None:
            audio_f.result()
        render.concat(files, str(audio), str(out))
    finally:
        # Drain producers before consumers: images may submit video tasks.
        # No credential scope or temporary files disappear while a task still uses them.
        stopped.set()
        if img_pool is not None:
            img_pool.shutdown(wait=True, cancel_futures=True)
        vid_pool.shutdown(wait=True, cancel_futures=True)
        net.shutdown(wait=True, cancel_futures=True)
    shutil.rmtree(tmp, ignore_errors=True)
    log(f"видео готово за {time.time() - t0:.0f} сек")
    return out
