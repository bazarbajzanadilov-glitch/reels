"""Двухстрочные субтитры: перенос, тайминг по озвучке, цвета и читаемая обводка."""

import math
import re
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw

from .graphics import font

DEFAULTS = {
    "mode": "off",
    "color": "#ffffff",
    "palette": ["#ffffff", "#ffd166", "#62e6b5", "#7cc8ff", "#ff92c2"],
    "size": 54,
    "position": 78,
    "width": 86,
    "words": 10,
    "spacing": 1.2,
    "outline": 2,
    "outline_color": "auto",
    "background": 0,
    "uppercase": False,
    "show_captions": False,
}


def _color(value, fallback):
    return (
        value.lower()
        if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value)
        else fallback
    )


def _number(value, fallback, low, high):
    try:
        n = float(value)
        return min(high, max(low, n)) if math.isfinite(n) else fallback
    except (TypeError, ValueError):
        return fallback


def normalize(value=None) -> dict:
    raw = value if isinstance(value, dict) else {}
    result = {**DEFAULTS, "palette": list(DEFAULTS["palette"])}
    result["mode"] = (
        raw.get("mode") if raw.get("mode") in ("off", "single", "cycle") else "off"
    )
    result["color"] = _color(raw.get("color"), DEFAULTS["color"])
    palette = raw.get("palette")
    if isinstance(palette, list):
        palette = [_color(c, "") for c in palette[:8]]
        palette = list(dict.fromkeys(c for c in palette if c))
        if len(palette) >= 2:
            result["palette"] = palette
    for name, low, high in [
        ("size", 28, 96),
        ("position", 15, 85),
        ("width", 50, 92),
        ("words", 2, 18),
        ("spacing", 1.05, 1.6),
        ("outline", 1, 5),
        ("background", 0, 85),
    ]:
        result[name] = _number(raw.get(name), DEFAULTS[name], low, high)
        if name != "spacing":
            result[name] = int(round(result[name]))
    result["outline_color"] = (
        "auto"
        if raw.get("outline_color", "auto") == "auto"
        else _color(raw.get("outline_color"), "auto")
    )
    for name in ("uppercase", "show_captions"):
        result[name] = raw.get(name) is True
    result["timing"] = (
        raw.get("timing") if raw.get("timing") in ("phrase", "words") else "phrase"
    )
    return result


def _layout(text: str, frame: tuple[int, int], options: dict) -> list[dict]:
    """Все слова сохраняются; каждый блок содержит максимум две строки, длинное слово уменьшается."""
    text = re.sub(r"\s+", " ", str(text)).strip()
    if options["uppercase"]:
        text = text.upper()
    words = text.split()
    if not words:
        return []
    scale = min(frame) / 1080
    size = max(8, round(options["size"] * scale))
    max_width = frame[0] * options["width"] / 100 - 2 * max(
        1, round(options["outline"] * scale)
    )
    f = font(size)
    lines, line = [], []
    for word in words:
        candidate = " ".join([*line, word])
        if line and (
            f.getlength(candidate) > max_width
            or len(line) >= math.ceil(options["words"] / 2)
        ):
            lines.append(line)
            line = []
        line.append(word)
    if line:
        lines.append(line)
    blocks = []
    for i in range(0, len(lines), 2):
        block = [" ".join(line) for line in lines[i : i + 2]]
        block_size = size
        longest = max(f.getlength(line) for line in block)
        if longest > max_width:
            block_size = max(1, math.floor(size * max_width / longest))
        blocks.append({"lines": block, "font_size": block_size})
    return blocks


def prepare(
    scenes: list[dict], frame: tuple[int, int], value=None, custom=None
) -> list[dict]:
    """Цвет меняется на каждом блоке по всему ролику, включая границы сцен и частей рендера."""
    options = normalize(value)
    if custom is not None and options["mode"] != "off":
        virtual = [
            {"start": c["start"], "dur": c["end"] - c["start"], "text": c["text"]}
            for c in custom
        ]
        cues = prepare(virtual, frame, options)
        for scene in scenes:
            scene["subtitle_settings"] = options
            scene["subtitle_cues"] = [
                c
                for c in cues
                if c["start"] < scene["start"] + scene["dur"]
                and c["end"] > scene["start"]
            ]
        return cues
    cues = []
    index = 0
    for scene in scenes:
        scene["subtitle_settings"] = options
        scene["subtitle_cues"] = []
        if options["mode"] == "off":
            continue
        blocks = _layout(scene.get("text", ""), frame, options)
        if not blocks:
            continue
        start = scene.get("speech_start", scene["start"])
        end = scene.get("speech_end", scene["start"] + scene["dur"])
        duration = max(0, end - start)
        weights = [
            max(1, sum(len(line) for line in block["lines"])) for block in blocks
        ]
        consumed, total = 0, sum(weights)
        word_offset = 0
        for block, weight in zip(blocks, weights):
            color = (
                options["color"]
                if options["mode"] == "single"
                else options["palette"][index % len(options["palette"])]
            )
            cue = {
                **block,
                "start": start + duration * consumed / total,
                "end": start + duration * (consumed + weight) / total,
                "color": color,
                "index": index,
            }
            timings = scene.get("word_timings")
            if timings:
                count = sum(len(line.split()) for line in block["lines"])
                cue["start"] = timings[word_offset]["start"]
                word_offset += count
                cue["end"] = (
                    timings[word_offset]["start"]
                    if word_offset < len(timings)
                    else timings[-1]["end"]
                )
            scene["subtitle_cues"].append(cue)
            cues.append(cue)
            consumed += weight
            index += 1
    return cues


def outline_color(fill: str, option: str) -> str:
    if option != "auto":
        return option
    r, g, b = ImageColor.getrgb(fill)
    return "#101014" if (0.2126 * r + 0.7152 * g + 0.0722 * b) > 140 else "#ffffff"


def render_block(cue: dict, frame: tuple[int, int], value=None) -> Image.Image:
    options = normalize(value)
    scale = min(frame) / 1080
    size = cue["font_size"]
    f = font(size)
    stroke = max(1, round(options["outline"] * scale))
    line_height = max(1, round(size * options["spacing"]))
    bounds = [f.getbbox(line, stroke_width=stroke) for line in cue["lines"]]
    left = min(b[0] for b in bounds)
    top = min(b[1] for b in bounds)
    right = max(b[2] for b in bounds)
    bottom = max(i * line_height + b[3] for i, b in enumerate(bounds))
    pad = max(3, round(size * 0.22))
    image = Image.new(
        "RGBA",
        (max(1, right - left + 2 * pad), max(1, bottom - top + 2 * pad)),
        (0, 0, 0, 0),
    )
    draw = ImageDraw.Draw(image)
    if options["background"]:
        draw.rounded_rectangle(
            (0, 0, image.width - 1, image.height - 1),
            radius=pad,
            fill=(0, 0, 0, round(255 * options["background"] / 100)),
        )
    edge = outline_color(cue["color"], options["outline_color"])
    # If a custom outline matches the fill, add a contrasting outer hairline.
    contrast = outline_color(cue["color"], "auto")
    fill_rgb, edge_rgb = ImageColor.getrgb(cue["color"]), ImageColor.getrgb(edge)
    same = sum(abs(a - b) for a, b in zip(fill_rgb, edge_rgb)) < 100
    for i, (line, box) in enumerate(zip(cue["lines"], bounds)):
        x = (image.width - (box[2] - box[0])) / 2 - box[0]
        y = pad - top + i * line_height
        if same:
            draw.text(
                (x, y),
                line,
                font=f,
                fill=cue["color"],
                stroke_width=stroke + 1,
                stroke_fill=contrast,
            )
        draw.text(
            (x, y),
            line,
            font=f,
            fill=cue["color"],
            stroke_width=stroke,
            stroke_fill=edge,
        )
    max_width = max(1, round(frame[0] * options["width"] / 100))
    if image.width > max_width:
        image = image.resize(
            (max_width, max(1, round(image.height * max_width / image.width))),
            Image.Resampling.LANCZOS,
        )
    return image


def paste(frame: Image.Image, image: Image.Image, value=None) -> None:
    options = normalize(value)
    margin = max(4, round(min(frame.size) * 0.04))
    x = (frame.width - image.width) // 2
    y = round(frame.height * options["position"] / 100 - image.height / 2)
    y = max(margin, min(y, frame.height - margin - image.height))
    frame.paste(image, (x, y), image)


def write_srt(cues: list[dict], path: Path) -> None:
    def stamp(seconds):
        millis = max(0, round(seconds * 1000))
        hours, millis = divmod(millis, 3600000)
        minutes, millis = divmod(millis, 60000)
        seconds, millis = divmod(millis, 1000)
        return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"

    path.write_text(
        "\n\n".join(
            f"{i}\n{stamp(c['start'])} --> {stamp(c['end'])}\n" + "\n".join(c["lines"])
            for i, c in enumerate(cues, 1)
        )
        + "\n",
        encoding="utf-8",
    )


def preview(value=None, fmt="vertical", page=0, width=None) -> Image.Image:
    options = normalize(value)
    horizontal = fmt == "horizontal"
    target_width = int(
        _number(width, 640 if horizontal else 360, 180, 1920 if horizontal else 1080)
    )
    size = (target_width, round(target_width * (9 / 16 if horizontal else 16 / 9)))
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    # Light and dark areas make contrast visible with any chosen text color.
    for y in range(size[1]):
        light = round(235 - 180 * y / size[1])
        draw.line(
            (0, y, size[0] // 2, y),
            fill=(light, max(0, light - 12), max(0, light - 20)),
        )
        draw.line(
            (size[0] // 2, y, size[0], y), fill=(24, 32 + round(45 * y / size[1]), 52)
        )
    scene = {
        "start": 0,
        "dur": 12,
        "text": "Каждый новый блок субтитров появляется целиком. Цвет меняется только при смене блока. Тонкая обводка помогает читать текст на любом фоне.",
    }
    cues = prepare([scene], size, options)
    if cues:
        cue = cues[max(0, int(page)) % len(cues)]
        paste(image, render_block(cue, size, options), options)
    return image


def write_ass(cues, frame, value, path):
    options = normalize(value)
    width, height = frame
    size = round(options["size"] * min(frame) / 1080)
    edge = max(1, options["outline"] * min(frame) / 1080)
    family = font(max(8, size)).getname()[0].replace(",", "").replace("\n", " ")
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{family},{size},&H00FFFFFF,&H00FFFFFF,&H00101014,&H80000000,-1,0,0,0,100,100,0,0,1,{edge},0,5,20,20,20,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def stamp(t):
        units = round(t * 100)
        h, units = divmod(units, 360000)
        m, units = divmod(units, 6000)
        s, c = divmod(units, 100)
        return f"{h}:{m:02}:{s:02}.{c:02}"

    def color(value):
        return "&H" + value[5:7] + value[3:5] + value[1:3] + "&"

    lines = []
    for cue in cues:
        content = r"\N".join(
            line.replace("\\", "＼").replace("{", "｛").replace("}", "｝")
            for line in cue["lines"]
        )
        border = outline_color(cue["color"], options["outline_color"])
        tag = (
            r"{\an5\pos("
            + f"{width // 2},{round(height * options['position'] / 100)}"
            + r")\1c"
            + color(cue["color"])
            + r"\3c"
            + color(border)
            + "}"
        )
        lines.append(
            f"Dialogue: 0,{stamp(cue['start'])},{stamp(cue['end'])},Default,,0,0,0,,{tag}{content}"
        )
    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
