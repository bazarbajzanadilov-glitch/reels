"""Mobile layout contract: every 5 px from 260 to 1280.

Run a local server first:
    START_WORKER=0 PORT=8765 .venv/bin/python server.py
    TEST_URL=http://127.0.0.1:8765 .venv/bin/python tests/mobile_ui.py

Playwright is a UI-only dependency; it is not needed by `tests/run.py`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

URL = os.environ.get("TEST_URL", "http://127.0.0.1:8765")
ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "test-results"

JOB = {
    "id": "fixture",
    "topic": "Тест",
    "title": "Тест",
    "status": "draft",
    "format": "vertical",
    "animate": "none",
    "minutes": 1,
    "stages": {"script": {"state": "done"}},
}
SCRIPT = {
    "title": "Тест",
    "scenes": [{"text": "Тестовый текст", "image": "image", "motion": "motion", "caption": ""}],
    "social": {"youtube": {"title": "Тест", "description": "Описание", "tags": ["тест"]}},
}
SOCIAL = {"youtube": {"Название": "Тест", "Описание": "Описание", "Теги": "тест"}}


def launch_browser(playwright):
    try:
        return playwright.chromium.launch(channel="chrome", headless=True)
    except Exception:
        executable = os.environ.get("CHROME_PATH")
        if executable:
            return playwright.chromium.launch(executable_path=executable, headless=True)
        raise


def scroll_center(locator):
    locator.evaluate(
        "el => window.scrollBy({top: el.getBoundingClientRect().top - innerHeight / 2, behavior: 'instant'})"
    )


def tap(locator):
    scroll_center(locator)
    locator.click()


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("SKIP: playwright is not installed (uv pip install playwright)", file=sys.stderr)
        return 2
    if os.environ.get("UI_SCREENSHOTS") == "1":
        SHOTS.mkdir(exist_ok=True)

    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = launch_browser(playwright)
        page = browser.new_page(viewport={"width": 260, "height": 800})
        page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
        page.route("**/api/balance", lambda route: route.fulfill(json={}))
        page.route("**/api/events", lambda route: route.fulfill(status=204))
        page.route("**/api/jobs", lambda route: route.fulfill(json=[JOB]))
        page.route("**/api/jobs/fixture/script", lambda route: route.fulfill(json=SCRIPT))
        page.route("**/api/jobs/fixture/render", lambda route: route.fulfill(json={"status": "queued"}))
        page.route("**/files/fixture/*", lambda route: route.fulfill(status=404))
        page.route("**/files/fixture/social.json", lambda route: route.fulfill(json=SOCIAL))
        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector(".choice-group button")

        def assert_layout(width: int, state: str) -> None:
            data = page.evaluate(
                """() => {
                    const vw = innerWidth;
                    const panes = [...document.querySelectorAll('.pane:not([hidden])')]
                      .filter(el => el.offsetParent !== null)
                      .map(el => el.getBoundingClientRect());
                    return {
                      sw: document.documentElement.scrollWidth,
                      vw,
                      panes: panes.map(r => [r.left, r.right]),
                    };
                }"""
            )
            if data["sw"] > width:
                errors.append(f"{width} {state}: scrollWidth {data['sw']}")
            for left, right in data["panes"]:
                if left < -1 or right > width + 1:
                    errors.append(f"{width} {state}: pane {left:.1f}..{right:.1f}")

        def assert_summary(width: int, state: str) -> None:
            if width > 1024 or not page.locator("#checkout").is_visible():
                return
            panel = page.locator("#checkout").bounding_box()
            go = page.locator("#go").bounding_box()
            height = page.viewport_size["height"]
            if not panel or not go:
                errors.append(f"{width} {state}: summary/go missing")
                return
            if go["x"] < 0 or go["x"] + go["width"] > width or go["y"] < panel["y"] or go["y"] + go["height"] > height:
                errors.append(f"{width} {state}: go outside {panel} / {go}")

        def create_tab() -> None:
            tap(page.locator('[data-worktab="create"]'))

        def check_create(width: int) -> None:
            create_tab()
            assert_layout(width, "создание")
            assert_summary(width, "создание")
            rail = page.locator(".modes").bounding_box()
            for mode in ("none", "animated"):
                card = page.locator(f'[data-project="{mode}"]')
                tap(card)
                page.wait_for_timeout(120)
                box = card.bounding_box()
                if not box or not rail or box["x"] < rail["x"] - 1 or box["x"] + box["width"] > rail["x"] + rail["width"] + 1:
                    errors.append(f"{width} карточка {mode} обрезана")
            page.evaluate(
                """() => {
                    const err = document.querySelector('#err');
                    err.textContent = 'Ошибка проверки';
                    window.scrollBy({top: err.getBoundingClientRect().top - innerHeight / 2, behavior: 'instant'});
                }"""
            )
            page.wait_for_timeout(60)
            alert = page.locator("#err").bounding_box()
            panel = page.locator("#checkout").bounding_box()
            if not alert or not panel or alert["y"] + alert["height"] > panel["y"]:
                errors.append(f"{width} ошибка закрыта нижней панелью")

        def check_sections(width: int) -> None:
            for name in ("history", "music"):
                tap(page.locator(f'[data-worktab="{name}"]'))
                page.wait_for_timeout(120)
                assert_layout(width, name)
                if page.locator("#checkout").is_visible():
                    errors.append(f"{width} панель видна в {name}")
            create_tab()

        def check_subtitles(width: int) -> None:
            cycle = page.locator('[data-caption="cycle"]')
            tap(cycle)
            page.wait_for_timeout(150)
            if page.locator("#subtitle-editor details").count():
                errors.append(f"{width} настройки субтитров спрятаны в details")
            for selector in ("#subtitle-width", "#subtitle-spacing", "#subtitle-background", "#subtitle-outline"):
                if not page.locator(selector).is_visible():
                    errors.append(f"{width} {selector} не виден")
            assert_layout(width, "субтитры")

        def check_progress(width: int) -> None:
            page.evaluate("openKit('fixture')")
            page.wait_for_timeout(200)
            assert_layout(width, "прогресс")
            tap(page.locator('#kit [data-kit="script"]'))
            page.wait_for_timeout(200)
            assert_layout(width, "редактор")
            render = page.locator("#script-render").bounding_box()
            if not render or render["y"] + render["height"] > page.viewport_size["height"]:
                errors.append(f"{width} «Собрать видео» не видна без прокрутки")
            page.locator("#script-close").click()
            page.wait_for_timeout(100)
            page.evaluate(
                """() => {
                    jobs[0].status = 'done'; jobs[0].files = [];
                    openJob('fixture');
                }"""
            )
            page.locator("#kit").wait_for(state="visible")
            page.wait_for_timeout(150)
            assert_layout(width, "результат")
            page.locator("#kit-close").click()
            page.evaluate("jobs[0].status = 'draft'")
            create_tab()

        def screenshot(width: int, name: str) -> None:
            if os.environ.get("UI_SCREENSHOTS") == "1":
                page.set_viewport_size({"width": width, "height": 900})
                page.screenshot(path=str(SHOTS / f"{name}-{width}.png"))

        for width in range(260, 361, 5):
            page.set_viewport_size({"width": width, "height": 800})
            check_create(width)
            check_subtitles(width)
            check_sections(width)
            if width % 20 == 0:
                check_progress(width)
            if width in (260, 320, 360):
                screenshot(width, "mobile")

        for width in (375, 390, 414, 430, 480, 600, 768, 834, 1024, 1280, 1440):
            page.set_viewport_size({"width": width, "height": 900})
            create_tab()
            page.wait_for_timeout(60)
            assert_layout(width, "checkpoint")
            assert_summary(width, "checkpoint")
            if width in (390, 768, 1024, 1280):
                screenshot(width, "checkpoint")

        page.set_viewport_size({"width": 1280, "height": 900})
        create_tab()
        check_subtitles(1280)
        check_progress(1280)
        page.wait_for_timeout(100)
        for selector in ("[data-worktab]", "#go"):
            box = page.locator(selector).first.bounding_box()
            if box and box["height"] < 40:
                errors.append(f"{selector} ниже 40px: {box['height']}")
        screenshot(1280, "desktop")

        browser.close()

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("21 width (260–360, шаг 5) + 11 контрольных (375–1440): настройки, навигация, прогресс и редактор: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
