"""Дизайн-система: скругления, шрифты и отступы задаются только токенами из web/css/tokens.css."""

import re
import unittest
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "web" / "css"
RULE = re.compile(r"(border-radius|font-size|gap|row-gap|column-gap)\s*:\s*([^;}]+)")


def allowed(value: str) -> bool:
    for part in value.replace("/", " ").split():
        if part.startswith(("var(", "calc(")) or part in ("0", "50%", "1em", "inherit"):
            continue
        px = re.fullmatch(r"(\d+)px", part)
        if px and int(px.group(1)) <= 6:  # микродетали: флаг, эквалайзер, галочка
            continue
        return False
    return True


class DesignTokenTests(unittest.TestCase):
    def test_layout_and_components_use_tokens(self):
        problems = []
        for name in ("components.css", "app.css"):
            for number, line in enumerate((CSS / name).read_text(encoding="utf-8").splitlines(), 1):
                for prop, value in RULE.findall(line):
                    if not allowed(value.strip().removesuffix("!important").strip()):
                        problems.append(f"{name}:{number} {prop}: {value.strip()}")
        self.assertEqual(problems, [])

    def test_index_has_no_native_color_or_voice_pickers_visible(self):
        html = (CSS.parent / "index.html").read_text(encoding="utf-8")
        for tag in re.findall(r"<input[^>]*type=\"color\"[^>]*>", html) + re.findall(r"<select id=\"voice\"[^>]*>", html):
            self.assertIn("hidden", tag)


if __name__ == "__main__":
    unittest.main()
