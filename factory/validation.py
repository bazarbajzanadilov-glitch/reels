"""Shared validation for JSON requests and pricing queries."""

import base64
import io
import math
import re
from PIL import Image, ImageOps
from . import subtitles
from .config import (
    AUDIENCES,
    ENDINGS,
    GENRES,
    LANGS,
    NARRATORS,
    STYLES,
    TONES,
    VIDEO_DEFAULT,
    VIDEO_MODELS,
    VOICES,
)

MAX_BODY = 6 * 1024 * 1024
from .config import MAX_PRICE  # noqa: E402 — потолок расходов на один ролик
MAX_IMAGE = 4 * 1024 * 1024
MAX_PIXELS = 20_000_000
MAX_SCRIPT = 20_000


class InvalidRequest(ValueError):
    status = 400


class PayloadTooLarge(InvalidRequest):
    status = 413


def clip_count(value):
    """Сколько сцен оживить: пусто — по умолчанию (None), иначе целое 0…300."""
    if value in (None, ""):
        return None
    return int(number(value, "Число анимированных сцен", 0, 300))


def number(value, label, low, high, default=None):
    if value in (None, "") and default is not None:
        return default
    if isinstance(value, bool):
        raise InvalidRequest(f"Некорректное значение: {label}")
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise InvalidRequest(f"Некорректное значение: {label}") from None
    if not math.isfinite(result) or not low <= result <= high:
        raise InvalidRequest(f"{label}: допустимо от {low} до {high}")
    return result


def choice(value, options, default, label):
    if value is None:
        return default
    if not isinstance(value, str) or value not in options:
        raise InvalidRequest(f"Неизвестное значение: {label}")
    return value


def text(value, label, maximum, required=False):
    if not isinstance(value, str):
        raise InvalidRequest(f"{label}: нужен текст")
    value = value.strip()
    if required and not value:
        raise InvalidRequest(f"Введите {label.lower()}")
    if len(value) > maximum:
        raise InvalidRequest(f"{label}: максимум {maximum} символов")
    return value


def reference_image(value):
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not re.match(
        r"^data:image/(?:jpeg|jpg|png|webp|gif);base64,", value, re.I
    ):
        raise InvalidRequest("Референс: выберите JPG, PNG или WebP")
    try:
        encoded = value.split(",", 1)[1]
        if len(encoded) > MAX_IMAGE * 4 // 3 + 8:
            raise InvalidRequest("Референс: максимум 4 МБ")
        content = base64.b64decode(encoded, validate=True)
        if len(content) > MAX_IMAGE:
            raise InvalidRequest("Референс: максимум 4 МБ")
        with Image.open(io.BytesIO(content)) as image:
            if image.width * image.height > MAX_PIXELS:
                raise InvalidRequest("Референс: максимум 20 мегапикселей")
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((1024, 1024))
            return image
    except InvalidRequest:
        raise
    except (OSError, ValueError, Image.DecompressionBombError):
        raise InvalidRequest("Не удалось прочитать референс") from None


def job_options(data):
    if not isinstance(data, dict):
        raise InvalidRequest("Ожидается объект настроек")
    provider = choice(data.get("voice_provider"), VOICES, "gemini", "озвучка")
    voice = choice(
        data.get("voice"),
        VOICES[provider]["voices"],
        VOICES[provider]["default"],
        "голос",
    )
    maximum = number(data.get("max_price"), "Бюджет", 0.05, MAX_PRICE, default=0)
    if data.get("exact") not in (None, True, False):
        raise InvalidRequest("Некорректный режим сходства")
    return {
        "review": data.get("review") is True,
        "topic": text(data.get("topic", ""), "Тема", 200, True),
        "script": text(data.get("script", ""), "Готовый сценарий", MAX_SCRIPT),
        "format": choice(
            data.get("format"), ("vertical", "horizontal"), "vertical", "формат"
        ),
        "minutes": number(data.get("minutes"), "Длительность", 0.5, 15, default=1),
        "animate": choice(
            data.get("animate"), ("none", "key", "all"), "key", "анимация"
        ),
        "voice_provider": provider,
        "voice": voice,
        "voice_speed": number(data.get("voice_speed"), "Темп голоса", 0.75, 1.25, default=1),
        "channel_name": text(data.get("channel_name", ""), "Название канала", 80),
        **{
            name: choice(data.get(name), options, default, name)
            for name, options, default in [
                ("lang", LANGS, "ru"),
                ("style", STYLES, "2d"),
                ("genre", GENRES, "auto"),
                ("tone", TONES, "auto"),
                ("narrator", NARRATORS, "auto"),
                ("ending", ENDINGS, "auto"),
                ("audience", AUDIENCES, "all"),
                ("video_model", VIDEO_MODELS, VIDEO_DEFAULT),
            ]
        },
        "notes": text(data.get("notes", ""), "Пожелания", 600),
        "custom_style": text(data.get("custom_style", ""), "Свой стиль", 600),
        "custom_genre": text(data.get("custom_genre", ""), "Свой жанр", 600),
        "max_price": round(maximum, 2) if maximum else None,
        "clips": clip_count(data.get("clips")),
        "subtitles": subtitles.normalize(data.get("subtitles")),
    }


def estimate_options(query):
    get = lambda key, default=None: query.get(key, [default])[0]
    return {
        "minutes": number(get("minutes"), "Длительность", 0.5, 15, default=1),
        "animate": choice(get("animate"), ("none", "key", "all"), "key", "анимация"),
        "exact": choice(get("exact"), ("0", "1"), "0", "сходство") == "1",
        "voice": choice(get("voice"), VOICES, "gemini", "озвучка"),
        "style": choice(get("style"), STYLES, "2d", "стиль"),
        "video": choice(get("video"), VIDEO_MODELS, VIDEO_DEFAULT, "модель видео"),
        "max_price": number(get("max"), "Бюджет", 0, MAX_PRICE, default=0) or None,
        "clips": clip_count(get("clips")),
    }
