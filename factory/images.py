"""Картинки сцен через Pollinations.

Обычный режим: flux ($0.002) по текстовому описанию героя.
Точное сходство: flux.2-klein ($0.005) получает саму картинку-референс к каждой сцене.
"""

import hashlib
import io
import urllib.parse
from .execution import ThreadPoolExecutor, check_cancelled
from pathlib import Path

from PIL import Image

from .config import API, CACHE, IMAGE_MODEL, IMAGE_MODEL_REF, NET_IMAGES
from .http import request
from .files import atomic_bytes, jpeg_bytes, path_lock, valid_image


def build_prompt(scene: str, style: str, character: str) -> str:
    """Герой в начале и ещё раз в конце — так модель меньше «забывает» одежду и цвета."""
    return (
        f"Main character: {character}. Scene: {scene}. Art style: {style}. "
        f"The character must look exactly as described, same face, hair, outfit and colors: {character}"
    )


def fetch(
    scene_prompt: str,
    style: str,
    character: str,
    seed: int,
    wh: tuple[int, int],
    ref_url: str | None = None,
) -> Path:
    """Генерирует картинку (если её нет в кэше) и возвращает путь к файлу."""
    w, h = wh
    model = IMAGE_MODEL_REF if ref_url else IMAGE_MODEL
    prompt = build_prompt(scene_prompt, style, character)
    key = hashlib.sha1(
        f"{model}|{seed}|{w}x{h}|{ref_url}|{prompt}".encode()
    ).hexdigest()[:16]
    d = CACHE / "images"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{key}.jpg"
    with path_lock(path):
        check_cancelled()
        if valid_image(path):
            return path
        params = {
            "width": w,
            "height": h,
            "seed": seed,
            "nologo": "true",
            "model": model,
        }
        if ref_url:
            params["image"] = ref_url
        data = request(
            f"{API}/image/{urllib.parse.quote(prompt)}?{urllib.parse.urlencode(params)}",
            timeout=180,
            tries=4,
        )
        with Image.open(io.BytesIO(data)) as image:
            atomic_bytes(path, jpeg_bytes(image))
        return path


def fetch_all(
    prompts: list[str],
    style: str,
    character: str,
    seed: int,
    wh,
    log=print,
    ref_url: str | None = None,
) -> list[Path]:
    todo = list(dict.fromkeys(prompts))
    done = 0

    def one(p: str) -> Path:
        nonlocal done
        r = fetch(p, style, character, seed, wh, ref_url)
        done += 1
        log(f"картинки {done}/{len(todo)}")
        return r

    with ThreadPoolExecutor(NET_IMAGES) as ex:
        paths = dict(zip(todo, ex.map(one, todo)))
    return [paths[p] for p in prompts]
