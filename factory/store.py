"""Transactional persistent queue and request journal. job.json remains a portable mirror."""

import json
import io
import zipfile
import logging
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from .files import atomic_json, atomic_bytes, path_lock

LOG = logging.getLogger(__name__)
ACTIVE = ("queued", "running", "cancelling")


class QueueFull(ValueError):
    pass


class JobStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        with path_lock(self.root / ".database-schema"):
            self.path = self.root / ".factory.sqlite3"
            with self.connection() as db:
                db.executescript("""
                    PRAGMA journal_mode=WAL;
                    CREATE TABLE IF NOT EXISTS jobs (
                        id TEXT PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL, created TEXT NOT NULL,
                        owner TEXT, heartbeat REAL, updated REAL NOT NULL);
                    CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(status, created);
                    CREATE TABLE IF NOT EXISTS requests (
                        id INTEGER PRIMARY KEY, job_id TEXT NOT NULL, kind TEXT NOT NULL, model TEXT,
                        started REAL NOT NULL, finished REAL, state TEXT NOT NULL, status INTEGER, bytes INTEGER, run_id TEXT);
                    CREATE INDEX IF NOT EXISTS requests_job ON requests(job_id, id);
                    CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS dedup (request_id TEXT PRIMARY KEY,job_id TEXT NOT NULL,input_hash TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS import_errors (path TEXT PRIMARY KEY, error TEXT NOT NULL);
                """)
                if "run_id" not in {
                    r["name"] for r in db.execute("PRAGMA table_info(requests)")
                }:
                    db.execute("ALTER TABLE requests ADD COLUMN run_id TEXT")
            for file in self.root.glob(".factory.sqlite3*"):
                file.chmod(0o600)
            self.import_legacy()

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        try:
            with db:
                yield db
        finally:
            db.close()

    def import_legacy(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT value FROM metadata WHERE name='legacy_import'"
            ).fetchone():
                return
            legacy = list(self.root.glob("*/job.json"))
            backup = self.root / ".legacy-json.zip"
            if legacy and not backup.exists():
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                    for path in legacy:
                        archive.write(path, str(path.relative_to(self.root)))
                atomic_bytes(backup, buffer.getvalue())
            for path in legacy:
                try:
                    job = json.loads(path.read_text(encoding="utf-8"))
                    if job["id"] != path.parent.name or job.get("status") not in (
                        *ACTIVE,
                        "done",
                        "error",
                        "cancelled",
                        "draft",
                    ):
                        raise ValueError("invalid job metadata")
                    db.execute(
                        "INSERT OR IGNORE INTO jobs(id,payload,status,created,updated) VALUES(?,?,?,?,?)",
                        (
                            job["id"],
                            json.dumps(job, ensure_ascii=False),
                            job["status"],
                            job["created"],
                            time.time(),
                        ),
                    )
                except (ValueError, KeyError, OSError) as error:
                    db.execute(
                        "INSERT OR REPLACE INTO import_errors VALUES(?,?)",
                        (str(path.relative_to(self.root)), type(error).__name__),
                    )
            db.execute("INSERT OR REPLACE INTO metadata VALUES('legacy_import','1')")

    def _mirror(self, job):
        try:
            with path_lock(self.root / job["id"] / ".mirror"):
                atomic_json(self.root / job["id"] / "job.json", self.get(job["id"]))
        except OSError:
            LOG.exception("Could not mirror job %s", job["id"])

    def get(self, jid):
        with self.connection() as db:
            row = db.execute("SELECT payload FROM jobs WHERE id=?", (jid,)).fetchone()
        if row is None:
            raise KeyError(jid)
        return json.loads(row["payload"])

    def list(self):
        with self.connection() as db:
            rows = db.execute(
                "SELECT payload FROM jobs ORDER BY created DESC,id DESC"
            ).fetchall()
        result = []
        for row in rows:
            try:
                result.append(json.loads(row["payload"]))
            except (ValueError, TypeError):
                LOG.error("Corrupt job payload skipped")
        return result

    def put(self, job, max_active=None, request_id=None, input_hash=None):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if request_id:
                previous = db.execute(
                    "SELECT job_id,input_hash FROM dedup WHERE request_id=?",
                    (request_id,),
                ).fetchone()
                if previous:
                    if previous["input_hash"] != input_hash:
                        raise QueueFull(
                            "Этот идентификатор уже использован для других настроек"
                        )
                    return json.loads(
                        db.execute(
                            "SELECT payload FROM jobs WHERE id=?", (previous["job_id"],)
                        ).fetchone()[0]
                    )
            old = db.execute(
                "SELECT payload FROM jobs WHERE id=?", (job["id"],)
            ).fetchone()
            if old:
                previous = json.loads(old["payload"])
                if (previous.get("cost") or {}).get("total", 0) > (
                    job.get("cost") or {}
                ).get("total", 0):
                    job["cost"] = previous["cost"]
            elif max_active is not None:
                count = db.execute(
                    "SELECT count(*) FROM jobs WHERE status IN ('queued','running','cancelling')"
                ).fetchone()[0]
                if count >= max_active:
                    raise QueueFull(
                        "Очередь заполнена. Дождитесь завершения текущих роликов"
                    )
            db.execute(
                """INSERT INTO jobs(id,payload,status,created,updated) VALUES(?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,status=excluded.status,updated=excluded.updated""",
                (
                    job["id"],
                    json.dumps(job, ensure_ascii=False, allow_nan=False),
                    job["status"],
                    job["created"],
                    time.time(),
                ),
            )
            if request_id:
                db.execute(
                    "INSERT INTO dedup VALUES(?,?,?)",
                    (request_id, job["id"], input_hash),
                )
        self._mirror(job)
        return job

    def patch(self, jid, **changes):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM jobs WHERE id=?", (jid,)).fetchone()
            if row is None:
                raise KeyError(jid)
            job = json.loads(row["payload"])
            if changes.get("status") == "done" and job["status"] == "cancelling":
                changes = {**changes, "status": "cancelled", "progress": "остановлено"}
            job.update(changes)
            db.execute(
                "UPDATE jobs SET payload=?,status=?,updated=? WHERE id=?",
                (
                    json.dumps(job, ensure_ascii=False, allow_nan=False),
                    job["status"],
                    time.time(),
                    jid,
                ),
            )
        self._mirror(job)
        return job

    def progress(self, jid, message):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM jobs WHERE id=?", (jid,)).fetchone()
            if row is None:
                return
            job = json.loads(row["payload"])
            job["progress"] = str(message)[:1000]
            job["log"] = [*job.get("log", []), str(message)[:1000]][-200:]
            db.execute(
                "UPDATE jobs SET payload=?,updated=? WHERE id=?",
                (json.dumps(job, ensure_ascii=False), time.time(), jid),
            )
        self._mirror(job)

    def claim(self, owner):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT id,payload FROM jobs WHERE status='queued' ORDER BY created,id"
            ).fetchall()
            for row in rows:
                try:
                    job = json.loads(row["payload"])
                    if (
                        not isinstance(job.get("topic"), str)
                        or not job["topic"].strip()
                    ):
                        raise ValueError("invalid topic")
                except (ValueError, TypeError):
                    broken = {
                        "id": row["id"],
                        "topic": "Повреждённая запись",
                        "status": "error",
                        "created": "",
                        "progress": "Повреждены данные задачи; остальные ролики продолжают обрабатываться",
                    }
                    db.execute(
                        "UPDATE jobs SET status='error',payload=? WHERE id=?",
                        (json.dumps(broken, ensure_ascii=False), row["id"]),
                    )
                    continue
                job.update(
                    status="running",
                    progress="старт",
                    started=time.strftime("%Y-%m-%dT%H:%M:%S"),
                )
                db.execute(
                    "UPDATE jobs SET status=?,payload=?,owner=?,heartbeat=?,updated=? WHERE id=?",
                    (
                        "running",
                        json.dumps(job, ensure_ascii=False),
                        owner,
                        time.time(),
                        time.time(),
                        job["id"],
                    ),
                )
                break
            else:
                return None
        self._mirror(job)
        return job

    def retry(self, jid, max_active=20):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM jobs WHERE id=?", (jid,)).fetchone()
            if row is None:
                raise KeyError(jid)
            job = json.loads(row["payload"])
            if job["status"] not in ("error", "cancelled"):
                return job
            count = db.execute(
                "SELECT count(*) FROM jobs WHERE status IN ('queued','running','cancelling')"
            ).fetchone()[0]
            if count >= max_active:
                raise QueueFull("Очередь заполнена")
            (self.root / jid / ".cancelled").unlink(missing_ok=True)
            job.update(status="queued", progress="в очереди (повтор)")
            db.execute(
                "UPDATE jobs SET payload=?,status=?,owner=NULL,updated=? WHERE id=?",
                (json.dumps(job, ensure_ascii=False), "queued", time.time(), jid),
            )
        self._mirror(job)
        return job

    def recover(self):
        # Called only by the process holding the exclusive worker lock.
        with self.connection() as db:
            rows = db.execute(
                "SELECT id,payload FROM jobs WHERE status IN ('running','cancelling')"
            ).fetchall()
        for row in rows:
            try:
                job = json.loads(row["payload"])
                atomic_bytes(
                    self.root / job["id"] / ".run-id", uuid.uuid4().hex.encode()
                )
                if job["status"] == "cancelling":
                    self.patch(job["id"], status="cancelled", progress="остановлено")
                else:
                    summary = self.request_summary(job["id"], job.get("run_id"))
                    if summary.get("started") or summary.get("uncertain"):
                        self.patch(
                            job["id"],
                            status="error",
                            progress="Прерван запрос к провайдеру: проверьте расходы перед повтором",
                        )
                    else:
                        self.patch(
                            job["id"],
                            status="queued",
                            progress="восстановление после перезапуска",
                        )
            except (ValueError, KeyError):
                with self.connection() as db:
                    db.execute(
                        "UPDATE jobs SET status='error' WHERE id=?", (row["id"],)
                    )

    def heartbeat(self, owner):
        with self.connection() as db:
            db.execute(
                "UPDATE jobs SET heartbeat=? WHERE owner=? AND status IN ('running','cancelling')",
                (time.time(), owner),
            )
            db.execute(
                "INSERT OR REPLACE INTO metadata VALUES('worker_heartbeat',?)",
                (str(time.time()),),
            )
            db.execute(
                "INSERT OR REPLACE INTO metadata VALUES('worker_owner',?)", (owner,)
            )

    def audit(self, jid, event):
        with self.connection() as db:
            if event["state"] == "started":
                cursor = db.execute(
                    "INSERT INTO requests(job_id,kind,model,started,state,run_id) VALUES(?,?,?,?,?,?)",
                    (
                        jid,
                        event["kind"],
                        event.get("model"),
                        time.time(),
                        "started",
                        event.get("run_id"),
                    ),
                )
                return cursor.lastrowid
            db.execute(
                "UPDATE requests SET finished=?,state=?,status=?,bytes=? WHERE id=? AND job_id=?",
                (
                    time.time(),
                    event["state"],
                    event.get("status"),
                    event.get("bytes"),
                    event["id"],
                    jid,
                ),
            )

    def request_summary(self, jid, run_id=None):
        with self.connection() as db:
            if run_id:
                rows = db.execute(
                    "SELECT state,count(*) AS n FROM requests WHERE job_id=? AND run_id=? GROUP BY state",
                    (jid, run_id),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT state,count(*) AS n FROM requests WHERE job_id=? GROUP BY state",
                    (jid,),
                ).fetchall()
        return {r["state"]: r["n"] for r in rows}

    def healthy(self):
        with self.connection() as db:
            row = db.execute(
                "SELECT value FROM metadata WHERE name='worker_heartbeat'"
            ).fetchone()
        return bool(row and time.time() - float(row["value"]) < 15)

    def find_request(self, request_id, input_hash):
        with self.connection() as db:
            row = db.execute(
                "SELECT job_id,input_hash FROM dedup WHERE request_id=?", (request_id,)
            ).fetchone()
        if not row:
            return None
        if row["input_hash"] != input_hash:
            raise QueueFull("Идентификатор запроса связан с другими настройками")
        return self.get(row["job_id"])

    def cancel(self, jid):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM jobs WHERE id=?", (jid,)).fetchone()
            if row is None:
                raise KeyError(jid)
            job = json.loads(row["payload"])
            if job["status"] not in ACTIVE:
                return job
            atomic_json(self.root / jid / ".cancelled", {"requested": time.time()})
            job.update(
                status="cancelled" if job["status"] == "queued" else "cancelling",
                progress="остановка",
            )
            db.execute(
                "UPDATE jobs SET payload=?,status=?,updated=? WHERE id=?",
                (json.dumps(job, ensure_ascii=False), job["status"], time.time(), jid),
            )
        self._mirror(job)
        return job

    def edit(self, jid, transform, task=None, max_active=20):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM jobs WHERE id=?", (jid,)).fetchone()
            if row is None:
                raise KeyError(jid)
            job = json.loads(row["payload"])
            if job["status"] in ACTIVE:
                raise QueueFull("Дождитесь завершения текущего этапа")
            if task:
                count = db.execute(
                    "SELECT count(*) FROM jobs WHERE status IN ('queued','running','cancelling')"
                ).fetchone()[0]
                if count >= max_active:
                    raise QueueFull("Очередь заполнена")
            changes = transform(job) or {}
            job.update(changes)
            if task:
                (self.root / jid / ".cancelled").unlink(missing_ok=True)
                job.update(task=task, status="queued", progress="в очереди")
            db.execute(
                "UPDATE jobs SET payload=?,status=?,updated=? WHERE id=?",
                (json.dumps(job, ensure_ascii=False), job["status"], time.time(), jid),
            )
        self._mirror(job)
        return job

    def revision(self):
        with self.connection() as db:
            return db.execute("SELECT coalesce(max(updated),0) FROM jobs").fetchone()[0]
