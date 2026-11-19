"""ИИ-помощник: кэш ответов на 30 дней и дневной лимит платных запросов (ASSISTANT_DAILY, по умолчанию 20)."""

import json
import threading
import time
from pathlib import Path

from . import writer
from .config import env, key
from .files import atomic_json, fingerprint
from .http import generation_key

LOCK = threading.Lock()
CACHE_DAYS = 30


class QuotaExceeded(RuntimeError):
    pass


def daily_limit() -> int:
    try:
        return max(0, int(env("ASSISTANT_DAILY") or 20))
    except ValueError:
        return 20


class Assistant:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _usage(self) -> Path:
        return self.root / f"usage-{time.strftime('%Y%m%d')}.json"

    def _used(self) -> int:
        try:
            return int(json.loads(self._usage().read_text())["used"])
        except (OSError, ValueError, KeyError, TypeError):
            return 0

    def left(self) -> int:
        return max(0, daily_limit() - self._used())

    def ask(self, kind: str, params: dict, fresh: bool = False) -> tuple[dict, bool]:
        """Возвращает (ответ, взят_из_кэша). fresh=True — новый вариант, тратит запрос из лимита."""
        path = self.root / f"{kind}-{fingerprint(params)}.json"
        if not fresh and path.is_file() and time.time() - path.stat().st_mtime < CACHE_DAYS * 86400:
            try:
                return json.loads(path.read_text(encoding="utf-8")), True
            except ValueError:
                pass
        with LOCK:
            if self.left() <= 0:
                raise QuotaExceeded("Лимит ИИ-запросов на сегодня исчерпан. Выберите тему из библиотеки")
            self.root.mkdir(parents=True, exist_ok=True)
            atomic_json(self._usage(), {"used": self._used() + 1})
        with generation_key(key()):
            if kind == "topics":
                result = {"topics": writer.topics(params["query"], params["lang"])}
            else:
                result = writer.draft(params["topic"], params["minutes"], params["lang"])
        atomic_json(path, result)
        return result, False
