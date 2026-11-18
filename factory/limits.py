"""Bounded web concurrency and per-address rate limits."""

import threading
import time
from collections import OrderedDict
from http.server import ThreadingHTTPServer


class RateLimiter:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.entries = OrderedDict()

    def allow(self, key, limit, window=60):
        now = self.clock()
        with self.lock:
            started, count = self.entries.pop(key, (now, 0))
            if now - started >= window:
                started, count = now, 0
            allowed = count < limit
            self.entries[key] = (started, count + 1 if allowed else count)
            while len(self.entries) > 4096:
                self.entries.popitem(last=False)
            return allowed


class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(32)
        super().__init__(*args, **kwargs)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            try:
                request.settimeout(1)
                request.sendall(
                    b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                )
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()
