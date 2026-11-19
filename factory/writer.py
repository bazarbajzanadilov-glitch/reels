"""Сценарий и тексты для соцсетей из одной темы — через текстовую модель Pollinations.

Короткие ролики (до ~30 сцен) пишутся одним запросом. Длинные (11–14 мин, ~130 сцен) — сначала план
(название, обложка, тексты для соцсетей, краткое содержание каждой сцены), затем сцены частями по 25.
"""

import json
from pathlib import Path
from .execution import ThreadPoolExecutor, check_cancelled, Cancelled, UncertainRequest

from .config import (
    API,
    AUDIENCES,
    ENDINGS,
    GENRES,
    LANGS,
    NARRATORS,
    SECONDS_PER_SCENE,
    TEXT_MODEL,
    TONES,
)
from .http import post_json
from .files import atomic_json, fingerprint

CHUNK = 25

RULES = """Ты сценарист вирусных роликов.
Тема: «{topic}». Длина: {minutes} мин, всего {n} сцен.

НАСТРОЙКИ СЮЖЕТА — соблюдай строго, каждая сцена должна им соответствовать:
- Жанр и подача: {genre}
- Тон: {tone}
- Рассказчик: {narrator}
- Аудитория: {audience}
- Финал: {ending}
- Пожелания заказчика (важнее всего остального, если противоречат — следуй им): {notes}
- Готовый текст заказчика: {script}

ЯЗЫК РОЛИКА: {lang}. На этом языке пиши "text", "caption", подписи "hud.label", обложку и все тексты для соцсетей.
Поля "image" и "motion" — всегда на английском.
Главный герой (the hero): {hero}.

Требования к тексту:
- строго следуй настройкам сюжета выше: жанр, тон, рассказчик, аудитория и финал задают текст, а не шаблон;
- первая фраза — сильный крючок, цепляет в первые 3 секунды;
- в каждой сцене 1–2 коротких предложения (80–110 символов), история развивается, без повторов;
- придумай свой оригинальный сюжет под эту тему, а не типовой;
- в конце — вопрос зрителю для комментариев.

Формат сцены:
{{
  "text": "фраза для озвучки",
  "caption": "1–3 СЛОВА НА ЭКРАН, главное слово в *звёздочках*",
  "image": "frame description in English: what we see, angle, light; main character is 'the hero'; no text in frame",
  "motion": "5-second motion in English: who does what (no words about death, blood, drowning)",
  "camera": "zoom_in | zoom_out | pan_left | pan_right | pan_up | pan_down | shake",
  "sfx": "boom | whoosh | heartbeat | alarm | hit | rise | none",
  "danger": false,
  "key": false,
  "hud": {{"label": "Воздух", "icon": "air", "unit": "%", "from": 80, "to": 60}}
}}
Правила полей:
- "hud": {hud_rule}
- "danger": true — в самых напряжённых моментах, не чаще чем в трети сцен (в спокойных жанрах — редко или никогда).
- "key": true — сцены с самым заметным действием (примерно каждая четвёртая).
- В "image", "motion" и обложке НЕ описывай внешность, одежду и цвета героя — они добавятся автоматически.
  Герой никогда не снимает и не меняет одежду."""

META = """  "title": "короткое название ролика",
  "cover": {{"image": "bright thumbnail frame in English, the hero close-up, strong emotion", "text": "2–4 СЛОВА НА ОБЛОЖКУ, главное в *звёздочках*"}},
  "social": {{
    "youtube": {{"title": "до 90 символов, кликабельно", "description": "3–5 предложений + призыв подписаться", "tags": ["10–15 тегов без #"]}},
    "instagram": {{"caption": "2–3 предложения с эмодзи + вопрос", "hashtags": ["15–20 хэштегов без #"]}},
    "tiktok": {{"caption": "до 150 символов", "hashtags": ["5–8 хэштегов без #"]}},
    "facebook": {{"title": "короткий заголовок", "text": "2–4 предложения + вопрос", "hashtags": ["3–5 хэштегов без #"]}}
  }}"""

ONE_SHOT = (
    RULES
    + """

Ответь ТОЛЬКО JSON:
{{
"""
    + META
    + """,
  "scenes": [ ровно {n} сцен в формате выше ]
}}"""
)

OUTLINE = (
    RULES
    + """

Сейчас нужен только ПЛАН. Ответь ТОЛЬКО JSON:
{{
"""
    + META
    + """,
  "beats": [ ровно {n} строк: краткое содержание каждой сцены по порядку, 5–12 слов ]
}}"""
)

PART = (
    RULES
    + """

План всего ролика (номер: содержание):
{beats}

Напиши сцены с {a} по {b} включительно, строго по плану, связно с соседними сценами плана.
Ответь ТОЛЬКО JSON: {{"scenes": [ ровно {count} сцен в формате выше ]}}"""
)


def _ask(prompt: str, timeout: int = 400) -> dict:
    payload = {
        "model": TEXT_MODEL,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": prompt}],
    }
    raw = json.loads(post_json(f"{API}/v1/chat/completions", payload, timeout=timeout))
    return json.loads(raw["choices"][0]["message"]["content"])


def _clean(scenes: list) -> list:
    out = []
    for s in scenes:
        if not isinstance(s, dict) or not s.get("text"):
            continue
        if s.get("sfx") == "none":
            s.pop("sfx")
        s["animate"] = bool(s.pop("key", False))
        out.append(s)
    return out


def _retry(fn, what: str):
    last = None
    for _ in range(3):
        try:
            return fn()
        except (Cancelled, UncertainRequest):
            raise
        except Exception as e:
            last = e
    raise RuntimeError(f"не удалось написать {what}: {last}")


HUD_ON = (
    "индикатор вверху экрана (воздух, расстояние, время, пульс, температура, глубина), "
    "icon: air | distance | time | heart | temp | depth. Только если уместен по сюжету; указывай, когда значение "
    "меняется или появляется новый индикатор; null — убрать. Если не уместен — не указывай вовсе."
)
HUD_OFF = 'не используй (не указывай поле "hud" вообще).'
SCRIPT_RULE = (
    "это и есть озвучка ролика. Разбей его на сцены по порядку и используй формулировки заказчика в \"text\" "
    "почти дословно (можно только сократить фразу до 1–2 предложений), не добавляй новых событий.\n<<<\n{}\n>>>"
)


def write(
    topic: str,
    minutes: float,
    hero: str,
    lang: str = "ru",
    log=print,
    genre: str = "auto",
    tone: str = "auto",
    narrator: str = "auto",
    ending: str = "auto",
    audience: str = "all",
    notes: str = "",
    checkpoint_dir: Path | None = None,
    script: str = "",
) -> dict:
    n = max(6, round(minutes * 60 / SECONDS_PER_SCENE))
    g = GENRES.get(genre, GENRES["auto"])
    base = {
        "topic": topic,
        "minutes": minutes,
        "n": n,
        "hero": hero,
        "lang": LANGS[lang]["name"],
        "genre": g["rules"],
        "hud_rule": HUD_ON if g["hud"] else HUD_OFF,
        "tone": TONES.get(tone, TONES["auto"])["text"],
        "narrator": NARRATORS.get(narrator, NARRATORS["auto"])["text"],
        "ending": ENDINGS.get(ending, ENDINGS["auto"])["text"],
        "audience": AUDIENCES.get(audience, AUDIENCES["all"])["text"],
        "notes": notes.strip() or "нет",
        "script": SCRIPT_RULE.format(script.strip()) if script.strip() else "нет — придумай текст сам",
    }

    def cached(name, fn):
        check_cancelled()
        path = (
            checkpoint_dir / (name + "-" + fingerprint(base) + ".json")
            if checkpoint_dir
            else None
        )
        if path and path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                pass
        value = fn()
        if path:
            atomic_json(path, value)
        return value

    if n <= 30:

        def one():
            d = _ask(ONE_SHOT.format(**base))
            d["scenes"] = _clean(d.get("scenes", []))
            if len(d["scenes"]) < n * 0.7:
                raise ValueError(f"мало сцен: {len(d['scenes'])} из {n}")
            return d

        data = cached("script", lambda: _retry(one, "сценарий"))
    else:

        def outline():
            d = _ask(OUTLINE.format(**base))
            if len(d.get("beats", [])) < n * 0.8:
                raise ValueError(f"в плане {len(d.get('beats', []))} сцен из {n}")
            return d

        data = cached("outline", lambda: _retry(outline, "план"))
        beats = data.pop("beats")
        plan = "\n".join(f"{i + 1}: {b}" for i, b in enumerate(beats))
        ranges = [(a, min(a + CHUNK, len(beats))) for a in range(0, len(beats), CHUNK)]
        log(f"сценарий: {len(beats)} сцен, пишу {len(ranges)} частей одновременно")

        def part(r):
            a, b = r

            def once():
                d = _ask(PART.format(**base, beats=plan, a=a + 1, b=b, count=b - a))
                got = _clean(d.get("scenes", []))
                if len(got) < (b - a) * 0.7:
                    raise ValueError(f"мало сцен в части: {len(got)}")
                return got

            return cached(f"part-{a}-{b}", lambda: _retry(once, f"сцены {a + 1}–{b}"))

        with ThreadPoolExecutor(
            min(4, len(ranges))
        ) as ex:  # части по плану независимы — пишем параллельно
            data["scenes"] = [s for chunk in ex.map(part, ranges) for s in chunk]
    data["lang"] = lang
    return data


def social(data: dict) -> dict:
    """Отдельные поля для каждой соцсети — каждое можно скопировать отдельно."""
    s = data.get("social", {})
    tags = lambda xs, sep=" ": sep.join(
        ("#" if sep == " " else "")
        + x.strip().lstrip("#").replace(" ", "" if sep == " " else " ")
        for x in xs or []
    )
    yt, ig, tt, fb = (
        s.get(k, {}) for k in ("youtube", "instagram", "tiktok", "facebook")
    )
    return {
        "youtube": {
            "Название": yt.get("title", data.get("title", "")),
            "Описание": yt.get("description", ""),
            "Теги": tags(yt.get("tags"), ", "),
        },
        "instagram": {
            "Подпись": ig.get("caption", ""),
            "Хэштеги": tags(ig.get("hashtags")),
        },
        "tiktok": {
            "Подпись": tt.get("caption", ""),
            "Хэштеги": tags(tt.get("hashtags")),
        },
        "facebook": {
            "Заголовок": fb.get("title", data.get("title", "")),
            "Текст": fb.get("text", ""),
            "Хэштеги": tags(fb.get("hashtags")),
        },
    }


def social_texts(data: dict) -> dict[str, str]:
    """Те же тексты файлами для архива."""
    return {
        f"{net}.txt": "\n\n".join(f"{k.upper()}:\n{v}" for k, v in fields.items())
        + "\n"
        for net, fields in social(data).items()
    }
