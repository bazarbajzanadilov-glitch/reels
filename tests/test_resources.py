import os
from pathlib import Path
import unittest
from unittest.mock import patch
from factory import resources, render


class ServerResources(unittest.TestCase):
    def test_cpu_quota_wins_over_host_cpu_count(self):
        with (
            patch.object(resources.os, "cpu_count", return_value=64),
            patch.object(
                resources.os,
                "sched_getaffinity",
                create=True,
                return_value=set(range(8)),
            ),
            patch.object(Path, "read_text", return_value="200000 100000"),
        ):
            self.assertEqual(resources.cpu_count(), 2)

    def test_memory_caps_explicit_worker_count(self):
        with (
            patch.dict(os.environ, {"RENDER_WORKERS": "16"}),
            patch.object(resources, "cpu_count", return_value=16),
            patch.object(resources, "memory_available", return_value=1024**3),
        ):
            self.assertEqual(resources.render_workers(), 1)

    def test_auto_workers_leave_cpu_headroom(self):
        with (
            patch.dict(os.environ, {"RENDER_WORKERS": ""}),
            patch.object(resources, "cpu_count", return_value=4),
            patch.object(resources, "memory_available", return_value=8 * 1024**3),
        ):
            self.assertEqual(resources.render_workers(), 3)

    def test_cached_render_assets_are_reused(self):
        render._frame_assets.cache_clear()
        first = render._frame_assets((120, 200))
        self.assertIs(first, render._frame_assets((120, 200)))
        before = [image.tobytes() for image in first]
        render._frame_assets((120, 200))
        self.assertEqual(before, [image.tobytes() for image in first])
