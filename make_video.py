"""Командная строка (без сайта): тема -> видео, обложка, тексты.

    python make_video.py --topic "Застрял в лифте" --format vertical --minutes 1 --lang ru
"""
import argparse
import json
import re

from factory import cost, pipeline
from factory.config import GENRES, JOBS, LANGS, STYLES, TONES, VOICES


def main() -> None:
    ap = argparse.ArgumentParser(description="Тема -> видео, обложка, тексты для соцсетей")
    ap.add_argument("--topic", required=True)
    ap.add_argument("--format", choices=["vertical", "horizontal"], default="vertical")
    ap.add_argument("--minutes", type=float, default=1)
    ap.add_argument("--animate", choices=["key", "all", "none"], default="key")
    ap.add_argument("--lang", choices=list(LANGS), default="ru")
    ap.add_argument("--style", choices=list(STYLES), default="2d")
    ap.add_argument("--voice", choices=list(VOICES), default="gemini")
    ap.add_argument("--genre", choices=list(GENRES), default="auto")
    ap.add_argument("--tone", choices=list(TONES), default="auto")
    ap.add_argument("--notes", default="")
    ap.add_argument("--subtitles", choices=["off", "single", "cycle"], default="off")
    ap.add_argument("--subtitle-color", default="#ffffff")
    ap.add_argument("--subtitle-size", type=int, default=54)
    ap.add_argument("--subtitle-position", type=int, default=78)
    a = ap.parse_args()
    est = cost.estimate(a.minutes, a.animate, voice=a.voice)
    print(f"примерная цена: ${est['total']}")
    out = JOBS / ("cli-" + re.sub(r"[^\w-]+", "_", a.topic.lower())[:40])
    res = pipeline.run(a.topic, a.format, a.minutes, a.animate, out, print, lang=a.lang, voice_provider=a.voice,
                       style=a.style, genre=a.genre, tone=a.tone, notes=a.notes,
                       subtitles={"mode": a.subtitles, "color": a.subtitle_color, "size": a.subtitle_size, "position": a.subtitle_position})
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
