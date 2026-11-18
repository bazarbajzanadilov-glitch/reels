"""Графика поверх картинки: плашка-индикатор (HUD), крупные подписи, виньетки."""

import os
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import ASSETS, GOLD, PANEL, RED, WHITE

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",  # macOS
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Debian/Ubuntu
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",  # Fedora/Alpine
    "C:/Windows/Fonts/arialbd.ttf",  # Windows
]


@lru_cache(maxsize=1)
def font_path() -> str:
    if os.environ.get("FONT"):
        return os.environ["FONT"]
    own = sorted((ASSETS / "fonts").glob("*.ttf")) + sorted(
        (ASSETS / "fonts").glob("*.otf")
    )
    if own:
        return str(own[0])
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return p
    raise RuntimeError(
        "Не найден жирный шрифт с кириллицей: положите .ttf в assets/fonts/"
    )


@lru_cache(maxsize=32)
def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(font_path(), size)


# ---------- подписи ----------


def parse_caption(text: str) -> list[tuple[str, bool]]:
    """'*ГРОМКИЙ* звук' -> [('ГРОМКИЙ', True), ('ЗВУК', False)]. Слова в *звёздочках* — красные."""
    words = []
    for part in re.split(r"(\*[^*]+\*)", text):
        accent = part.startswith("*") and part.endswith("*")
        for w in part.strip("*").split():
            words.append((w.upper(), accent))
    return words


def render_caption(
    text: str, frame: tuple[int, int], scale: float = 1.0
) -> Image.Image | None:
    """Крупная подпись. frame — размер кадра; размер шрифта считается от короткой стороны."""
    words = parse_caption(text or "")
    if not words:
        return None
    width = frame[0]
    size = int(min(frame) * 0.095 * scale)
    f = font(size)
    max_w = int(width * (0.86 if frame[1] > frame[0] else 0.7))
    space = f.getlength(" ")
    lines, line, lw = [], [], 0.0
    for (
        w,
        acc,
    ) in words:  # перенос строк + красное слово всегда на своей строке, как в оригинале
        ww = f.getlength(w)
        if line and (lw + space + ww > max_w or acc != line[-1][1]):
            lines.append(line)
            line, lw = [], 0.0
        lw += (space if line else 0) + ww
        line.append((w, acc))
    lines.append(line)
    lh = int(size * 1.12)
    pad = int(size * 0.35)
    img = Image.new("RGBA", (width, lh * len(lines) + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    stroke = max(3, size // 14)
    for i, ln in enumerate(lines):
        total = sum(f.getlength(w) for w, _ in ln) + space * (len(ln) - 1)
        x = (width - total) / 2
        y = pad + i * lh
        for w, acc in ln:
            d.text(
                (x, y),
                w,
                font=f,
                fill=RED if acc else WHITE,
                stroke_width=stroke,
                stroke_fill=(10, 10, 14),
            )
            x += f.getlength(w) + space
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow.putalpha(
        img.getchannel("A")
        .filter(ImageFilter.GaussianBlur(size // 6))
        .point(lambda a: a * 0.7)
    )
    return Image.alpha_composite(shadow, img)


# ---------- плашка-индикатор ----------


def _icon(d: ImageDraw.ImageDraw, kind: str, x: int, y: int, s: int, color) -> None:
    """Простые иконки, нарисованные фигурами: air, distance, time, heart, temp, depth."""
    if kind == "air":  # лёгкие
        d.rounded_rectangle(
            [x, y + s * 0.15, x + s * 0.44, y + s],
            radius=int(s * 0.2),
            outline=color,
            width=max(2, s // 9),
        )
        d.rounded_rectangle(
            [x + s * 0.56, y + s * 0.15, x + s, y + s],
            radius=int(s * 0.2),
            outline=color,
            width=max(2, s // 9),
        )
        d.line(
            [x + s * 0.5, y, x + s * 0.5, y + s * 0.5], fill=color, width=max(2, s // 9)
        )
    elif kind == "distance":  # грузовик
        d.rectangle(
            [x, y + s * 0.25, x + s * 0.62, y + s * 0.75],
            outline=color,
            width=max(2, s // 9),
        )
        d.polygon(
            [
                (x + s * 0.62, y + s * 0.4),
                (x + s * 0.88, y + s * 0.4),
                (x + s, y + s * 0.6),
                (x + s, y + s * 0.75),
                (x + s * 0.62, y + s * 0.75),
            ],
            outline=color,
            width=max(2, s // 9),
        )
        for cx in (x + s * 0.2, x + s * 0.8):
            d.ellipse(
                [cx - s * 0.12, y + s * 0.7, cx + s * 0.12, y + s * 0.94], fill=color
            )
    elif kind == "time":
        d.ellipse([x, y, x + s, y + s], outline=color, width=max(2, s // 9))
        d.line(
            [x + s / 2, y + s / 2, x + s / 2, y + s * 0.2],
            fill=color,
            width=max(2, s // 9),
        )
        d.line(
            [x + s / 2, y + s / 2, x + s * 0.72, y + s / 2],
            fill=color,
            width=max(2, s // 9),
        )
    elif kind == "heart":
        d.ellipse([x, y + s * 0.1, x + s * 0.55, y + s * 0.6], fill=color)
        d.ellipse([x + s * 0.45, y + s * 0.1, x + s, y + s * 0.6], fill=color)
        d.polygon(
            [
                (x + s * 0.03, y + s * 0.45),
                (x + s * 0.97, y + s * 0.45),
                (x + s / 2, y + s),
            ],
            fill=color,
        )
    elif kind == "temp":
        d.rounded_rectangle(
            [x + s * 0.38, y, x + s * 0.62, y + s * 0.7],
            radius=int(s * 0.12),
            outline=color,
            width=max(2, s // 9),
        )
        d.ellipse([x + s * 0.25, y + s * 0.6, x + s * 0.75, y + s], fill=color)
    elif kind == "depth":
        d.polygon(
            [
                (x + s / 2, y + s),
                (x, y + s * 0.4),
                (x + s * 0.3, y + s * 0.4),
                (x + s * 0.3, y),
                (x + s * 0.7, y),
                (x + s * 0.7, y + s * 0.4),
                (x + s, y + s * 0.4),
            ],
            fill=color,
        )
    else:
        d.ellipse([x + s * 0.2, y + s * 0.2, x + s * 0.8, y + s * 0.8], fill=color)


@lru_cache(maxsize=256)
def render_hud(
    label: str,
    value: str,
    icon: str,
    trend: int,
    danger: bool,
    bright: bool,
    width: int,
) -> Image.Image:
    s = width / 1080 * 1.5
    h = int(66 * s)
    f_lbl, f_val = font(int(19 * s)), font(int(38 * s))
    label_sp = " ".join(label.upper())
    accent = RED if danger else GOLD
    border = accent if bright else tuple(int(c * 0.55) for c in accent)
    icon_s = int(30 * s)
    pad = int(22 * s)
    w_lbl, w_val = f_lbl.getlength(label_sp), f_val.getlength(value)
    w = int(
        pad + icon_s + 14 * s + w_lbl + 18 * s + w_val + (30 * s if trend else 0) + pad
    )
    img = Image.new("RGBA", (w + 40, h + 40), (0, 0, 0, 0))
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).rounded_rectangle(
        [20, 20, 20 + w, 20 + h], radius=h // 2, fill=accent + (150 if bright else 60,)
    )
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(10)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        [20, 20, 20 + w, 20 + h],
        radius=h // 2,
        fill=PANEL + (235,),
        outline=border,
        width=max(2, int(3 * s)),
    )
    x = 20 + pad
    _icon(d, icon, x, 20 + (h - icon_s) // 2, icon_s, accent)
    x += icon_s + 14 * s
    d.text((x, 20 + h / 2), label_sp, font=f_lbl, fill=(225, 220, 205), anchor="lm")
    x += w_lbl + 18 * s
    d.text(
        (x, 20 + h / 2), value, font=f_val, fill=RED if danger else WHITE, anchor="lm"
    )
    x += w_val + 10 * s
    if trend:
        cy, a = 20 + h / 2, 8 * s
        pts = (
            [(x, cy - a / 2), (x + 2 * a, cy - a / 2), (x + a, cy + a)]
            if trend < 0
            else [(x, cy + a / 2), (x + 2 * a, cy + a / 2), (x + a, cy - a)]
        )
        d.polygon(pts, fill=accent)
    return img


# ---------- виньетки ----------


def vignette_mask(size: tuple[int, int], strength: float) -> Image.Image:
    """Маска затемнения краёв (L). strength 0..1."""
    w, h = size
    sw, sh = max(2, w // 8), max(2, h // 8)
    data = []
    for y in range(sh):
        dy = (y / (sh - 1) - 0.5) * 2
        for x in range(sw):
            dx = (x / (sw - 1) - 0.5) * 2
            r = (dx * dx * 0.85 + dy * dy * 0.75) ** 0.5
            v = min(1.0, max(0.0, (r - 0.5) / 0.7))
            data.append(int(255 * strength * v**1.6))
    small = Image.new("L", (sw, sh))
    small.putdata(data)
    return small.filter(ImageFilter.GaussianBlur(2)).resize((w, h), Image.BILINEAR)
