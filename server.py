"""Веб-страница: клиент вводит тему, выбирает формат — получает видео, обложку и тексты для соцсетей.

    python server.py            # http://localhost:8000
Пароль — ACCESS_PASSWORD (логин любой); без него разрешён только локальный доступ.
"""

import base64
import io
import hmac
import ipaddress
import ssl
import json
import os
import re
import threading
import time
import logging
import subprocess
import sys
import socket
import shutil
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse


from factory import cost, subtitles, editing, alignment
from factory.config import (
    API,
    AUDIENCES,
    ENDINGS,
    GENRES,
    JOBS,
    LANGS,
    NARRATORS,
    ROOT,
    STYLES,
    TONES,
    VIDEO_MODELS,
    VOICES,
    env,
)
from factory.http import request
from factory.files import atomic_bytes, jpeg_bytes, fingerprint
from factory.limits import BoundedHTTPServer, RateLimiter
from factory.store import JobStore, QueueFull
from factory.validation import (
    InvalidRequest,
    PayloadTooLarge,
    MAX_BODY,
    job_options,
    reference_image,
    estimate_options,
)

PORT = int(os.environ.get("PORT", 8000))
HOST = os.environ.get("HOST", "127.0.0.1")
FILES = {
    "subtitles.ass": "text/plain; charset=utf-8",
    "subtitles.srt": "application/x-subrip; charset=utf-8",
    "social.json": "application/json; charset=utf-8",
    "video.mp4": "video/mp4",
    "cover.jpg": "image/jpeg",
    "result.zip": "application/zip",
    "youtube.txt": "text/plain; charset=utf-8",
    "instagram.txt": "text/plain; charset=utf-8",
    "tiktok.txt": "text/plain; charset=utf-8",
    "facebook.txt": "text/plain; charset=utf-8",
}
MAX_QUEUE = 20
RATE = RateLimiter()
HEAVY = threading.BoundedSemaphore(2)
STORES = {}
STORE_LOCK = threading.RLock()
LOG = logging.getLogger("shorts.web")


def jobs_store():
    path = JOBS.resolve()
    with STORE_LOCK:
        if path not in STORES:
            STORES[path] = JobStore(path)
        return STORES[path]


def job_path(jid: str) -> Path:
    return JOBS / jid / "job.json"


def load(jid: str) -> dict:
    return jobs_store().get(jid)


def save(job: dict) -> None:
    jobs_store().put(job)


def all_jobs() -> list[dict]:
    return jobs_store().list()


def restore() -> None:
    jobs_store()  # Import old history; only the exclusive worker recovers interrupted jobs.


def supervise_worker(stop):
    process = None
    while not stop.is_set():
        try:
            if not jobs_store().healthy() and (
                process is None or process.poll() is not None
            ):
                process = subprocess.Popen(
                    [
                        sys.executable,
                        str(ROOT / "worker.py"),
                        "--jobs",
                        str(JOBS.resolve()),
                    ],
                    cwd=ROOT,
                    start_new_session=True,
                )
        except Exception:
            LOG.exception("Could not start job worker")
        stop.wait(5)


# ---------- HTTP ----------


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(15)
        super().setup()

    def _read_json(self, maximum=MAX_BODY):
        try:
            if (
                self.headers.get("Transfer-Encoding")
                or len(self.headers.get_all("Content-Length", [])) > 1
            ):
                raise InvalidRequest("Некорректные заголовки запроса")
            length = int(self.headers.get("Content-Length", 0))
            if length < 0 or length > maximum:
                raise PayloadTooLarge(
                    f"Запрос слишком большой: максимум {maximum // 1024} КБ"
                )
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise InvalidRequest("Запрос получен не полностью")
            value = json.loads(
                raw or b"{}",
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
            )
            if not isinstance(value, dict):
                raise InvalidRequest("Ожидается объект настроек")
            return value
        except (ValueError, UnicodeError) as error:
            self.close_connection = True
            if isinstance(error, InvalidRequest):
                raise
            raise InvalidRequest("Некорректный JSON-запрос") from None

    def _client_ip(self) -> str:
        """Настоящий IP посетителя. За nginx (BEHIND_PROXY=1) все запросы приходят с 127.0.0.1 —
        тогда берём X-Real-IP, который выставляет наш nginx; иначе все делили бы один лимит."""
        peer = self.client_address[0]
        if env("BEHIND_PROXY") == "1" and ipaddress.ip_address(peer).is_loopback:
            real = (self.headers.get("X-Real-IP") or "").strip()
            try:
                return str(ipaddress.ip_address(real))
            except ValueError:
                pass
        return peer

    def _limited(self, group, limit):
        if RATE.allow((self._client_ip(), group), limit):
            return False
        self.send_response(429)
        self.send_header("Retry-After", "60")
        self.send_header("Content-Length", "0")
        self.end_headers()
        self.close_connection = True
        return True

    def log_message(self, *a):  # тише в консоли
        pass

    def _auth(self) -> bool:
        pw = env("ACCESS_PASSWORD")
        if not pw:
            try:
                host = urlparse("//" + self.headers.get("Host", "")).hostname
            except ValueError:
                host = None
            if ipaddress.ip_address(self.client_address[0]).is_loopback and host in (
                "localhost",
                "127.0.0.1",
                "::1",
            ):
                return True
            self._json({"error": "Удалённый доступ требует ACCESS_PASSWORD"}, 403)
            return False
        h = self.headers.get("Authorization", "")
        if h.startswith("Basic "):
            try:
                user, given = base64.b64decode(h[6:]).decode().split(":", 1)
                login = env("ACCESS_LOGIN")  # если задан — логин тоже проверяется
                if hmac.compare_digest(given.encode(), pw.encode()) and (
                    not login or hmac.compare_digest(user.encode(), login.encode())
                ):
                    return True
            except Exception:
                pass
        if self._limited("auth-fail", 10):
            return False
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Shorts Factory"')
        self.end_headers()
        return False

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(b)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        # по умолчанию ничего не кэшируется; файлы задают свою политику в _file
        self.send_header("Cache-Control", getattr(self, "_cache_control", None) or "no-store")
        self._cache_control = None
        super().end_headers()

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            self._get()
        except InvalidRequest as error:
            self._json({"error": str(error)}, error.status)
        except (ValueError, TypeError, OverflowError):
            self._json({"error": "Некорректные параметры запроса"}, 400)
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            return
        except Exception:
            LOG.exception("GET failed")
            self._json({"error": "Временная ошибка сервера"}, 500)

    def _get(self):
        if urlparse(self.path).path == "/api/health":
            ready = jobs_store().healthy()
            return self._json({"ready": ready, "worker": ready}, 200 if ready else 503)
        if not self._auth():
            return
        if (
            urlparse(self.path).path.startswith("/api/")
            and self.headers.get("Sec-Fetch-Site") == "cross-site"
        ):
            return self._json({"error": "Запрос с другого сайта запрещён"}, 403)
        u = urlparse(self.path)
        parts = u.path.strip("/").split("/")
        static_files = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/index.html": ("index.html", "text/html; charset=utf-8"),
            "/app.css": ("app.css", "text/css; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            **{
                f"/{name}.js": (f"{name}.js", "text/javascript; charset=utf-8")
                for name in (
                    "subtitle-controls",
                    "job-editor",
                    "preferences",
                    "bootstrap",
                )
            },
        }
        if u.path in static_files:
            name, ctype = static_files[u.path]
            self._file(ROOT / "web" / name, ctype)
        elif u.path == "/api/estimate":
            self._json(cost.estimate(**estimate_options(parse_qs(u.query))))
        elif u.path == "/api/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            if self.command == "HEAD":
                return
            previous = None
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                current = jobs_store().revision()
                if current != previous:
                    self.wfile.write(f"data: {current}\n\n".encode())
                    self.wfile.flush()
                    previous = current
                time.sleep(0.5)
            return
        elif re.fullmatch(r"/api/jobs/[\w-]+/script", u.path):
            jid = u.path.split("/")[3]
            load(jid)
            value = editing.load_script(JOBS / jid)
            value["srt"] = (
                (JOBS / jid / "subtitles.srt").read_text(encoding="utf-8")
                if (JOBS / jid / "subtitles.srt").exists()
                else ""
            )
            self._json(value)
        elif u.path == "/api/options":
            self._json(
                {
                    "word_timing": alignment.available(),
                    "langs": {k: v["label"] for k, v in LANGS.items()},
                    "voices": {
                        k: {
                            "label": v["label"],
                            "male": v["male"],
                            "female": v["female"],
                            "default": v["default"],
                        }
                        for k, v in VOICES.items()
                    },
                    "styles": {k: v["label"] for k, v in STYLES.items()},
                    "genres": {k: v["label"] for k, v in GENRES.items()},
                    **{
                        name: {k: v["label"] for k, v in opts.items()}
                        for name, opts in (
                            ("tones", TONES),
                            ("narrators", NARRATORS),
                            ("endings", ENDINGS),
                            ("audiences", AUDIENCES),
                        )
                    },
                    "video_models": {
                        k: {"label": v["label"], "note": v["note"], "price": v["price"]}
                        for k, v in VIDEO_MODELS.items()
                    },
                }
            )
        elif re.fullmatch(
            r"/voices/\w+/[\w-]+\.mp3", u.path
        ):  # готовые пробы голосов, без генерации
            self._file(ROOT / "web" / u.path.lstrip("/"), "audio/mpeg", "public, max-age=604800")
        elif u.path == "/api/balance":
            if self._limited("balance", 20):
                return
            try:
                d = json.loads(request(f"{API}/account/balance", timeout=20, tries=1))
                self._json(
                    {
                        "balance": d.get("accountBalance", {}).get(
                            "total", d.get("balance")
                        )
                    }
                )
            except Exception as e:
                self._json({"error": str(e)[:200]})
        elif u.path == "/api/jobs":
            self._json(
                [
                    {k: v for k, v in j.items() if k != "log"}
                    | {"log": j.get("log", [])[-6:]}
                    for j in all_jobs()
                ]
            )
        elif (
            len(parts) == 3
            and parts[0] == "files"
            and parts[2] in FILES
            and re.fullmatch(r"[\w-]+", parts[1])
        ):
            self._file(JOBS / parts[1] / parts[2], FILES[parts[2]])
        else:
            self.send_error(404)

    def _file(self, path: Path, ctype: str, cache: str = "private, no-cache"):
        """Отдаёт файл. ETag позволяет браузеру не скачивать повторно то, что не изменилось (304)."""
        if not path.is_file():
            return self.send_error(404)
        stat = path.stat()
        size = stat.st_size
        etag = f'"{stat.st_mtime_ns:x}-{size:x}"'
        if self.headers.get("If-None-Match") == etag and not self.headers.get("Range"):
            self.send_response(304)
            self.send_header("ETag", etag)
            self._cache_control = cache
            self.end_headers()
            return
        start, end = 0, size - 1
        partial = False
        rng = self.headers.get("Range", "")
        # Multiple ranges and unknown units may be ignored (full 200 response).
        if (
            rng.startswith("bytes=")
            and "," not in rng
            and not self.headers.get("If-Range")
        ):
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", rng)
            try:
                if not match or not any(match.groups()) or size == 0:
                    raise ValueError
                first, last = match.groups()
                if first:
                    start = int(first)
                    end = min(int(last), size - 1) if last else size - 1
                    if start >= size or end < start:
                        raise ValueError
                else:
                    suffix = int(last)
                    if suffix <= 0:
                        raise ValueError
                    start = max(0, size - suffix)
                partial = True
            except ValueError:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        self.send_response(206 if partial else 200)
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Type", ctype)
        self.send_header("ETag", etag)
        self._cache_control = cache
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if path.name in FILES and not ctype.startswith(("video", "image", "audio")):
            self.send_header(
                "Content-Disposition", f'attachment; filename="{path.name}"'
            )
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(1 << 20, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                left -= len(chunk)

    def do_POST(self):
        try:
            self._post()
        except InvalidRequest as error:
            self._json({"error": str(error)}, error.status)
        except QueueFull as error:
            self._json({"error": str(error)}, 429)
        except KeyError:
            self._json({"error": "Ролик не найден"}, 404)
        except socket.timeout:
            self.close_connection = True
            self._json({"error": "Время загрузки запроса истекло"}, 408)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            LOG.exception("POST failed")
            self._json({"error": "Временная ошибка сервера"}, 500)

    def _post(self):
        origin = self.headers.get("Origin")
        if self.headers.get("Sec-Fetch-Site") == "cross-site" or (
            origin and urlparse(origin).netloc != self.headers.get("Host")
        ):
            return self._json({"error": "Запрос с другого сайта запрещён"}, 403)
        if not self._auth():
            return
        m = re.fullmatch(r"/api/jobs/([\w-]+)/(retry|cancel)", self.path)
        if m:
            if self._limited("jobs", 10):
                return
            jid, action = m.groups()
            store = jobs_store()
            if action == "retry":
                return self._json(store.retry(jid, MAX_QUEUE))
            return self._json(store.cancel(jid))
        edit = re.fullmatch(
            r"/api/jobs/([\w-]+)/(script|render|remount|trash|restore)", self.path
        )
        if edit:
            if self._limited("editing", 30):
                return
            jid, action = edit.groups()
            data = self._read_json()
            directory = JOBS / jid

            def transform(job):
                if action in ("trash", "restore"):
                    return {"deleted_at": time.time() if action == "trash" else None}
                if action in ("script", "render"):
                    saved = editing.save_script(directory, data)
                    return {"title": saved["title"]}
                script = editing.load_script(directory)
                script["subtitles"] = subtitles.normalize(data.get("subtitles"))
                if data.get("srt"):
                    script["subtitle_cues"] = editing.parse_srt(data["srt"])
                else:
                    script.pop("subtitle_cues", None)
                from factory.files import atomic_json

                atomic_json(directory / "script.json", script)
                return {"subtitles": script["subtitles"]}

            return self._json(
                jobs_store().edit(
                    jid, transform, action if action in ("render", "remount") else None
                )
            )
        if self.path == "/api/subtitles/preview":
            if self._limited("preview", 180):
                return
            data = self._read_json(8192)
            try:
                if not HEAVY.acquire(blocking=False):
                    return self._json(
                        {"error": "Предпросмотр занят. Повторите через секунду"}, 429
                    )
                try:
                    image = subtitles.preview(
                        data.get("subtitles"),
                        data.get("format"),
                        int(data.get("page", 0)),
                        data.get("width"),
                    )
                    output = io.BytesIO()
                    image.save(output, format="PNG")
                finally:
                    HEAVY.release()
            except (TypeError, ValueError, AttributeError):
                return self._json({"error": "Неверные параметры предпросмотра"}, 400)
            raw = output.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        if self.path != "/api/jobs":
            return self.send_error(404)
        if self._limited("jobs", 10):
            return
        data = self._read_json()
        options = job_options(data)
        if not HEAVY.acquire(blocking=False):
            return self._json(
                {"error": "Сервер обрабатывает изображения. Повторите через секунду"},
                429,
            )
        try:
            ref = reference_image(data.get("reference"))
            scene_ref = reference_image(data.get("scene_reference"))
        finally:
            HEAVY.release()
        options["reference"] = ref is not None
        options["scene_reference"] = scene_ref is not None
        options["exact"] = data.get("exact") is True and ref is not None
        plan = cost.estimate(
            options["minutes"],
            options["animate"],
            options["exact"],
            options["voice_provider"],
            options["style"],
            options["video_model"],
            options["max_price"],
        )
        if plan["minimum"] > plan["budget"]:
            raise InvalidRequest(
                f"Бюджет слишком мал: без анимации нужно примерно ${plan['minimum']:.2f}"
            )
        request_id = self.headers.get("Idempotency-Key")
        if request_id and not re.fullmatch(r"[a-zA-Z0-9_-]{16,100}", request_id):
            raise InvalidRequest("Некорректный идентификатор запроса")
        store = jobs_store()
        identity = fingerprint(data)
        previous = store.find_request(request_id, identity) if request_id else None
        if previous:
            return self._json(previous)
        jid = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:12]
        directory = JOBS / jid
        directory.mkdir(parents=True, exist_ok=False)
        try:
            if ref is not None:
                atomic_bytes(directory / "reference.jpg", jpeg_bytes(ref, 90))
            if scene_ref is not None:
                atomic_bytes(directory / "scene-reference.jpg", jpeg_bytes(scene_ref, 90))
            job = {
                **options,
                "id": jid,
                "budget_version": 1,
                "status": "queued",
                "progress": "в очереди",
                "created": datetime.now().isoformat(timespec="seconds"),
                "estimate": plan,
            }
            saved = store.put(
                job, max_active=MAX_QUEUE, request_id=request_id, input_hash=identity
            )
        except QueueFull:
            shutil.rmtree(directory)
            raise
        if saved["id"] != jid:
            shutil.rmtree(directory)
        self._json(saved)


def serve() -> None:
    remote = HOST not in ("127.0.0.1", "::1", "localhost")
    if remote and not env("ACCESS_PASSWORD"):
        raise SystemExit("Для удалённого доступа задайте ACCESS_PASSWORD")
    cert, private_key = env("TLS_CERT"), env("TLS_KEY")
    if bool(cert) != bool(private_key):
        raise SystemExit("TLS_CERT и TLS_KEY должны быть заданы вместе")
    tls = None
    if cert:
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.minimum_version = ssl.TLSVersion.TLSv1_2
        tls.load_cert_chain(cert, private_key)
    elif remote and env("BEHIND_PROXY") != "1":
        raise SystemExit(
            "Для удалённого доступа нужен TLS_CERT/TLS_KEY или BEHIND_PROXY=1 за HTTPS-прокси"
        )
    httpd = BoundedHTTPServer((HOST, PORT), Handler)
    if tls:
        httpd.socket = tls.wrap_socket(httpd.socket, server_side=True)
    JOBS.mkdir(exist_ok=True)
    restore()
    stop = threading.Event()
    if env("START_WORKER") != "0":
        threading.Thread(target=supervise_worker, args=(stop,), daemon=True).start()
    print(f"Shorts Factory: {'https' if tls else 'http'}://{HOST}:{PORT}", flush=True)
    try:
        httpd.serve_forever()
    finally:
        stop.set()
        httpd.server_close()


if __name__ == "__main__":
    serve()
