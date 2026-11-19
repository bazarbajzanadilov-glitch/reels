"""Общие настройки. Всё генерируется через один ключ Pollinations (POLLINATIONS_KEY в .env)."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"
JOBS = ROOT / "jobs"  # результаты заказов с веб-страницы
ASSETS = ROOT / "assets"
API = "https://gen.pollinations.ai"

FPS = 30
# Параллельные запросы к API (у Pollinations лимит ~60 запросов/мин на модель)
NET_TTS = min(16, max(1, int(os.environ.get("NET_TTS", "8"))))
NET_IMAGES = min(16, max(1, int(os.environ.get("NET_IMAGES", "6"))))
NET_VIDEO = min(16, max(1, int(os.environ.get("NET_VIDEO", "8"))))
# Форматы: размер видео и размер генерируемых картинок
FORMATS = {
    "vertical": {
        "size": (1080, 1920),
        "image": (768, 1344),
        "aspect": "9:16",
        "cover": (1080, 1920),
    },
    "horizontal": {
        "size": (1920, 1080),
        "image": (1344, 768),
        "aspect": "16:9",
        "cover": (1280, 720),
    },
}
SCENE_PAD = 0.25  # пауза после фразы, сек
SECONDS_PER_SCENE = 6.3  # для расчёта числа сцен по длине ролика

BUDGET_SAFETY = (
    1.00  # планируем на весь лимит; перед анимацией пересчёт по реально потраченному
)

# Модели Pollinations
TEXT_MODEL = "openai/gpt-5.6-luna"  # сценарий и тексты для соцсетей
IMAGE_MODEL = "flux"
IMAGE_MODEL_REF = "black-forest-labs/flux.2-klein-4b"  # точное сходство с референсом
# Видео-модели на выбор клиента. price — $ за 5-секундный клип, params — доп. параметры запроса.
VIDEO_MODELS = {
    "pvideo": {
        "label": "P-Video",
        "note": "720p",
        "model": "prunaai/p-video",
        "price": 0.10,
        "params": {"resolution": "720p"},
    },
    "grok": {
        "label": "Grok Lite",
        "note": "720p",
        "model": "x-ai/grok-imagine-video-1.5-lite",
        "price": 0.16,
        "params": {"resolution": "720p"},
    },
    "seedance2": {
        "label": "Seedance 2.0",
        "note": "плавнее, 480p",
        "model": "bytedance/seedance-2.0-mini",
        "price": 0.20,
        "params": {"resolution": "480p"},
    },
}
VIDEO_DEFAULT = "pvideo"
VIDEO_MODEL_FALLBACK = (
    "bytedance/seedance-1-pro-fast"  # если фильтр модели отклонил сцену; 480p, $0.05
)

# Языки: название для сценариста и подпись на сайте
LANGS = {
    "ru": {"name": "русский", "label": "RU"},
    "kk": {"name": "казахский (қазақ тілі, кириллица)", "label": "KZ"},
    "en": {"name": "English", "label": "EN"},
    "de": {"name": "Deutsch", "label": "DE"},
}

# Голоса. price — $ за символ текста (замерено на пробах), kk — проверка казахского через распознавание.
VOICES = {
    "gemini": {
        "label": "Gemini",
        "model": "google/gemini-3.8-flash-tts",
        "price": 0.000019,
        "kk": "99%",
        "default": "Charon",
        "male": [
            "Charon",
            "Orus",
            "Fenrir",
            "Puck",
            "Iapetus",
            "Algieba",
            "Alnilam",
            "Enceladus",
            "Umbriel",
            "Rasalgethi",
            "Sadaltager",
            "Zubenelgenubi",
            "Schedar",
            "Achird",
            "Algenib",
            "Sadachbia",
        ],
        "female": [
            "Kore",
            "Aoede",
            "Leda",
            "Zephyr",
            "Callirrhoe",
            "Autonoe",
            "Despina",
            "Erinome",
            "Laomedeia",
            "Achernar",
            "Gacrux",
            "Pulcherrima",
            "Vindemiatrix",
            "Sulafat",
        ],
    },
    "eleven": {
        "label": "ElevenLabs",
        "model": "elevenlabs/eleven-v4-turbo",
        "price": 0.00004,
        "kk": "97%",
        "default": "adam",
        "male": [
            "adam",
            "brian",
            "daniel",
            "george",
            "james",
            "josh",
            "liam",
            "callum",
            "charlie",
            "bill",
            "arnold",
            "antoni",
            "sam",
            "fin",
        ],
        "female": [
            "rachel",
            "sarah",
            "charlotte",
            "lily",
            "matilda",
            "emily",
            "bella",
            "elli",
            "domi",
            "dorothy",
        ],
    },
    "openai": {
        "label": "OpenAI",
        "model": "openai/tts-1-hd",
        "price": 0.00003,
        "kk": "94%",
        "default": "onyx",
        "male": ["onyx", "echo", "fable"],
        "female": ["nova", "shimmer", "alloy"],
    },
}
for _v in VOICES.values():
    _v["voices"] = _v["male"] + _v["female"]

# Стили видео: описание для генератора картинок и анимации
# Жанры сюжета: как писать текст. hud — уместен ли индикатор вверху экрана.
GENRES = {
    "auto": {
        "label": "Авто",
        "hud": False,
        "rules": "Художественный РАССКАЗ с сюжетом по теме: герой, завязка, нарастающий конфликт, поворот, "
        "яркая развязка. Повествование от третьего лица, живые детали и эмоции. Настроение (драма, "
        "приключение, юмор, мистика, хоррор) выбери сам под тему. Это НЕ инструкция и НЕ пособие: "
        "никаких советов, правил, «что делать» и обращений к зрителю с наставлениями.",
    },
    "survival": {
        "label": "Выживание",
        "hud": True,
        "rules": "Жанр «что будет, если… / как выжить». Обращение на «ты», настоящее время, нарастающая "
        "опасность. Факты правдивые. В конце — что делать на самом деле.",
    },
    "story": {
        "label": "История",
        "hud": False,
        "rules": "Художественная история с сюжетом: завязка, конфликт, поворот, развязка. Рассказ от третьего лица "
        "о герое, живые детали, эмоции, диалоги-реплики. Никаких советов и инструкций.",
    },
    "horror": {
        "label": "Хоррор",
        "hud": False,
        "rules": "Страшная история: атмосфера, саспенс, недосказанность, нарастающий ужас, неожиданный финальный "
        "поворот. Без советов и инструкций, без жестоких подробностей.",
    },
    "mystery": {
        "label": "Детектив",
        "hud": False,
        "rules": "Загадка или детектив: странное событие, улики, ложные следы, герой разгадывает тайну, "
        "неожиданная разгадка в конце. Зритель должен пытаться угадать.",
    },
    "comedy": {
        "label": "Комедия",
        "hud": False,
        "rules": "Смешная история: абсурдные ситуации, неожиданные шутки, ирония, нелепые повороты, "
        "комичный финал. Лёгкий тон, без нравоучений.",
    },
    "facts": {
        "label": "Факты",
        "hud": True,
        "rules": "Научпоп: удивительные правдивые факты по теме, каждый следующий удивительнее предыдущего, "
        "простые сравнения, «вау»-моменты. Без выдумок.",
    },
    "motivation": {
        "label": "Мотивация",
        "hud": False,
        "rules": "Вдохновляющая история: герой проходит через трудности, падает и поднимается, сильные "
        "эмоции, яркий финал с мыслью, которая цепляет.",
    },
    "fairy": {
        "label": "Сказка",
        "hud": False,
        "rules": "Сказка или фэнтези: волшебный мир, необычные существа, испытания героя, добрый или "
        "неожиданный финал с моралью.",
    },
}
for key, label, rules in [
    ("scifi", "Фантастика", "Научная фантастика: технологии, необычный мир и последовательный сюжет."),
    ("adventure", "Приключения", "Приключенческий рассказ: путешествие, препятствия и яркая развязка."),
    ("drama", "Драма", "Эмоциональная драма с живыми персонажами и убедительным конфликтом."),
    ("romance", "Романтика", "Романтическая история с развитием отношений и эмоциональной развязкой."),
    ("documentary", "Документальный", "Документальный рассказ: проверяемые факты, без выдуманных свидетельств."),
    ("education", "Обучающий", "Понятно объясни тему на конкретных примерах, последовательно и без воды."),
    ("custom", "Свой вариант", "Следуй жанру и сюжету, описанным в пожеланиях заказчика."),
]:
    GENRES[key] = {"label": label, "hud": False, "rules": rules}


# Тон истории: text — для сценариста, mood — настроение картинок (свет, палитра).
TONES = {
    "auto": {"label": "Авто", "text": "подбери под тему и жанр", "mood": ""},
    "tense": {
        "label": "Напряжённый",
        "text": "напряжённый, держит в тревоге и ожидании",
        "mood": "dramatic tense lighting, high contrast, cinematic shadows",
    },
    "dark": {
        "label": "Мрачный",
        "text": "мрачный, тяжёлый, гнетущий",
        "mood": "dark moody palette, deep shadows, cold light",
    },
    "funny": {
        "label": "Весёлый",
        "text": "весёлый, лёгкий, с юмором",
        "mood": "bright cheerful colors, soft sunny light",
    },
    "touching": {
        "label": "Трогательный",
        "text": "трогательный, тёплый, вызывает эмоции",
        "mood": "warm soft golden light, gentle colors",
    },
    "epic": {
        "label": "Эпичный",
        "text": "эпичный, масштабный, героический",
        "mood": "epic cinematic lighting, grand scale, god rays",
    },
    "calm": {
        "label": "Спокойный",
        "text": "спокойный, размеренный, уютный",
        "mood": "soft calm pastel light, cozy atmosphere",
    },
}
NARRATORS = {
    "auto": {"label": "Авто", "text": "выбери сам под жанр"},
    "third": {
        "label": "От 3-го лица",
        "text": "от третьего лица: рассказчик говорит о герое («он», «она»)",
    },
    "first": {
        "label": "От 1-го лица",
        "text": "от первого лица: герой сам рассказывает («я»)",
    },
    "you": {
        "label": "На «ты»",
        "text": "обращение к зрителю на «ты», зритель — главный герой",
    },
}
ENDINGS = {
    "auto": {"label": "Авто", "text": "выбери сам под жанр и тон"},
    "happy": {"label": "Счастливый", "text": "счастливый финал"},
    "sad": {"label": "Грустный", "text": "грустный или трагичный финал"},
    "twist": {
        "label": "Поворот",
        "text": "неожиданный поворот в самом конце, который меняет смысл истории",
    },
    "open": {"label": "Открытый", "text": "открытый финал, зритель сам додумывает"},
}
AUDIENCES = {
    "all": {"label": "Для всех", "text": "широкая аудитория"},
    "kids": {
        "label": "Детям",
        "text": "дети 6–12 лет: простые слова, без страшных и жестоких деталей, добрый смысл",
    },
    "teens": {
        "label": "Подросткам",
        "text": "подростки: динамично, современно, без занудства",
    },
    "adults": {
        "label": "Взрослым",
        "text": "взрослые: глубже, сложнее, можно серьёзные темы (без натурализма)",
    },
}

# Стили видео. prompt — для картинок, motion — для анимации, budget — потолок цены ($ за 1 мин, $ за 15 мин).
STYLES = {
    "2d": {
        "label": "2D мультфильм",
        "budget": (0.35, 2.00),
        "prompt": "flat 2D vector illustration, minimalist cartoon style, cinematic palette, "
        "soft cinematic rim light, simple clean shapes, smooth gradients",
        "motion": "Flat 2D cartoon animation, simple smooth motion",
    },
    "3d": {
        "label": "3D мультфильм",
        "budget": (0.45, 4.00),
        "camera_fly": True,
        "prompt": "3D animated movie still, Pixar-like stylized 3D render, soft global illumination, subsurface skin, "
        "detailed textures, cinematic depth of field, volumetric light",
        "motion": "3D animated film shot with a dynamic cinematic camera fly-through around the hero "
        "(smooth dolly, orbit or crane move), strong parallax depth",
    },
    "anime": {
        "label": "Аниме",
        "budget": (0.35, 2.00),
        "prompt": "anime style illustration, cel shading, bold clean line art, expressive eyes, vibrant colors, "
        "dramatic anime lighting",
        "motion": "Anime animation, expressive smooth motion",
    },
    "real": {
        "label": "Реализм",
        "budget": (0.35, 2.00),
        "prompt": "photorealistic cinematic film still, realistic human, natural skin, 35mm lens, "
        "dramatic cinematic lighting, shallow depth of field",
        "motion": "Realistic cinematic footage, natural motion",
    },
    "comic": {
        "label": "Комикс",
        "budget": (0.35, 2.00),
        "prompt": "comic book illustration, bold ink outlines, halftone shading, dynamic composition, "
        "saturated graphic colors",
        "motion": "Comic book style animation, punchy motion",
    },
}
for key, label, prompt in [
    ("watercolor", "Акварель", "watercolor illustration, textured paper, soft pigments"),
    ("clay", "Пластилин", "claymation, handmade clay characters, stop motion aesthetic"),
    ("pixel", "Пиксель-арт", "pixel art, retro game aesthetic, crisp pixel edges"),
    ("noir", "Нуар", "film noir, monochrome, dramatic high contrast shadows"),
    ("paper", "Бумажный", "layered paper cutout illustration, handmade paper textures"),
    ("custom", "Свой вариант", "cinematic illustration"),
]:
    STYLES[key] = {"label": label, "budget": (0.35, 2.00), "prompt": prompt, "motion": "Smooth cinematic motion"}

STYLE_TAIL = ", no text, no letters, no watermark"
STYLE = STYLES["2d"]["prompt"] + STYLE_TAIL
CHARACTER = (
    "a simple cartoon young man with short dark hair, round face, "
    "mustard-yellow sweater and dark pants"
)

# Цвета оформления (RGB)
RED = (235, 64, 52)
GOLD = (222, 170, 90)
WHITE = (245, 245, 245)
PANEL = (18, 18, 24)


def env(name: str) -> str | None:
    """Значение из переменной окружения или из файла .env в корне проекта."""
    if os.environ.get(name):
        return os.environ[name]
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip() or None
    return None


def key() -> str:
    k = env("POLLINATIONS_KEY")
    if not k:
        raise RuntimeError("нет POLLINATIONS_KEY в .env")
    return k
