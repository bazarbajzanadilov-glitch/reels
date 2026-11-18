"""Persistent job worker. The web process may restart without interrupting rendering."""

import argparse
import fcntl
import logging
import resource
import sys
import os
import signal
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from factory import budget, cost, pipeline
from factory.config import API, JOBS
from factory.http import request
import json
import math
from factory.execution import Cancelled, operation
from factory.store import JobStore
from factory.files import atomic_bytes

LOG = logging.getLogger("shorts.worker")


def reconcile(store, job):
    child = budget.credential(store.root / job["id"])
    if not child:
        store.patch(
            job["id"], accounting="unchanged" if job.get("cost") else "not-started"
        )
        return
    metadata = budget.record(store.root / job["id"])
    key_info = json.loads(
        request(f"{API}/account/key", api_key=child, tries=1, timeout=20)
    )
    remaining = key_info.get("pollenBudget")
    if isinstance(remaining, (float, int)) and math.isfinite(remaining):
        store.patch(
            job["id"],
            budget_status={
                "limit": metadata["cap"],
                "remaining": max(0, remaining),
                "state": "exhausted" if remaining <= 0 else "ready",
            },
        )
    actual = cost.actual(
        "1970-01-01 00:00:00", cost.now_utc(), wait=False, api_key=child
    )
    if actual is None:
        store.patch(job["id"], accounting="pending")
        return
    prior = float(metadata.get("prior_spent", 0))
    if prior:
        actual["parts"]["прежние попытки"] = prior
        actual["total"] = round(actual["total"] + prior, 3)
    latest = store.get(job["id"])
    if actual["total"] >= (latest.get("cost") or {}).get("total", 0):
        old_total = (latest.get("cost") or {}).get("total")
        settled = (
            old_total == actual["total"]
            and time.time() - float(latest.get("accounting_started", time.time()))
            >= 120
        )
        store.patch(
            job["id"], cost=actual, accounting="confirmed" if settled else "pending"
        )


def process(store, job):
    measured = time.monotonic()
    usage = resource.getrusage(resource.RUSAGE_SELF)
    jid = job["id"]
    cancel = store.root / jid / ".cancelled"
    run_id = uuid.uuid4().hex
    atomic_bytes(store.root / jid / ".run-id", run_id.encode())
    store.patch(jid, run_id=run_id)

    def log(message):
        store.progress(jid, message)

    try:
        with operation(
            run_id=run_id,
            cancel_path=cancel,
            audit=lambda event: store.audit(jid, {**event, "run_id": run_id}),
        ):
            if job.get("task") == "remount":
                result = pipeline.remount(
                    store.root / jid, job["format"], job["animate"], log
                )
            else:
                result = pipeline.run(
                    job["topic"],
                    job["format"],
                    job["minutes"],
                    job["animate"],
                    store.root / jid,
                    log,
                    **{
                        name: job.get(name, default)
                        for name, default in [
                            ("exact", False),
                            ("lang", "ru"),
                            ("voice_provider", "gemini"),
                            ("voice", None),
                            ("style", "2d"),
                            ("genre", "auto"),
                            ("tone", "auto"),
                            ("narrator", "auto"),
                            ("ending", "auto"),
                            ("audience", "all"),
                            ("notes", ""),
                            ("custom_style", ""),
                            ("custom_genre", ""),
                            ("video_model", "wan"),
                            ("max_price", None),
                            ("subtitles", None),
                        ]
                    },
                    script_only=job.get("review", False)
                    and job.get("task") != "render",
                    prior_spent=(job.get("cost") or {}).get("total", 0),
                )
        if cancel.exists():
            raise Cancelled("Создание остановлено")
        store.patch(
            jid,
            status="draft" if result.get("draft") else "done",
            title=result["title"],
            files=result["files"],
            progress="готово",
        )
    except Cancelled:
        store.patch(jid, status="cancelled", progress="остановлено")
    except Exception as error:
        LOG.exception("Job %s failed", jid)
        store.patch(jid, status="error", progress=f"Ошибка: {error}")
    finally:
        store.patch(
            jid,
            finished=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            accounting="pending",
            accounting_started=time.time(),
            metrics={
                "seconds": round(time.monotonic() - measured, 2),
                "cpu_seconds": round(
                    resource.getrusage(resource.RUSAGE_SELF).ru_utime - usage.ru_utime,
                    2,
                ),
                "peak_memory_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                * (1 if sys.platform == "darwin" else 1024),
            },
        )
        try:
            reconcile(store, store.get(jid))
        except Exception:
            LOG.exception("Accounting refresh deferred for %s", jid)


def run(root: Path, stop=None):
    root.mkdir(parents=True, exist_ok=True)
    stop = stop or threading.Event()
    with (root / ".worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        store = JobStore(root)
        store.recover()
        owner = f"{os.getpid()}:{uuid.uuid4().hex}"

        def heartbeat():
            while not stop.is_set():
                try:
                    store.heartbeat(owner)
                except Exception:
                    LOG.exception("Worker heartbeat failed")
                stop.wait(2)
            for active in store.list():
                if active["status"] in ("running", "cancelling"):
                    try:
                        store.cancel(active["id"])
                    except Exception:
                        LOG.exception("Could not mark shutdown cancellation")

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        last_accounting = 0
        try:
            while not stop.is_set():
                try:
                    job = store.claim(owner)
                    if job:
                        process(store, job)
                    elif time.monotonic() - last_accounting > 30:
                        for item in store.list():
                            if item.get("accounting") == "pending":
                                try:
                                    reconcile(store, item)
                                except Exception:
                                    LOG.exception("Accounting postponed")
                        last_accounting = time.monotonic()
                    else:
                        stop.wait(0.5)
                except Exception:
                    LOG.exception("Queue iteration failed; worker remains alive")
                    stop.wait(1)
        finally:
            stop.set()
            thread.join(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=Path, default=JOBS)
    args = parser.parse_args()
    shutdown = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: shutdown.set())
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    run(args.jobs, shutdown)
