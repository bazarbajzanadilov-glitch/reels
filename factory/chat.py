"""Чат-помощник по идеям: клиент переписывается с GPT или Claude, модель подкидывает темы роликов.

Запрос уходит только по нажатию «Отправить»; сам ролик по-прежнему создаётся отдельной кнопкой.
"""

import json

from .config import API, key
from .http import request

MODELS = {
    "gpt": {"label": "GPT", "model": "openai/gpt-5.6-luna"},
    "claude": {"label": "Claude", "model": "anthropic/claude-sonnet-5"},
}
MAX_MESSAGES = 30
MAX_CHARS = 4000

SYSTEM = """Ты креативный продюсер коротких вирусных роликов (TikTok, YouTube Shorts, Instagram Reels, YouTube).
Помогаешь автору придумать идею ролика: задаёшь уточняющие вопросы, если запрос размытый, и предлагаешь идеи.
Когда предлагаешь идеи, пиши каждую ОТДЕЛЬНОЙ строкой списка, начиная с «- », одной фразой до 150 символов,
без кавычек и без пояснений в той же строке — так автор сможет одним нажатием взять её в работу.
Пояснения, если нужны, — отдельным коротким абзацем до или после списка.
Идеи конкретные, с сильным крючком, без пересказа известных фильмов и игр.
Отвечай на языке собеседника, коротко и по делу, без Markdown-заголовков и таблиц."""


class ChatError(ValueError):
    pass


def clean_messages(messages) -> list[dict]:
    if not isinstance(messages, list) or not messages:
        raise ChatError("Напишите сообщение")
    out = []
    for item in messages[-MAX_MESSAGES:]:
        if not isinstance(item, dict) or item.get("role") not in ("user", "assistant"):
            raise ChatError("Некорректная история чата")
        content = str(item.get("content") or "").strip()[:MAX_CHARS]
        if content:
            out.append({"role": item["role"], "content": content})
    if not out or out[-1]["role"] != "user":
        raise ChatError("Последним должно быть сообщение пользователя")
    return out


def reply(model: str, messages) -> str:
    if model not in MODELS:
        raise ChatError("Неизвестная модель")
    payload = {
        "model": MODELS[model]["model"],
        "messages": [{"role": "system", "content": SYSTEM}, *clean_messages(messages)],
    }
    raw = request(
        f"{API}/v1/chat/completions",
        json.dumps(payload, ensure_ascii=False).encode(),
        {"Content-Type": "application/json"},
        timeout=120,
        tries=1,
        api_key=key(),
    )
    text = json.loads(raw)["choices"][0]["message"]["content"]
    if isinstance(text, list):  # некоторые провайдеры отдают части
        text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
    text = str(text or "").strip()
    if not text:
        raise RuntimeError("Модель вернула пустой ответ")
    return text
