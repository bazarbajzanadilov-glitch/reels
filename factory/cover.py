"""Обложка: ИИ-картинка + крупный заголовок."""

from pathlib import Path

from PIL import Image, ImageOps

from . import graphics, images
from .config import FORMATS
from .files import atomic_bytes, jpeg_bytes

PRICE = 0.002  # одна картинка обложки (flux)


def make_cover(
    cover: dict,
    style: str,
    character: str,
    seed: int,
    fmt: str,
    out: Path,
    ref_url: str | None = None,
    channel_name: str = "",
) -> Path:
    f = FORMATS[fmt]
    w, h = f["cover"]
    src = images.fetch(
        cover.get("image", "the hero looking shocked, dramatic close-up"),
        style + ", dramatic thumbnail composition, high contrast",
        character,
        seed + 1,
        f["image"],
        ref_url,
    )
    img = ImageOps.fit(Image.open(src).convert("RGB"), (w, h), Image.LANCZOS)
    # затемнение снизу, чтобы текст читался
    grad = Image.new("L", (1, h))
    for y in range(h):
        grad.putpixel((0, y), int(230 * max(0.0, (y / h - 0.45) / 0.55) ** 1.4))
    img.paste((0, 0, 0), (0, 0, w, h), grad.resize((w, h)))
    cap = graphics.render_caption(
        cover.get("text", ""), (w, h), scale=1.7 if h > w else 1.5
    )
    if cap is not None:
        y = int(h * (0.78 if h > w else 0.72)) - cap.height // 2
        img.paste(cap, ((w - cap.width) // 2, max(0, min(y, h - cap.height))), cap)
    if channel_name:
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        font = graphics.font(max(20, min(w, h) // 28))
        draw.text((w // 2, int(h * .08)), channel_name, font=font, anchor="mm",
                  fill="white", stroke_width=3, stroke_fill="black")
    atomic_bytes(out, jpeg_bytes(img))
    return out
