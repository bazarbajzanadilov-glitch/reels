"""Provider transport with isolated credentials and a durable attempt journal."""

import json
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from urllib.parse import parse_qs, urlparse

from .config import API, key
from .execution import (
    CURRENT,
    OfflineOnly,
    UncertainRequest,
    check_cancelled,
    operation,
)


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if (
            redirected is not None
            and urlparse(newurl).hostname != urlparse(req.full_url).hostname
        ):
            redirected.remove_header("Authorization")
        if urlparse(newurl).scheme != "https":
            raise RuntimeError("Небезопасное перенаправление провайдера")
        return redirected


def _open(req, timeout):
    return urllib.request.build_opener(SafeRedirect()).open(req, timeout=timeout)


@contextmanager
def generation_key(value: str):
    with operation(token=value):
        yield


def _describe(url, data):
    parsed = urlparse(url)
    kind = next(
        (
            name
            for prefix, name in [
                ("/image/", "image"),
                ("/video/", "video"),
                ("/v1/audio/speech", "speech"),
                ("/v1/chat/completions", "text"),
            ]
            if parsed.path.startswith(prefix)
        ),
        "account",
    )
    model = parse_qs(parsed.query).get("model", [None])[0]
    if model is None and data and kind in ("speech", "text"):
        try:
            model = json.loads(data).get("model")
        except (ValueError, AttributeError):
            pass
    return kind, model


def _pause(seconds):
    end = time.monotonic() + min(60, max(0, seconds))
    while time.monotonic() < end:
        check_cancelled()
        time.sleep(min(0.25, max(0, end - time.monotonic())))


def request(
    url: str,
    data: bytes | None = None,
    headers: dict | None = None,
    timeout: int = 180,
    tries: int = 3,
    api_key: str | None = None,
    method: str | None = None,
) -> bytes:
    if CURRENT.get().offline:
        raise OfflineOnly(
            "Для бесплатного перемонтажа не хватает сохранённых материалов"
        )
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in (
        urlparse(API).hostname,
        "media.pollinations.ai",
    ):
        raise RuntimeError("Недопустимый адрес провайдера")
    account = parsed.path.startswith("/account/")
    context = CURRENT.get()
    kind, model = _describe(url, data)
    paid = kind in ("image", "video", "speech", "text")
    if paid and not (api_key or context.token):
        raise RuntimeError("Платный запрос без отдельного ключа задачи заблокирован")
    token = api_key or (None if account else context.token) or key()
    h = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "shorts-factory/2.1",
        **(headers or {}),
    }
    for attempt in range(max(1, tries)):
        check_cancelled()
        event_id = (
            context.audit({"state": "started", "kind": kind, "model": model})
            if context.audit and paid
            else None
        )

        def finish(state, **extra):
            if event_id is not None:
                context.audit({"id": event_id, "state": state, **extra})

        try:
            with _open(
                urllib.request.Request(url, data=data, headers=h, method=method),
                timeout=timeout,
            ) as response:
                content = response.read()
                finish(
                    "succeeded",
                    status=getattr(response, "status", 200),
                    bytes=len(content),
                )
                return content
        except urllib.error.HTTPError as error:
            body = error.read()[:1000].lower()
            if paid and error.code >= 500:
                finish("uncertain", status=error.code)
                raise UncertainRequest(
                    "Ответ провайдера не подтверждён. Автоматический платный повтор остановлен"
                ) from error
            finish("rejected", status=error.code)
            if error.code == 402:
                raise RuntimeError(
                    "Бюджет ключа исчерпан или на балансе провайдера закончились деньги"
                ) from error
            if error.code != 429 and (error.code < 500 or attempt == tries - 1):
                reason = (
                    "content_policy"
                    if b"content_policy" in body or b"flagged" in body
                    else "запрос отклонён"
                )
                raise RuntimeError(f"Провайдер: HTTP {error.code}, {reason}") from error
            if attempt == tries - 1:
                raise RuntimeError(
                    "Провайдер временно ограничил число запросов"
                ) from error
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
            finish("uncertain" if paid else "failed")
            if paid:
                raise UncertainRequest(
                    "Связь оборвалась после отправки. Возможное списание проверяется; автоматический повтор остановлен"
                ) from error
            if attempt == tries - 1:
                raise RuntimeError("Провайдер недоступен") from error
        _pause(3 * (attempt + 1))


def post_json(url: str, payload: dict, timeout: int = 180) -> bytes:
    return request(
        url,
        json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(),
        {"Content-Type": "application/json"},
        timeout,
    )
