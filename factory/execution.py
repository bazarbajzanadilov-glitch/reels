"""Per-operation execution context, explicitly copied into background work."""

from concurrent.futures import ThreadPoolExecutor as BaseExecutor
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class Cancelled(RuntimeError):
    pass


class OfflineOnly(RuntimeError):
    pass


class UncertainRequest(RuntimeError):
    """A paid request may have reached the provider; never blindly repeat it."""


@dataclass(frozen=True)
class Operation:
    token: str | None = None
    cancel_path: Path | None = None
    audit: Callable | None = None
    run_id: str | None = None
    offline: bool = False


CURRENT = ContextVar("shorts_operation", default=Operation())


@contextmanager
def operation(*, token=None, cancel_path=None, audit=None, run_id=None, offline=None):
    previous = CURRENT.get()
    value = Operation(
        token if token is not None else previous.token,
        Path(cancel_path) if cancel_path is not None else previous.cancel_path,
        audit if audit is not None else previous.audit,
        run_id if run_id is not None else previous.run_id,
        offline if offline is not None else previous.offline,
    )
    reset = CURRENT.set(value)
    try:
        yield value
    finally:
        CURRENT.reset(reset)


def check_cancelled():
    path = CURRENT.get().cancel_path
    if path is not None and path.exists():
        raise Cancelled("Создание остановлено")


class ThreadPoolExecutor(BaseExecutor):
    def submit(self, fn, /, *args, **kwargs):
        context = copy_context()
        return super().submit(context.run, fn, *args, **kwargs)
