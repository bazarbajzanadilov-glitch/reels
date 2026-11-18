"""One provider-limited credential per job; secrets never enter downloadable outputs."""

import json
import math
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .config import API
from .files import atomic_json, path_lock
from .http import generation_key, request
from .execution import Cancelled

LOCK = threading.RLock()
SECRET_FILE = ".budget-key.json"  # Legacy migration only.


def secret_path(directory: Path) -> Path:
    return directory.parent / ".private" / directory.name / "budget.json"


def _write(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    path.parent.parent.chmod(0o700)
    atomic_json(path, data)


def record(directory: Path) -> dict:
    path = secret_path(directory)
    legacy = directory / SECRET_FILE
    if not path.exists() and legacy.is_file():
        with LOCK, path_lock(path):
            if not path.exists():
                _write(path, json.loads(legacy.read_text(encoding="utf-8")))
            legacy.unlink(missing_ok=True)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def credential(directory: Path) -> str | None:
    return record(directory).get("key")


def public(directory: Path) -> dict:
    data = record(directory)
    return {
        k: v
        for k, v in data.items()
        if k in ("cap", "allocated", "prior_spent", "state", "remaining")
    }


def _resolve_unused(path: Path, data: dict):
    # A lost creation response exposes no child token to the pipeline, so the orphan was never used by us.
    # Revoke the exact persisted unique name before permitting another allocation.
    if not data.get("name"):
        raise RuntimeError(
            "Неизвестная прежняя попытка создания ключа: требуется проверка в кабинете провайдера"
        )
    listing = json.loads(request(f"{API}/account/keys", tries=1))
    matches = [
        item for item in listing.get("data", []) if item.get("name") == data["name"]
    ]
    if not matches:
        raise RuntimeError(
            "Провайдер ещё не подтвердил создание ключа; повторное выделение заблокировано"
        )
    for item in matches:
        if item.get("enabled", True):
            data.update(state="revoking", id=item["id"])
            _write(path, data)
            request(f"{API}/account/keys/{item['id']}", method="DELETE", tries=1)
    # An acknowledged revocation makes replacement safe; the old credential never reached generation.
    data.update(state="resolved-unused")
    _write(path, data)


def provision(directory: Path, cap: float, prior_spent: float = 0.0) -> str:
    if (
        not math.isfinite(cap)
        or cap <= 0
        or not math.isfinite(prior_spent)
        or prior_spent < 0
    ):
        raise RuntimeError("Некорректный бюджет задачи")
    directory.mkdir(parents=True, exist_ok=True)
    record(directory)  # Migrate an old private key before locking its new location.
    path = secret_path(directory)
    with LOCK, path_lock(path):
        data = record(directory)
        if data.get("key"):
            if float(data["cap"]) > cap + 0.000001:
                raise RuntimeError("Лимит существующего ключа выше бюджета задачи")
            info = json.loads(
                request(f"{API}/account/key", api_key=data["key"], tries=1)
            )
            available = info.get("pollenBudget")
            if (
                info.get("valid") is False
                or not isinstance(available, (int, float))
                or not math.isfinite(available)
            ):
                raise RuntimeError(
                    "Ограниченный ключ недействителен или его остаток не подтверждён"
                )
            if available <= 0:
                raise RuntimeError("Бюджет ролика исчерпан")
            if available > float(data["allocated"]) + 0.000001:
                raise RuntimeError(
                    "Лимит ключа был изменён вне задачи; генерация заблокирована"
                )
            return data["key"]
        if data and data.get("state") != "resolved-unused":
            _resolve_unused(path, data)
        remaining = math.floor((cap - prior_spent) * 1000 + 1e-9) / 1000
        if remaining <= 0:
            raise RuntimeError("Бюджет ролика исчерпан")
        permissions = json.loads(request(f"{API}/account/key", tries=1))
        if "keys" not in (permissions.get("permissions") or {}).get("account", []):
            raise RuntimeError(
                "Ключу провайдера нужны права account:keys; генерация не запускалась"
            )
        name = f"shorts-factory:{directory.name}:{uuid.uuid4().hex[:12]}"
        _write(
            path,
            {
                "cap": cap,
                "allocated": remaining,
                "state": "creating",
                "name": name,
                "created": time.time(),
            },
        )
        payload = {
            "name": name,
            "type": "secret",
            "pollenBudget": remaining,
            "accountPermissions": ["usage"],
        }
        try:
            created = json.loads(
                request(
                    f"{API}/account/keys",
                    json.dumps(payload).encode(),
                    {"Content-Type": "application/json"},
                    tries=1,
                )
            )
            child = created["key"]
            reported = float(created["pollenBudget"])
            if (
                not child
                or not math.isfinite(reported)
                or reported < 0
                or reported > remaining + 0.000001
            ):
                raise ValueError("Invalid provider budget")
            _write(
                path,
                {
                    "cap": cap,
                    "allocated": remaining,
                    "prior_spent": prior_spent,
                    "key": child,
                    "id": created["id"],
                    "state": "ready",
                    "name": name,
                },
            )
        except Cancelled:
            data = json.loads(path.read_text())
            data["state"] = "resolved-unused"
            _write(path, data)
            raise
        except Exception as error:
            raise RuntimeError(
                "Не удалось подтвердить бюджетный ключ. Генерация остановлена; следующий повтор сначала проверит незавершённое создание"
            ) from error
        return child


@contextmanager
def limit(directory: Path, cap: float, prior_spent: float = 0.0):
    with path_lock(directory / ".pipeline"):
        child = provision(directory, cap, prior_spent)
        with generation_key(child):
            yield
