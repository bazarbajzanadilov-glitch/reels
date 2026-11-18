"""Анимация сцен: картинка -> 5-секундный клип (Wan 2.2 Fast через Pollinations).

Картинка загружается в хранилище Pollinations (публичная, но не перечисляемая ссылка),
ставится задача на видео и опрашивается до готовности. Клипы кэшируются в cache/clips/.
"""

import hashlib
import json
import time
import urllib.parse
import uuid
from pathlib import Path

from .config import API, CACHE, VIDEO_DEFAULT, VIDEO_MODEL_FALLBACK, VIDEO_MODELS
from .http import request
from .files import atomic_bytes, atomic_json, path_lock, valid_video
from .execution import Cancelled, OfflineOnly, UncertainRequest, check_cancelled

MEDIA = "https://media.pollinations.ai/upload"
KEEP = " Keep exactly the same character and art style."
SAFE_MOTION = "The character moves slightly and breathes, looks around, the light and environment gently move."


class Flagged(Exception):
    pass


def upload(path: Path) -> str:
    b = uuid.uuid4().hex
    body = (
        (
            f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            f"Content-Type: image/jpeg\r\n\r\n"
        ).encode()
        + path.read_bytes()
        + f"\r\n--{b}--\r\n".encode()
    )
    return json.loads(
        request(MEDIA, body, {"Content-Type": f"multipart/form-data; boundary={b}"})
    )["url"]


def clip_path(image: Path, motion: str, model: str = VIDEO_DEFAULT) -> Path:
    mid = VIDEO_MODELS[model]["model"]
    h = hashlib.sha1(f"{mid}|{image.name}|{motion}".encode()).hexdigest()[:16]
    d = CACHE / "clips"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{h}.mp4"


def _generate(
    image_url: str, model: str, motion: str, aspect: str, out: Path, extra: dict
) -> None:
    params = {
        "model": model,
        "image": image_url,
        "duration": 5,
        "aspectRatio": aspect,
        **extra,
    }
    pending = out.with_suffix(".pending.json")
    task = json.loads(pending.read_text()) if pending.exists() else None
    if task and task.get("model") != model:
        raise RuntimeError("Сначала нужно завершить предыдущий запрос анимации")
    try:
        resp = (
            None
            if task
            else request(
                f"{API}/video/{urllib.parse.quote(motion + KEEP)}?{urllib.parse.urlencode(params)}",
                headers={"Prefer": "respond-async"},
                tries=2,
            )
        )
    except RuntimeError as e:
        if "content_policy" in str(e) or "flagged" in str(e):
            raise Flagged(str(e)) from e
        raise
    if (
        resp is not None and b'"id"' not in resp[:200]
    ):  # уже было готово — пришёл сам файл
        _save_video(out, resp)
        return
    job = task["id"] if task else json.loads(resp)["id"]
    atomic_json(pending, {"id": job, "model": model})
    t0 = time.time()
    while time.time() - t0 < 600:
        check_cancelled()
        time.sleep(4)
        st = json.loads(request(f"{API}/v1/jobs/{job}", timeout=30))
        if st.get("status") == "succeeded":
            _save_video(out, request(f"{API}/v1/jobs/{job}/result", timeout=180))
            pending.unlink(missing_ok=True)
            return
        if st.get("status") == "failed":
            pending.unlink(missing_ok=True)
            err = str(st.get("error") or "задача не выполнена")
            raise (
                Flagged(err)
                if ("content_policy" in err or "flagged" in err)
                else RuntimeError(err)
            )
    raise RuntimeError("не дождались клипа за 10 минут")


def _save_video(out: Path, content: bytes):
    temporary = out.with_suffix(".partial.mp4")
    try:
        atomic_bytes(temporary, content)
        if not valid_video(temporary):
            raise UncertainRequest(
                "Провайдер вернул повреждённое видео; автоматический платный повтор остановлен"
            )
        temporary.replace(out)
    finally:
        temporary.unlink(missing_ok=True)


def _animate(
    image: Path, motion: str, aspect: str, log=print, model: str = VIDEO_DEFAULT
) -> Path | None:
    """Путь к клипу или None, если не вышло (сцена останется картинкой).
    Если фильтр Wan не пропустил сцену: нейтральное движение, затем другая модель (Seedance)."""
    out = clip_path(image, motion, model)
    if valid_video(out):
        return out
    main, extra = VIDEO_MODELS[model]["model"], VIDEO_MODELS[model]["params"]
    fb = {"resolution": "480p"}
    try:
        url = upload(image)
    except (Cancelled, OfflineOnly, UncertainRequest):
        raise
    except Exception as e:
        log(f"анимация: не загрузилась картинка ({str(e)[:100]})")
        return None
    plan = [
        (main, motion, extra),
        (main, SAFE_MOTION, extra),
        (VIDEO_MODEL_FALLBACK, motion, fb),
        (VIDEO_MODEL_FALLBACK, SAFE_MOTION, fb),
    ]
    i, errors = 0, 0
    while i < len(plan) and errors < 2:
        mid, m, prm = plan[i]
        try:
            _generate(url, mid, m, aspect, out, prm)
            return out
        except (Cancelled, OfflineOnly, UncertainRequest):
            raise
        except Flagged:
            i += 1  # фильтр — к следующему варианту
        except Exception as e:
            if "закончились деньги" in str(e):
                log("анимация: на балансе закончились деньги")
                return None
            errors += 1
            log(f"анимация: ошибка ({str(e)[:120]})")
    log("анимация: сцену не пропустили фильтры обеих моделей")
    return None


def animate(
    image: Path, motion: str, aspect: str, log=print, model: str = VIDEO_DEFAULT
) -> Path | None:
    with path_lock(clip_path(image, motion, model)):
        check_cancelled()
        return _animate(image, motion, aspect, log, model)
