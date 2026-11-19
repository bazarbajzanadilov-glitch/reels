import io
import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor as PlainPool
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import server
import worker
from factory import budget, http, images
from factory.execution import ThreadPoolExecutor, operation, Cancelled, UncertainRequest
from factory.files import valid_image
from factory.store import JobStore, QueueFull
from factory.validation import (
    job_options,
    estimate_options,
    InvalidRequest,
    reference_image,
)


def job(jid="one"):
    return {
        "id": jid,
        "topic": "Тест",
        "format": "vertical",
        "minutes": 1,
        "animate": "none",
        "created": f"2026-11-18T00:00:{jid}",
        "status": "queued",
        "budget_version": 1,
    }


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = JobStore(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def test_parallel_claims_never_start_the_same_job_twice(self):
        self.store.put(job())
        with PlainPool(8) as pool:
            results = list(pool.map(lambda i: self.store.claim(str(i)), range(8)))
        self.assertEqual(sum(value is not None for value in results), 1)

    def test_state_survives_new_store_instance(self):
        self.store.put(job())
        self.assertEqual(JobStore(self.root).get("one")["status"], "queued")

    def test_duplicate_submission_creates_one_job(self):
        def create(i):
            return self.store.put(
                job(str(i)),
                max_active=20,
                request_id="same-request",
                input_hash="settings",
            )

        with PlainPool(6) as pool:
            results = list(pool.map(create, range(6)))
        self.assertEqual(len({j["id"] for j in results}), 1)
        self.assertEqual(len(self.store.list()), 1)

    def test_queue_limit_is_transactional(self):
        self.store.put(job("one"), max_active=1)
        with self.assertRaises(QueueFull):
            self.store.put(job("two"), max_active=1)
        self.assertEqual(len(self.store.list()), 1)

    def test_corrupt_entry_does_not_block_next_job(self):
        self.store.put(job("broken"))
        self.store.put(job("good"))
        with self.store.connection() as db:
            db.execute("UPDATE jobs SET payload='{' WHERE id='broken'")
        self.assertEqual(self.store.claim("worker")["id"], "good")
        self.assertEqual(self.store.get("broken")["status"], "error")

    def test_cost_is_not_overwritten_by_progress(self):
        self.store.put(job())
        self.store.patch("one", cost={"total": 0.2, "parts": {}})
        self.store.progress("one", "монтаж")
        self.assertEqual(self.store.get("one")["cost"]["total"], 0.2)

    def test_safe_interruption_resumes_but_uncertain_payment_stops(self):
        self.store.put(job("safe"))
        self.store.claim("old")
        self.store.put(job("uncertain"))
        self.store.claim("old")
        self.store.audit("uncertain", {"state": "started", "kind": "image"})
        self.store.recover()
        self.assertEqual(self.store.get("safe")["status"], "queued")
        self.assertEqual(self.store.get("uncertain")["status"], "error")

    def test_cancel_and_retry_keep_original_budget(self):
        self.store.put(
            {**job(), "cost": {"total": 0.12, "parts": {}}, "max_price": 0.28}
        )
        self.store.claim("worker")
        self.assertEqual(self.store.cancel("one")["status"], "cancelling")
        self.assertTrue((self.root / "one" / ".cancelled").exists())
        self.store.patch("one", status="done")
        self.assertEqual(self.store.get("one")["status"], "cancelled")
        retried = self.store.retry("one")
        self.assertEqual(retried["max_price"], 0.28)
        self.assertEqual(retried["cost"]["total"], 0.12)
        self.assertFalse((self.root / "one" / ".cancelled").exists())

    def test_legacy_import_preserves_good_files_and_reports_bad(self):
        second = self.root / "legacy"
        (second / "old").mkdir(parents=True)
        (second / "old" / "job.json").write_text(json.dumps(job("old")))
        (second / "bad").mkdir()
        (second / "bad" / "job.json").write_text("{")
        imported = JobStore(second)
        self.assertEqual(imported.get("old")["topic"], "Тест")
        self.assertEqual((second / "bad" / "job.json").read_text(), "{")
        with imported.connection() as db:
            self.assertEqual(
                db.execute("SELECT count(*) FROM import_errors").fetchone()[0], 1
            )

    def test_worker_error_does_not_prevent_next_job(self):
        for jid in ("a", "b"):
            self.store.put(job(jid))

        def run(*args, **kwargs):
            if args[4].name == "a":
                raise RuntimeError("test failure")
            return {"title": "Готово", "files": ["video.mp4"]}

        with (
            patch("worker.pipeline.run", side_effect=run),
            patch("worker.reconcile"),
            self.assertLogs("shorts.worker", level="ERROR"),
        ):
            worker.process(self.store, self.store.claim("test"))
            worker.process(self.store, self.store.claim("test"))
        self.assertEqual(self.store.get("a")["status"], "error")
        self.assertEqual(self.store.get("b")["status"], "done")


class ContextTests(unittest.TestCase):
    def test_overlapping_jobs_and_late_threads_keep_their_own_keys(self):
        seen = []
        gate = threading.Barrier(2)

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self):
                return b"{}"

        def opening(req, **kwargs):
            seen.append(req.get_header("Authorization"))
            return Response()

        def execute(token):
            with http.generation_key(token):
                with ThreadPoolExecutor(1) as children:

                    def late():
                        gate.wait(timeout=3)
                        return http.request("https://gen.pollinations.ai/image/test")

                    return children.submit(late).result()

        with patch("factory.http._open", side_effect=opening):
            with PlainPool(2) as outer:
                list(outer.map(execute, ["job-a", "job-b"]))
        self.assertCountEqual(seen, ["Bearer job-a", "Bearer job-b"])

    def test_cancelled_context_never_sends_request(self):
        with tempfile.TemporaryDirectory() as directory:
            cancel = Path(directory) / "cancel"
            cancel.touch()
            with (
                operation(token="test-key", cancel_path=cancel),
                patch("factory.http._open") as transport,
            ):
                with self.assertRaises(Cancelled):
                    http.request("https://gen.pollinations.ai/image/a")
                transport.assert_not_called()

    def test_paid_timeout_is_journaled_and_not_retried(self):
        events = []

        def audit(event):
            events.append(event)
            return 1

        with (
            operation(token="test-key", audit=audit),
            patch("factory.http._open", side_effect=TimeoutError) as opening,
        ):
            with self.assertRaises(UncertainRequest):
                http.request("https://gen.pollinations.ai/image/a", tries=5)
        self.assertEqual(opening.call_count, 1)
        self.assertEqual([e["state"] for e in events], ["started", "uncertain"])
        self.assertNotIn("test-key", json.dumps(events))

    def test_redirect_does_not_forward_authorization(self):
        request = __import__("urllib.request", fromlist=["Request"]).Request(
            "https://gen.pollinations.ai/image/a",
            headers={"Authorization": "Bearer test"},
        )
        redirected = http.SafeRedirect().redirect_request(
            request, None, 302, "", {}, "https://cdn.example/result.jpg"
        )
        self.assertIsNone(redirected.get_header("Authorization"))


class ValidationTests(unittest.TestCase):
    def test_nonfinite_and_malformed_settings_rejected(self):
        for value in [float("nan"), float("inf"), [], {}, True, -1, 99]:
            with self.subTest(value=value), self.assertRaises(InvalidRequest):
                job_options({"topic": "test", "minutes": value})
        with self.assertRaises(InvalidRequest):
            estimate_options({"minutes": ["nan"]})
        with self.assertRaises(InvalidRequest):
            job_options({"topic": ["not", "text"]})
        with self.assertRaises(InvalidRequest):
            job_options({"topic": "test", "voice_provider": []})

    def test_reference_image_dimensions_are_bounded(self):
        with patch("factory.validation.Image.open") as opening:
            opening.return_value.__enter__.return_value.width = 5000
            opening.return_value.__enter__.return_value.height = 5000
            with self.assertRaises(InvalidRequest):
                reference_image("data:image/png;base64,YQ==")

    def test_cache_corruption_is_replaced_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            buffer = io.BytesIO()
            Image.new("RGB", (16, 16), "red").save(buffer, "PNG")
            with (
                patch("factory.images.CACHE", Path(directory)),
                patch(
                    "factory.images.request", return_value=buffer.getvalue()
                ) as provider,
            ):
                path = images.fetch("test", "test", "test", 1, (16, 16))
                path.write_bytes(b"corrupt")
                repaired = images.fetch("test", "test", "test", 1, (16, 16))
                self.assertTrue(valid_image(repaired))
                images.fetch("test", "test", "test", 1, (16, 16))
                self.assertEqual(provider.call_count, 2)


class RequestLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()

    def test_large_body_and_invalid_json_fail_before_processing(self):
        for length, body, status in [
            (server.MAX_BODY + 1, b"", 413),
            (4, b"null", 400),
            (-1, b"", 413),
        ]:
            client = HTTPConnection(*self.httpd.server_address, timeout=3)
            try:
                with (
                    patch("server.env", return_value=None),
                    patch("server.reference_image") as parser,
                ):
                    client.request(
                        "POST",
                        "/api/jobs",
                        body=body,
                        headers={"Content-Length": str(length)},
                    )
                    response = client.getresponse()
                    response.read()
                self.assertEqual(response.status, status)
                parser.assert_not_called()
            finally:
                client.close()

    def test_bad_price_query_returns_json_400(self):
        client = HTTPConnection(*self.httpd.server_address, timeout=3)
        try:
            with patch("server.env", return_value=None):
                client.request("GET", "/api/estimate?minutes=nan")
                response = client.getresponse()
                body = json.loads(response.read())
            self.assertEqual(response.status, 400)
            self.assertIn("error", body)
        finally:
            client.close()


class RecoveryTests(unittest.TestCase):
    def test_worker_lock_prevents_two_consumers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stop = threading.Event()
            thread = threading.Thread(target=worker.run, args=(root, stop), daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 5
                store = JobStore(root)
                while not store.healthy() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(store.healthy())
                second = threading.Thread(
                    target=worker.run, args=(root, threading.Event()), daemon=True
                )
                second.start()
                second.join(1)
                self.assertFalse(second.is_alive())
                self.assertTrue(thread.is_alive())
            finally:
                stop.set()
                thread.join(5)
            self.assertFalse(thread.is_alive())

    def test_unused_key_is_reconciled_before_a_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "job"
            names = []
            calls = []

            def provider(url, data=None, *args, **kwargs):
                calls.append((url, kwargs.get("method")))
                if kwargs.get("method") == "DELETE":
                    return b"{}"
                if url.endswith("/account/key"):
                    return b'{"permissions":{"account":["keys"]}}'
                if url.endswith("/account/keys") and data is None:
                    return json.dumps(
                        {
                            "data": [
                                {"name": names[0], "id": "unused-id", "enabled": True}
                            ]
                        }
                    ).encode()
                payload = json.loads(data)
                names.append(payload["name"])
                if len(names) == 1:
                    raise TimeoutError("lost response")
                return json.dumps(
                    {
                        "id": "new-id",
                        "key": "test-child",
                        "pollenBudget": payload["pollenBudget"],
                    }
                ).encode()

            with patch("factory.budget.request", side_effect=provider):
                with self.assertRaises(RuntimeError):
                    budget.provision(root, 0.28)
                self.assertEqual(budget.provision(root, 0.28), "test-child")
            deletion = next(
                i for i, (_, method) in enumerate(calls) if method == "DELETE"
            )
            self.assertLess(deletion, len(calls) - 1)
            self.assertEqual(budget.record(root)["allocated"], 0.28)
            self.assertNotEqual(names[0], names[1])

    def test_old_budget_secret_moves_out_of_download_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "job"
            root.mkdir()
            old = root / budget.SECRET_FILE
            old.write_text(
                json.dumps({"key": "test-only", "cap": 0.28, "allocated": 0.28})
            )
            self.assertEqual(budget.credential(root), "test-only")
            self.assertFalse(old.exists())
            self.assertTrue(budget.secret_path(root).exists())
            self.assertNotEqual(budget.secret_path(root).parent, root)

    def test_completed_render_chunk_is_reused_and_replaced_run_stops(self):
        from factory import render

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "image.jpg"
            Image.new("RGB", (120, 200), "blue").save(image)
            run_file = root / ".run-id"
            run_file.write_text("first")
            scene = {
                "start": 0,
                "dur": 1,
                "image": str(image),
                "camera": "none",
                "danger": False,
                "caption": "",
                "cancel_path": str(root / ".cancelled"),
                "run_id": "first",
            }
            out = root / "chunk.mp4"
            render.render_chunk([scene], 0, 5, 1, (120, 200), 5, str(out))
            scene["run_id"] = "second"
            run_file.write_text("second")
            with patch(
                "factory.render._render_chunk",
                side_effect=AssertionError("Already rendered"),
            ):
                render.render_chunk([scene], 0, 5, 1, (120, 200), 5, str(out))
            scene["run_id"] = "old"
            with self.assertRaises(Cancelled):
                render._render_chunk(
                    [scene], 0, 5, 1, (120, 200), 5, str(root / "cancel.mp4"), 1
                )

    def test_late_cost_progress_from_previous_attempt_does_not_leak_status(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory))
            store.put(job())
            store.patch("one", run_id="new", status="running")
            store.audit(
                "one", {"state": "started", "kind": "image", "run_id": "old"}
            )
            self.assertEqual(store.request_summary("one", "new"), {})
            self.assertEqual(store.request_summary("one", "old")["started"], 1)
