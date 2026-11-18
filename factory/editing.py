"""Validated edits to scripts and subtitle timing; no provider requests."""

import json
import re
from pathlib import Path
from .files import atomic_json
from .validation import InvalidRequest, text


def load_script(directory: Path):
    try:
        value = json.loads((directory / "script.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise InvalidRequest("Сценарий ещё не готов") from None
    return value


def save_script(directory: Path, data):
    original = load_script(directory)
    scenes = data.get("scenes")
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= 200:
        raise InvalidRequest("Нужно от 1 до 200 сцен")
    cleaned = []
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            raise InvalidRequest("Некорректная сцена")
        old = (
            original.get("scenes", [])[i] if i < len(original.get("scenes", [])) else {}
        )
        cleaned.append(
            {
                **old,
                **{
                    field: text(
                        scene.get(field, old.get(field, "")),
                        field,
                        limit,
                        field == "text",
                    )
                    for field, limit in [
                        ("text", 1200),
                        ("image", 2400),
                        ("motion", 1200),
                        ("caption", 200),
                    ]
                },
            }
        )
    original["scenes"] = cleaned
    original["title"] = text(
        data.get("title", original.get("title", "Ролик")), "Название", 200, True
    )
    atomic_json(directory / "script.json", original)
    return original


def parse_srt(source):
    if not isinstance(source, str) or len(source) > 500000:
        raise InvalidRequest("Слишком большой файл субтитров")
    result = []
    pattern = r"(\d{2,}):(\d{2}):(\d{2})[,.](\d{3})"

    def seconds(value):
        match = re.fullmatch(pattern, value.strip())
        if not match:
            raise InvalidRequest("Неверное время в SRT")
        h, m, s, ms = map(int, match.groups())
        if m >= 60 or s >= 60:
            raise InvalidRequest("Неверное время в SRT")
        return h * 3600 + m * 60 + s + ms / 1000

    previous = 0
    for block in re.split(r"\n\s*\n", source.strip().replace("\r", "")):
        lines = block.splitlines()
        if not lines:
            continue
        if lines[0].strip().isdigit():
            lines = lines[1:]
        if len(lines) < 2 or "-->" not in lines[0]:
            raise InvalidRequest("Неверный формат SRT")
        a, b = lines[0].split("-->", 1)
        start, end = seconds(a), seconds(b)
        if start < previous or end <= start or end > 7200:
            raise InvalidRequest(
                "Время субтитров пересекается или выходит за пределы ролика"
            )
        content = text(" ".join(lines[1:]), "Текст субтитров", 1200, True)
        result.append({"start": start, "end": end, "text": content})
        previous = end
        if len(result) > 5000:
            raise InvalidRequest("Слишком много блоков субтитров")
    if not result:
        raise InvalidRequest("Субтитры пустые")
    return result
