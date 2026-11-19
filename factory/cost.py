"""Оценка цены и учёт фактических расходов. Лимит ключа задачи устанавливается у провайдера."""

import json
import time
from datetime import datetime, timezone

from .config import (
    API,
    BUDGET_SAFETY,
    CLIPS_PER_MINUTE,
    MAX_PRICE,
    SECONDS_PER_SCENE,
    STYLES,
    VIDEO_DEFAULT,
    VIDEO_MODELS,
    VOICES,
)
from .http import request

PRICE_IMAGE = 0.002  # flux
PRICE_IMAGE_REF = 0.005  # flux.2-klein с референсом
CHARS_PER_SCENE = 100  # средняя длина фразы


def budget(minutes: float, style: str = "2d") -> float:
    """Потолок цены ролика: плавно от цены за 1 мин до цены за 15 мин (своя у каждого стиля, 3D дороже)."""
    lo, hi = STYLES.get(style, STYLES["2d"])["budget"]
    m = min(max(minutes, 1), 15)
    return round(lo + (hi - lo) * (m - 1) / 14, 3)


def scenes_for(minutes: float) -> int:
    return max(6, round(minutes * 60 / SECONDS_PER_SCENE))


def estimate(
    minutes: float,
    animate: str,
    exact: bool = False,
    voice: str = "gemini",
    style: str = "2d",
    video: str = VIDEO_DEFAULT,
    max_price: float | None = None,
    clips: int | None = None,
) -> dict:
    """max_price — лимит клиента; без него — лимит по стилю (budget), поднятый под выбранное число клипов.
    clips — сколько сцен оживить; без него — CLIPS_PER_MINUTE на минуту (3D — все сцены)."""
    clip = VIDEO_MODELS.get(video, VIDEO_MODELS[VIDEO_DEFAULT])["price"]
    n = scenes_for(minutes)
    text = 0.005 if n <= 30 else 0.004 * (2 + n / 25)
    tts = n * CHARS_PER_SCENE * VOICES.get(voice, VOICES["gemini"])["price"]
    imgs = (n + 1) * (PRICE_IMAGE_REF if exact else PRICE_IMAGE)
    base = text + tts + imgs
    fly = STYLES.get(style, {}).get("camera_fly")  # 3D — полёты камеры во всех сценах, сколько позволяет бюджет
    default = min(n, max(1, round(CLIPS_PER_MINUTE * minutes)))
    if animate == "none":
        want = 0
    elif clips is not None:
        want = min(n, max(0, clips))
    else:
        want = n if fly else default
    cap = max_price or budget(minutes, style)
    if not max_price and clips is not None:  # клиент сам выбрал число клипов — лимит растёт под них с запасом
        cap = max(cap, round((base + want * clip) * 1.15 + 0.01, 2))
    cap = min(cap, MAX_PRICE)  # больше потолка на один ролик не тратим никогда
    can = max(0, int((cap * BUDGET_SAFETY - base) / clip))
    clips = min(want, can)
    parts = {
        "сценарий и тексты": text,
        "голос": tts,
        "картинки": imgs,
        "анимация": clips * clip,
    }
    return {
        "scenes": n,
        "clips": clips,
        "wanted": want,
        "capped": clips < want,
        "parts": {k: round(v, 3) for k, v in parts.items()},
        "total": round(sum(parts.values()), 2),
        "budget": cap,
        "minimum": round(base, 3),
        "clip_price": clip,
        "default_clips": default,
    }


def base_cost(data: dict, exact: bool, voice: str) -> float:
    """Цена всего, кроме анимации, по готовому сценарию: реальная длина текста и число сцен."""
    n = len(data["scenes"])
    chars = sum(len(s["text"]) for s in data["scenes"])
    text = 0.005 if n <= 30 else 0.004 * (2 + n / 25)
    return (
        text
        + chars * VOICES.get(voice, VOICES["gemini"])["price"]
        + (n + 1) * (PRICE_IMAGE_REF if exact else PRICE_IMAGE)
    )


def clips_allowed(
    minutes: float,
    spent_now: float,
    reserve: float,
    style: str = "2d",
    video: str = VIDEO_DEFAULT,
    max_price: float | None = None,
) -> int:
    """Сколько клипов ещё можно сделать, чтобы не превысить лимит. reserve — что ещё предстоит оплатить (обложка)."""
    cap = min(max_price if max_price else budget(minutes, style), MAX_PRICE)
    clip = VIDEO_MODELS.get(video, VIDEO_MODELS[VIDEO_DEFAULT])["price"]
    return max(0, int((cap * BUDGET_SAFETY - spent_now - reserve) / clip))


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _kind(model: str) -> str:
    if any(k in model for k in ("wan", "seedance", "video", "veo", "kling")):
        return "анимация"
    if any(k in model for k in ("tts", "voice", "eleven", "speech")):
        return "голос"
    if any(k in model for k in ("flux", "image", "klein")):
        return "картинки"
    return "сценарий и тексты"


def actual(
    start: str, end: str, wait: bool = True, api_key: str | None = None
) -> dict | None:
    """Сумма расходов этого ключа между start и end (UTC). None, если история недоступна."""
    rows = None
    for _ in range(4 if wait else 1):
        if wait:
            time.sleep(10)  # расходы попадают в историю с небольшой задержкой
        try:
            rows = json.loads(
                request(
                    f"{API}/account/key/usage?limit=1000", timeout=60, api_key=api_key
                )
            )["usage"]
            if any(start <= r["timestamp"] <= end for r in rows):
                break
        except Exception:
            pass
    if rows is None or len(rows) >= 1000:
        return None
    parts: dict[str, float] = {}
    for r in rows:
        if start <= r["timestamp"] <= end:
            k = _kind(r["model"])
            parts[k] = parts.get(k, 0) + float(r.get("cost_usd") or 0)
    return {
        "parts": {k: round(v, 3) for k, v in parts.items()},
        "total": round(sum(parts.values()), 3),
    }
