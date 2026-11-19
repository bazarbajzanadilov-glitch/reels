import json
import stat
import tempfile
import threading
import unittest
from factory.execution import ThreadPoolExecutor
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import server
from factory import budget, http


class FileHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.path = Path(cls.directory.name) / "video.mp4"
        cls.path.write_bytes(b"0123456789")
        path = cls.path

        class Handler(server.Handler):
            def do_GET(self):
                self._file(path, "video/mp4")

        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()
        cls.directory.cleanup()

    def get(self, headers=None, method="GET"):
        client = HTTPConnection(*self.httpd.server_address, timeout=5)
        try:
            client.request(method, "/", headers=headers or {})
            response = client.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            client.close()

    def test_ranges(self):
        for value, body, content_range in [
            ("bytes=0-1", b"01", "bytes 0-1/10"),
            ("bytes=8-", b"89", "bytes 8-9/10"),
            ("bytes=-3", b"789", "bytes 7-9/10"),
            ("bytes=-100", b"0123456789", "bytes 0-9/10"),
            ("bytes=8-100", b"89", "bytes 8-9/10"),
        ]:
            with self.subTest(value=value):
                status, headers, actual = self.get({"Range": value})
                self.assertEqual(status, 206)
                self.assertEqual(actual, body)
                self.assertEqual(headers["Content-Range"], content_range)
                self.assertEqual(int(headers["Content-Length"]), len(body))

    def test_invalid_ranges(self):
        for value in (
            "bytes=-",
            "bytes=-0",
            "bytes=11-",
            "bytes=7-3",
            "bytes=a-b",
            "bytes=1--2",
        ):
            with self.subTest(value=value):
                status, headers, body = self.get({"Range": value})
                self.assertEqual(status, 416)
                self.assertEqual(headers["Content-Range"], "bytes */10")
                self.assertEqual(body, b"")

    def test_ignored_ranges(self):
        for headers in (
            {"Range": "items=0-1"},
            {"Range": "bytes=0-1,5-6"},
            {"Range": "bytes=0-1", "If-Range": "old-etag"},
        ):
            self.assertEqual(self.get(headers)[::2], (200, b"0123456789"))

    def test_head(self):
        status, headers, body = self.get({"Range": "bytes=-3"}, method="HEAD")
        self.assertEqual((status, headers["Content-Length"], body), (206, "3", b""))

    def test_empty_file(self):
        self.path.write_bytes(b"")
        try:
            self.assertEqual(self.get()[::2], (200, b""))
            self.assertEqual(self.get({"Range": "bytes=0-"})[0], 416)
        finally:
            self.path.write_bytes(b"0123456789")


class AccessTests(unittest.TestCase):
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

    def request(self, method="GET", headers=None, path="/"):
        client = HTTPConnection(*self.httpd.server_address, timeout=5)
        try:
            client.request(method, path, headers=headers or {})
            response = client.getresponse()
            body = response.read()
            return response.status, body
        finally:
            client.close()

    def test_assets_work_without_auth_on_loopback(self):
        with patch("server.env", return_value=None):
            for path in ("/", "/css/app.css", "/js/app.js"):
                self.assertEqual(self.request(path=path)[0], 200)
            for path in ("/css/../server.py", "/js/missing.js", "/img/x.png"):
                self.assertEqual(self.request(path=path)[0], 404)

    def test_dns_rebinding_blocked(self):
        with patch("server.env", return_value=None):
            self.assertEqual(self.request(headers={"Host": "attacker.example"})[0], 403)

    def test_cross_site_generation_blocked(self):
        self.assertEqual(
            self.request("POST", {"Origin": "https://attacker.example"}, "/api/jobs")[
                0
            ],
            403,
        )

    def test_password(self):
        import base64

        basic = lambda pair: {"Authorization": "Basic " + base64.b64encode(pair).decode()}
        settings = {"ACCESS_PASSWORD": "test-only-password"}
        with patch("server.env", side_effect=settings.get):
            self.assertEqual(self.request()[0], 401)
            self.assertEqual(self.request(headers=basic(b"user:test-only-password"))[0], 200)
            settings["ACCESS_LOGIN"] = "1"  # с заданным логином чужой логин не проходит
            self.assertEqual(self.request(headers=basic(b"user:test-only-password"))[0], 401)
            self.assertEqual(self.request(headers=basic(b"1:test-only-password"))[0], 200)

    def test_remote_binding_fails_before_workers(self):
        with (
            patch("server.HOST", "0.0.0.0"),
            patch("server.env", return_value=None),
            patch("server.restore") as restore,
        ):
            with self.assertRaises(SystemExit):
                server.serve()
            restore.assert_not_called()


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "job"
        self.calls = []

    def tearDown(self):
        self.directory.cleanup()

    def provider(self, url, data=None, *args, **kwargs):
        self.calls.append((url, data))
        if url.endswith("/account/key") and kwargs.get("api_key"):
            return b'{"valid":true,"pollenBudget":0.24}'
        if url.endswith("/account/key"):
            return b'{"permissions":{"account":["keys"]}}'
        payload = json.loads(data)
        return json.dumps(
            {
                "key": "test-child-secret",
                "id": "test-id",
                "pollenBudget": payload["pollenBudget"],
            }
        ).encode()

    def test_retry_keeps_original_budget_and_private_secret(self):
        with patch("factory.budget.request", side_effect=self.provider):
            key = budget.provision(self.path, 0.28, 0.04)
            self.assertEqual(budget.provision(self.path, 0.28, 0.17), key)
        self.assertEqual(len(self.calls), 3)
        self.assertAlmostEqual(json.loads(self.calls[1][1])["pollenBudget"], 0.24)
        self.assertEqual(
            stat.S_IMODE(budget.secret_path(self.path).stat().st_mode), 0o600
        )

    def test_ambiguous_creation_never_allocates_twice(self):
        def fail(url, data=None, *args, **kwargs):
            if data is None:
                return b'{"permissions":{"account":["keys"]}}'
            raise TimeoutError

        with patch("factory.budget.request", side_effect=fail) as provider:
            with self.assertRaises(RuntimeError):
                budget.provision(self.path, 0.28)
            with self.assertRaises(RuntimeError):
                budget.provision(self.path, 0.28)
            self.assertEqual(provider.call_count, 3)

    def test_missing_scope_fails_before_generation(self):
        with patch(
            "factory.budget.request", return_value=b'{"permissions":{"account":[]}}'
        ) as provider:
            with self.assertRaises(RuntimeError):
                budget.provision(self.path, 0.28)
            self.assertEqual(provider.call_count, 1)
            self.assertFalse(budget.secret_path(self.path).exists())

    def test_exhausted_budget_does_not_call_provider(self):
        with patch("factory.budget.request") as provider:
            with self.assertRaises(RuntimeError):
                budget.provision(self.path, 0.28, 0.29)
            provider.assert_not_called()

    def test_key_is_shared_with_pipeline_threads_but_not_account_requests(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self):
                return b"{}"

        authorizations = []

        def fake_urlopen(req, **kwargs):
            authorizations.append((req.full_url, req.get_header("Authorization")))
            return Response()

        with (
            patch("factory.http.key", return_value="test-owner"),
            patch("factory.http._open", side_effect=fake_urlopen),
        ):
            with http.generation_key("test-child"):
                with ThreadPoolExecutor(2) as pool:
                    list(
                        pool.map(
                            http.request,
                            [
                                "https://gen.pollinations.ai/image/a",
                                "https://gen.pollinations.ai/video/a",
                            ],
                        )
                    )
                http.request("https://gen.pollinations.ai/account/balance")
            with self.assertRaises(RuntimeError):
                http.request("https://gen.pollinations.ai/image/b")
        self.assertEqual(
            [auth for _, auth in authorizations],
            ["Bearer test-child", "Bearer test-child", "Bearer test-owner"],
        )


if __name__ == "__main__":
    unittest.main()
