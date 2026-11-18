"""Референс: картинка один раз превращается в текстовое описание героя и стиля (≈$0.0005).
Дальше все картинки рисует дешёвый flux по этому описанию — сама картинка больше не нужна."""

import base64
import json
from pathlib import Path

from .config import API, TEXT_MODEL
from .http import post_json

PROMPT = (
    "Look at this reference image. Describe for an image generator, in English: "
    '1) "character": the main character only — species/gender/age, face, hair, body, clothing with exact colors '
    '(1–2 sentences, start with "a ..."); '
    '2) "style": the art style, rendering, line work, palette, lighting (1–2 sentences). '
    'Do not mention text, background objects or the scene. Answer only JSON {"character": "...", "style": "..."}'
)


def describe(image: Path, scene=False) -> dict:
    b64 = base64.b64encode(image.read_bytes()).decode()
    payload = {
        "model": TEXT_MODEL,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": ("Describe the setting, environment, architecture, colors and lighting in this image for a video image generator. Do not describe people. Answer JSON with a single key scene." if scene else PROMPT)},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64," + b64},
                    },
                ],
            }
        ],
    }
    raw = json.loads(post_json(f"{API}/v1/chat/completions", payload))
    d = json.loads(raw["choices"][0]["message"]["content"])
    if scene:
        return {"scene": d["scene"].strip()}
    return {
        "character": d["character"].strip(),
        "style": d["style"].strip().rstrip(".") + ", no text, no letters, no watermark",
    }
