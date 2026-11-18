"""Покадровый рендер: движение камеры, тряска, вспышки, плашка, подписи -> ffmpeg.

Ролик режется по границам сцен на куски, куски рендерятся параллельно в отдельных процессах
(по одному на ядро), затем склеиваются без перекодирования и соединяются со звуком.
Каждый процесс держит в памяти только картинку текущей сцены.
"""

import math
import json
import random
import subprocess
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import get_context
from pathlib import Path
from functools import lru_cache
from bisect import bisect_right
from .resources import cpu_count, render_workers

from PIL import Image, ImageOps

from . import graphics, subtitles
from .config import RED
from .ff import FFMPEG
from .execution import Cancelled
from .files import atomic_json, fingerprint, path_lock

OVERSCAN = 1.22  # запас картинки под движение камеры
CLIP_LEN = 5.0  # длина клипа видео-модели, сек
MAX_SLOWDOWN = 1.5  # насколько можно замедлить клип, чтобы он покрыл длинную сцену
X264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p"]


def ease(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def prepare_base(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    w, h = size
    return ImageOps.fit(img, (int(w * OVERSCAN), int(h * OVERSCAN)), Image.LANCZOS)


def camera_box(
    cam: str,
    p: float,
    lt: float,
    bw: int,
    bh: int,
    size,
    rng: random.Random,
    shake: float,
):
    """Прямоугольник обрезки в координатах подготовленной картинки."""
    w, h = size
    e = ease(p)
    z, fx, fy = 1.0, 0.5, 0.5  # z=1 — весь кадр с запасом
    if cam == "zoom_in":
        z = 1.0 + 0.16 * e
    elif cam == "zoom_out":
        z = 1.16 - 0.16 * e
    elif cam == "pan_left":
        z, fx = 1.06, 0.62 - 0.24 * e
    elif cam == "pan_right":
        z, fx = 1.06, 0.38 + 0.24 * e
    elif cam == "pan_up":
        z, fy = 1.06, 0.62 - 0.24 * e
    elif cam == "pan_down":
        z, fy = 1.06, 0.38 + 0.24 * e
    elif cam == "shake":
        z = 1.08
    z *= 1 + 0.05 * max(0.0, 1 - lt / 0.25)  # «удар» камеры в начале сцены
    cw, ch = bw / z, bh / z
    cx = fx * bw + (rng.uniform(-1, 1) * shake * bw / w if shake else 0)
    cy = fy * bh + (rng.uniform(-1, 1) * shake * bh / h if shake else 0)
    cx = min(max(cx, cw / 2), bw - cw / 2)
    cy = min(max(cy, ch / 2), bh - ch / 2)
    return (
        max(0.0, cx - cw / 2),
        max(0.0, cy - ch / 2),
        min(float(bw), cx + cw / 2),
        min(float(bh), cy + ch / 2),
    )


class ClipReader:
    """Покадрово читает клип через ffmpeg в нужном размере и частоте кадров.
    Если сцена длиннее клипа — клип слегка замедляется, дальше держится последний кадр."""

    def __init__(self, path: str, size, fps: int, scene_dur: float):
        w, h = size
        slow = min(MAX_SLOWDOWN, max(1.0, scene_dur / CLIP_LEN))
        vf = f"setpts={slow:.3f}*PTS,scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps}"
        self.size, self.n = size, w * h * 3
        self.proc = subprocess.Popen(
            [
                FFMPEG,
                "-loglevel",
                "error",
                "-threads",
                "1",
                "-i",
                path,
                "-vf",
                vf,
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self.last = None

    def frame(self) -> Image.Image | None:
        if self.proc:
            buf = self.proc.stdout.read(self.n)
            if len(buf) == self.n:
                self.last = Image.frombytes("RGB", self.size, buf)
            else:
                self.close()
        return self.last

    def close(self):
        if (
            self.proc
        ):  # сцена может закончиться раньше клипа — просто останавливаем декодер
            self.proc.kill()
            self.proc.stdout.close()
            self.proc.wait()
            self.proc = None


@lru_cache(maxsize=1)
def _frame_assets(size):
    # Read-only source images: paste/blend never mutate these inputs.
    return (
        graphics.vignette_mask(size, 0.85),
        Image.new("RGB", size, (0, 0, 0)),
        Image.new("RGB", size, tuple(int(c * 0.8) for c in RED)),
        Image.new("RGB", size, (255, 255, 255)),
    )


@lru_cache(maxsize=1)
def _danger_masks(size):
    return [graphics.vignette_mask(size, a) for a in (0.15, 0.3, 0.45, 0.6, 0.75)]


def _render_chunk(
    scenes: list[dict],
    f0: int,
    f1: int,
    total: float,
    size,
    fps: int,
    out: str,
    threads: int,
) -> str:
    """Рендерит кадры [f0, f1) в отдельный файл (без звука). Работает в отдельном процессе."""
    w, h = size
    proc = subprocess.Popen(
        [
            FFMPEG,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{w}x{h}",
            "-r",
            str(fps),
            "-i",
            "-",
            *X264,
            "-threads",
            str(threads),
            out,
        ],
        stdin=subprocess.PIPE,
    )
    dark, black, red, white = _frame_assets(tuple(size))
    red_levels = (
        _danger_masks(tuple(size)) if any(s.get("danger") for s in scenes) else None
    )
    unit = min(size)

    si, cur, base, cap, reader = 0, -1, None, None, None
    sub_image, sub_index, subtitle_options = None, -1, subtitles.normalize()
    cue_starts, scene_cues = [], []
    try:
        for fi in range(f0, f1):
            cancel_path = scenes[0].get("cancel_path")
            if cancel_path and fi % max(1, fps) == 0:
                cancel = Path(cancel_path)
                run_id = scenes[0].get("run_id")
                replaced = run_id and (cancel.parent / ".run-id").read_text() != run_id
                if cancel.exists() or replaced:
                    raise Cancelled("Создание остановлено")
            t = fi / fps
            while si + 1 < len(scenes) and t >= scenes[si + 1]["start"]:
                si += 1
            sc = scenes[si]
            if (
                si != cur
            ):  # новая сцена: готовим её картинку и подпись, прошлую выбрасываем
                cur = si
                if reader:
                    reader.close()
                    reader = None
                base = prepare_base(Image.open(sc["image"]).convert("RGB"), size)
                scene_cues = sc.get("subtitle_cues", [])
                cue_starts = [cue["start"] for cue in scene_cues]
                subtitle_options = subtitles.normalize(sc.get("subtitle_settings"))
                has_subtitles = subtitle_options["mode"] != "off"
                cap = (
                    graphics.render_caption(sc.get("caption", ""), size)
                    if not has_subtitles or subtitle_options["show_captions"]
                    else None
                )
                sub_image, sub_index = None, -1
                if sc.get("clip"):
                    reader = ClipReader(sc["clip"], size, fps, sc["dur"])
            lt = t - sc["start"]
            p = lt / sc["dur"]
            src = base
            if reader:
                f = reader.frame()
                if f is not None:
                    src = f

            shake = 10 * w / 1080 if sc["camera"] == "shake" else 0.0
            if sc.get("sfx") == "boom":
                shake = max(shake, 22 * w / 1080 * max(0.0, 1 - lt / 0.6))
            rng = random.Random(fi) if shake else None
            box = camera_box(
                sc["camera"], p, lt, src.width, src.height, size, rng, shake
            )
            frame = src.resize(size, Image.BILINEAR, box=box)

            frame.paste(black, (0, 0), dark)
            if sc["danger"]:  # пульсирующая красная виньетка
                pulse = (math.sin(t * 2 * math.pi * 1.2) + 1) / 2
                frame.paste(red, (0, 0), red_levels[min(4, int(pulse * 5))])

            hud = sc.get("hud")
            if hud:
                v = hud["from"] + (hud["to"] - hud["from"]) * ease(p)
                value = f"{v:.{hud['decimals']}f}{hud['unit']}"
                danger = hud["danger"] or sc["danger"]
                bright = not danger or int(t * 3) % 2 == 0
                trend = (hud["to"] > hud["from"]) - (hud["to"] < hud["from"])
                img = graphics.render_hud(
                    hud["label"], value, hud["icon"], trend, danger, bright, unit
                )
                frame.paste(
                    img,
                    ((w - img.width) // 2, int(h * (0.12 if h > w else 0.07)) - 20),
                    img,
                )

            if cap is not None:
                k = 1 + 0.25 * (1 - ease(lt / 0.18))
                c = (
                    cap
                    if k <= 1.001
                    else cap.resize(
                        (int(cap.width * k), int(cap.height * k)), Image.BILINEAR
                    )
                )
                caption_position = (
                    (0.48 if h > w else 0.38)
                    if has_subtitles
                    else (0.66 if h > w else 0.8)
                )
                frame.paste(
                    c,
                    ((w - c.width) // 2, int(h * caption_position) - c.height // 2),
                    c,
                )

            if sc.get("flash") and lt < 0.12:  # вспышка в начале сцены
                frame = Image.blend(
                    frame,
                    white if sc["flash"] == "white" else black,
                    0.85 * (1 - lt / 0.12),
                )
            cue_position = bisect_right(cue_starts, t) - 1
            cue = scene_cues[cue_position] if cue_position >= 0 else None
            if cue is not None and t >= cue["end"]:
                cue = None
            if cue is not None:
                if cue["index"] != sub_index:
                    sub_image = subtitles.render_block(cue, size, subtitle_options)
                    sub_index = cue["index"]
                subtitles.paste(frame, sub_image, subtitle_options)
            if t < 0.3:
                frame = Image.blend(black, frame, t / 0.3)
            if t > total - 0.6:
                frame = Image.blend(frame, black, min(1.0, (t - (total - 0.6)) / 0.6))
            proc.stdin.write(frame.tobytes())
    finally:
        if reader:
            reader.close()
        try:
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        try:
            code = proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            code = proc.wait()
    if code != 0:
        raise RuntimeError("ffmpeg не смог собрать кусок видео")
    return out


def _split(
    scenes: list[dict], n_frames: int, fps: int, parts: int
) -> list[tuple[int, int, int, int]]:
    """Режет ролик на куски по границам сцен с примерно равным числом кадров.
    Возвращает [(первая сцена, последняя сцена + 1, первый кадр, кадр после последнего)]."""
    starts = [math.ceil(s["start"] * fps) for s in scenes] + [n_frames]
    starts[0] = 0
    target = n_frames / parts
    chunks, a = [], 0
    for i in range(1, len(scenes) + 1):
        if i == len(scenes) or starts[i] - starts[a] >= target:
            chunks.append((a, i, starts[a], starts[i]))
            a = i
    return chunks


def workers_count() -> int:
    """Bound rendering by the CPU quota and available memory of this server."""
    return render_workers()


def pool(workers: int | None = None) -> ProcessPoolExecutor:
    return ProcessPoolExecutor(
        workers or workers_count(), mp_context=get_context("spawn")
    )


def _chunk_key(scenes, f0, f1, total, size, fps):
    return fingerprint(
        {
            "version": 2,
            "scenes": [
                {k: v for k, v in s.items() if k not in ("run_id", "cancel_path")}
                for s in scenes
            ],
            "f0": f0,
            "f1": f1,
            "total": total,
            "size": size,
            "fps": fps,
        }
    )


def chunk_ready(out, scenes, f0, f1, total, size, fps):
    path = Path(out)
    try:
        data = json.loads(path.with_suffix(".done.json").read_text())
        return (
            data["key"] == _chunk_key(scenes, f0, f1, total, size, fps)
            and data["size"] == path.stat().st_size
            and data["size"] > 32
        )
    except (OSError, ValueError, KeyError):
        return False


def _cached_render_chunk(
    scenes: list[dict], f0: int, f1: int, total: float, size, fps: int, out: str
) -> str:
    if chunk_ready(out, scenes, f0, f1, total, size, fps):
        return out
    threads = max(1, cpu_count() // workers_count())
    path = Path(out)
    temporary = path.with_suffix(".partial.mp4")
    try:
        _render_chunk(scenes, f0, f1, total, size, fps, str(temporary), threads)
        temporary.replace(path)
        atomic_json(
            path.with_suffix(".done.json"),
            {
                "key": _chunk_key(scenes, f0, f1, total, size, fps),
                "size": path.stat().st_size,
            },
        )
    finally:
        temporary.unlink(missing_ok=True)
    return out


def render_chunk(
    scenes: list[dict], f0: int, f1: int, total: float, size, fps: int, out: str
) -> str:
    with path_lock(Path(out)):
        return _cached_render_chunk(scenes, f0, f1, total, size, fps, out)


def split(scenes: list[dict], total: float, fps: int, parts: int | None = None):
    n_frames = int(math.ceil(total * fps))
    return _split(scenes, n_frames, fps, min(len(scenes), parts or workers_count() * 3))


def concat(files: list[str], audio: str, out: str) -> None:
    """Склеивает куски без перекодирования и добавляет звук."""
    lst = Path(out).with_suffix(".list.txt")
    escaped = [str(Path(file).resolve()).replace("'", "'\\''") for file in files]
    lst.write_text("".join(f"file '{file}'\n" for file in escaped), encoding="utf-8")
    temporary = Path(out).with_suffix(".partial.mp4")
    r = subprocess.run(
        [
            FFMPEG,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(lst),
            "-i",
            audio,
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(temporary),
        ],
        timeout=3600,
    )
    lst.unlink(missing_ok=True)
    if r.returncode != 0:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("ffmpeg не смог склеить видео")
    temporary.replace(out)


def render(
    scenes: list[dict],
    total: float,
    audio: str,
    out: str,
    size,
    fps: int,
    log=print,
    workers: int | None = None,
) -> None:
    """Рендер готовых сцен целиком (все картинки и клипы уже есть)."""
    chunks = split(scenes, total, fps)
    with tempfile.TemporaryDirectory(dir=Path(out).parent) as tmp:
        files = [str(Path(tmp) / f"part{i:03d}.mp4") for i in range(len(chunks))]
        with pool(workers) as ex:
            futs = [
                ex.submit(render_chunk, scenes[a:b], f0, f1, total, size, fps, files[i])
                for i, (a, b, f0, f1) in enumerate(chunks)
            ]
            for k, f in enumerate(as_completed(futs), 1):
                f.result()
                log(f"монтаж {100 * k // len(chunks)}%")
        concat(files, audio, out)
