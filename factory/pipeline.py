"""Полный конвейер: тема -> сценарий -> видео + обложка + тексты для соцсетей + архив."""

import json
import zipfile
from .execution import ThreadPoolExecutor, check_cancelled
from pathlib import Path

from . import budget, cost, reference, subtitles as subtitle_tools, video, writer
from .assemble import assemble, seed_of
from .config import VIDEO_DEFAULT, CHARACTER, STYLE, STYLE_TAIL, STYLES, TONES
from .cover import PRICE as COVER_PRICE, make_cover
from .files import atomic_json, fingerprint, valid_image, valid_video

# Комплект для публикации всегда входит в ролик: обложка в трёх форматах и тексты для соцсетей.
PACKAGE_FILES = [
    "cover.jpg",
    "youtube.txt",
    "instagram.txt",
    "tiktok.txt",
    "facebook.txt",
    "all-texts.txt",
    "cover-vertical.jpg",
    "cover-youtube.jpg",
    "cover-square.jpg",
]


def run(
    topic: str,
    fmt: str,
    minutes: float,
    animate: str,
    out_dir: Path,
    log=print,
    exact: bool = False,
    lang: str = "ru",
    voice_provider: str = "gemini",
    voice: str | None = None,
    voice_speed: float = 1.0,
    channel_name: str = "",
    style: str = "2d",
    genre: str = "auto",
    tone: str = "auto",
    narrator: str = "auto",
    ending: str = "auto",
    audience: str = "all",
    notes: str = "",
    custom_style: str = "",
    custom_genre: str = "",
    video_model: str = VIDEO_DEFAULT,
    max_price: float | None = None,
    clips: int | None = None,
    prior_spent: float = 0.0,
    subtitles: dict | None = None,
    script_only: bool = False,
    script: str = "",
) -> dict:
    if subtitle_tools.normalize(subtitles).get("timing") == "words":
        from .alignment import model

        model()  # Resolve the local engine before any paid generation.
    plan = cost.estimate(
        minutes, animate, exact, voice_provider, style, video_model, max_price, clips
    )
    cap = plan["budget"]  # лимит клиента или авто-лимит под выбранное число клипов
    if plan["minimum"] > cap:
        raise RuntimeError(
            f"Бюджет слишком мал: без анимации нужно примерно ${plan['minimum']:.2f}"
        )
    # A legacy retry with unknown spending cannot safely allocate a fresh budget.
    if not budget.credential(out_dir) and (out_dir / "job.json").exists():
        job = json.loads((out_dir / "job.json").read_text(encoding="utf-8"))
        if (
            job.get("finished")
            and not job.get("cost")
            and not job.get("budget_version")
        ):
            raise RuntimeError(
                "Расходы прежней попытки неизвестны; платный повтор заблокирован"
            )
    with budget.limit(out_dir, cap, prior_spent):
        out_dir.mkdir(parents=True, exist_ok=True)

        log("этап:script:running")
        script_path = out_dir / "script.json"
        if script_path.exists():  # повтор после ошибки: сценарий уже есть, голос/картинки/клипы возьмутся из кэша
            data = json.loads(script_path.read_text(encoding="utf-8"))
            log(f"повтор: беру готовый сценарий «{data.get('title', topic)}»")
        else:
            look = {}
            ref = out_dir / "reference.jpg"
            if ref.exists():
                log("изучаю референс")
                look = reference.describe(ref)
                if (
                    exact
                ):  # точное сходство: картинка-референс передаётся в каждую сцену
                    look["reference_url"] = video.upload(ref)
            if style in STYLES:  # выбранный стиль важнее стиля референса
                look["style"] = STYLES[style]["prompt"] + STYLE_TAIL
            if style == "custom" and custom_style.strip():
                look["style"] = custom_style.strip() + STYLE_TAIL
            if genre == "custom" and custom_genre.strip():
                notes = notes + "\nЖанр пользователя: " + custom_genre.strip()
            scene_ref = out_dir / "scene-reference.jpg"
            if scene_ref.exists():
                log("изучаю референс сцены")
                scene_description = reference.describe(scene_ref, scene=True)["scene"]
                look["style"] = look.get("style", STYLE) + ", setting reference: " + scene_description
            mood = TONES.get(tone, TONES["auto"])["mood"]
            if mood:  # тон истории задаёт настроение картинок
                look["style"] = look.get("style", STYLE) + ", " + mood
            log("пишу сценарий")
            data = writer.write(
                topic,
                minutes,
                look.get("character", CHARACTER),
                lang,
                log,
                genre,
                tone,
                narrator,
                ending,
                audience,
                notes,
                checkpoint_dir=out_dir / ".stages",
                script=script,
            )
            data.update(look)
            data.update(voice_provider=voice_provider, voice=voice, voice_speed=voice_speed,
                        channel_name=channel_name.strip(), style_key=style)
            atomic_json(script_path, data)
            log(
                f"сценарий готов: «{data.get('title', topic)}», {len(data['scenes'])} сцен"
            )
        data["video_model"] = video_model
        data["subtitles"] = subtitle_tools.normalize(subtitles)
        atomic_json(script_path, data)
        log("этап:script:done")

        if script_only:
            return {"title": data.get("title", topic), "files": [], "draft": True}

        # сколько клипов влезает в лимит: всё остальное (сценарий, голос, картинки, обложка) считаем заранее
        # по реальному тексту с запасом 10%, чтобы анимация стартовала сразу, без ожидания истории расходов
        base = cost.base_cost(data, exact, voice_provider) * 1.10 + COVER_PRICE * (
            2.5 if exact else 1
        )
        clip_limit = data.setdefault(
            "clip_limit",
            min(
                plan["wanted"],
                cost.clips_allowed(
                    minutes, base + prior_spent, 0.0, style, video_model, cap
                ),
            ),
        )
        atomic_json(script_path, data)

        check_cancelled()
        st = data.get("style", STYLE) + (
            ", vertical 9:16 composition"
            if fmt == "vertical"
            else ", wide 16:9 composition"
        )
        checkpoint = out_dir / ".stages" / "outputs.json"
        try:
            completed = json.loads(checkpoint.read_text())
        except (OSError, ValueError):
            completed = {}
        video_key = fingerprint(
            {
                "version": 2,
                "data": data,
                "format": fmt,
                "channel_name": data.get("channel_name", ""),
                "animate": animate,
                "clips": clip_limit,
            }
        )
        cover_key = fingerprint(
            {
                "cover": data.get("cover"),
                "channel_name": data.get("channel_name", ""),
                "character": data.get("character"),
                "style": st,
                "format": fmt,
            }
        )

        def cover_step():
            log("этап:cover:running")
            if completed.get("cover") != cover_key or not valid_image(
                out_dir / "cover.jpg"
            ):
                make_cover(
                    data.get("cover", {}),
                    st,
                    data.get("character", CHARACTER),
                    seed_of(data),
                    fmt,
                    out_dir / "cover.jpg",
                    data.get("reference_url"),
                    data.get("channel_name", ""),
                )
            log("этап:cover:done")

        with ThreadPoolExecutor(1) as ex:
            cover = ex.submit(cover_step)
            if completed.get("video") == video_key and valid_video(
                out_dir / "video.mp4"
            ):
                log("повтор: использую готовый монтаж")
                for stage in ("voice", "images", "render"):
                    log(f"этап:{stage}:done")
                log("этап:animation:skipped" if animate == "none" else "этап:animation:done")
                out_video = out_dir / "video.mp4"
            else:
                out_video = assemble(
                    data,
                    fmt,
                    animate,
                    out_dir / "video.mp4",
                    log,
                    clip_limit=clip_limit,
                )
            completed["video"] = video_key
            atomic_json(checkpoint, completed)
            cover.result()
            completed["cover"] = cover_key
            atomic_json(checkpoint, completed)

        log("этап:texts:running")
        social = writer.social(data)
        (out_dir / "social.json").write_text(
            json.dumps(social, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        for name, text in writer.social_texts(data).items():
            (out_dir / name).write_text(text, encoding="utf-8")

        all_texts = []
        for network, fields in social.items():
            all_texts.append(network.upper() + "\n" + "\n\n".join(
                f"{label.upper()}:\n{value}" for label, value in fields.items()
            ))
        (out_dir / "all-texts.txt").write_text("\n\n".join(all_texts) + "\n", encoding="utf-8")
        log("этап:texts:done")

        # Useful crops are made locally from the finished cover, without another generation.
        from PIL import Image, ImageOps
        source_cover = Image.open(out_dir / "cover.jpg").convert("RGB")
        for name, size in (("cover-vertical.jpg", (1080, 1920)),
                           ("cover-youtube.jpg", (1280, 720)),
                           ("cover-square.jpg", (1080, 1080))):
            ImageOps.fit(source_cover, size, Image.LANCZOS).save(
                out_dir / name, "JPEG", quality=92, optimize=True)

        log("архив")
        files = ["video.mp4", *PACKAGE_FILES]
        if data["subtitles"]["mode"] != "off" and (out_dir / "subtitles.srt").is_file():
            files.append("subtitles.srt")
            if (out_dir / "subtitles.ass").is_file():
                files.append("subtitles.ass")
        archive = out_dir / "result.partial.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as z:
            for f in files:
                z.write(out_dir / f, f)
        archive.replace(out_dir / "result.zip")

        return {
            "title": data.get("title", topic),
            "files": files,
            "video": str(out_video),
        }


def remount(directory: Path, fmt: str, animate: str, log=print):
    """Rebuild from existing assets. A missing asset fails closed, without any API spend."""
    from .execution import operation

    data = json.loads((directory / "script.json").read_text(encoding="utf-8"))
    with operation(offline=True):
        assemble(
            data,
            fmt,
            animate,
            directory / "video.mp4",
            log,
            clip_limit=data.get("clip_limit", 0),
        )
    files = [name for name in ["video.mp4", *PACKAGE_FILES] if (directory / name).is_file()]
    files += [
        name
        for name in ("subtitles.srt", "subtitles.ass")
        if (directory / name).is_file()
    ]
    temporary = directory / "result.partial.zip"
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_STORED) as archive:
        for name in files:
            archive.write(directory / name, name)
    temporary.replace(directory / "result.zip")
    return {"title": data.get("title", "Ролик"), "files": files}
