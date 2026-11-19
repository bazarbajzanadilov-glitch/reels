import contextlib
import json
import subprocess
import threading
import tempfile
import zipfile
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from factory import subtitles
from factory.assemble import _timeline
from factory.render import _render_chunk
from factory.ff import FFMPEG
import server


class SubtitleLayoutTests(unittest.TestCase):
    def scenes(self):
        text = "Каждый новый блок меняет цвет целиком и остаётся хорошо видимым на любом фоне. Следующие две строки продолжают рассказ."
        return [
            {
                "start": 0,
                "dur": 6,
                "speech_start": 0.05,
                "speech_end": 5.7,
                "text": text,
            },
            {
                "start": 6,
                "dur": 5,
                "speech_start": 6.05,
                "speech_end": 10.7,
                "text": "Келесі көріністе қазақша мәтін де толық сақталады.",
            },
        ]

    def test_every_word_survives_and_blocks_have_two_lines_max(self):
        for frame in [(360, 640), (1080, 1920), (1920, 1080)]:
            for size in [28, 54, 96]:
                scenes = self.scenes()
                cues = subtitles.prepare(
                    scenes,
                    frame,
                    {"mode": "cycle", "size": size, "width": 50, "words": 4},
                )
                self.assertEqual(
                    " ".join(" ".join(c["lines"]) for c in cues),
                    " ".join(s["text"] for s in scenes),
                )
                self.assertTrue(all(1 <= len(c["lines"]) <= 2 for c in cues))
                for cue in cues:
                    image = subtitles.render_block(
                        cue, frame, scenes[0]["subtitle_settings"]
                    )
                    self.assertLessEqual(image.width, frame[0])
                    self.assertLess(image.height, frame[1] * 0.5)

    def test_color_changes_on_every_block_and_continues_across_scenes(self):
        scenes = self.scenes()
        cues = subtitles.prepare(
            scenes,
            (1080, 1920),
            {"mode": "cycle", "words": 4, "palette": ["#ffffff", "#ffd166"]},
        )
        self.assertGreater(len(cues), 2)
        for index, cue in enumerate(cues):
            self.assertEqual(cue["color"], ["#ffffff", "#ffd166"][index % 2])
            self.assertEqual(cue["index"], index)
        self.assertEqual(
            scenes[1]["subtitle_cues"][0]["index"], len(scenes[0]["subtitle_cues"])
        )

    def test_single_color_and_timing_within_speech(self):
        scenes = self.scenes()
        cues = subtitles.prepare(
            scenes, (1080, 1920), {"mode": "single", "color": "#33ccff"}
        )
        self.assertEqual({c["color"] for c in cues}, {"#33ccff"})
        for scene in scenes:
            blocks = scene["subtitle_cues"]
            self.assertAlmostEqual(blocks[0]["start"], scene["speech_start"])
            self.assertAlmostEqual(blocks[-1]["end"], scene["speech_end"])
            self.assertTrue(
                all(a["end"] <= b["start"] + 1e-9 for a, b in zip(blocks, blocks[1:]))
            )

    def test_off_preserves_original_captions(self):
        scenes = self.scenes()
        self.assertEqual(subtitles.prepare(scenes, (1080, 1920)), [])
        self.assertEqual(scenes[0]["subtitle_settings"]["mode"], "off")

    def test_bad_settings_are_safe(self):
        options = subtitles.normalize(
            {
                "mode": "cycle",
                "size": float("nan"),
                "outline": 0,
                "width": 999,
                "palette": ["#ffffff", "#ffffff", "<script>"],
                "position": -100,
                "background": "NaN",
            }
        )
        self.assertEqual(options["size"], 54)
        self.assertEqual(options["outline"], 1)
        self.assertEqual(options["width"], 92)
        self.assertEqual(options["position"], 15)
        self.assertEqual(options["background"], 0)
        self.assertGreaterEqual(len(options["palette"]), 2)
        json.dumps(options, allow_nan=False)

    def test_preview_resolution_tracks_large_displays_and_is_bounded(self):
        self.assertEqual(
            subtitles.preview({"mode": "single"}, width=760).size, (760, 1351)
        )
        self.assertEqual(
            subtitles.preview({"mode": "cycle"}, "horizontal", width=1520).size,
            (1520, 855),
        )
        self.assertEqual(subtitles.preview(width=999999).size, (1080, 1920))
        self.assertEqual(subtitles.preview(width=-1).size, (180, 320))

    def test_auto_outline_contrasts_with_dark_and_light_text(self):
        self.assertEqual(subtitles.outline_color("#ffffff", "auto"), "#101014")
        self.assertEqual(subtitles.outline_color("#000000", "auto"), "#ffffff")

    def test_extremely_long_word_still_fits(self):
        scenes = [{"start": 0, "dur": 2, "text": "Сверхдлинноеслово" * 30}]
        cues = subtitles.prepare(
            scenes, (360, 640), {"mode": "single", "size": 96, "width": 50}
        )
        self.assertEqual("".join(cues[0]["lines"]), scenes[0]["text"])
        self.assertLessEqual(
            subtitles.render_block(
                cues[0], (360, 640), scenes[0]["subtitle_settings"]
            ).width,
            360,
        )

    def test_srt_export_uses_cue_times_and_full_text(self):
        cues = subtitles.prepare(self.scenes(), (1080, 1920), {"mode": "single"})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "subtitles.srt"
            subtitles.write_srt(cues, path)
            srt = path.read_text()
            self.assertIn("00:00:00,050 -->", srt)
            self.assertIn("қазақша", srt)
            self.assertEqual(srt.count(" --> "), len(cues))

    def test_timeline_has_real_voice_duration(self):
        scenes, *_ = _timeline([{"text": "Пример текста"}], [("test.wav", 3.25)])
        self.assertEqual(scenes[0]["speech_start"], 0.05)
        self.assertEqual(scenes[0]["speech_end"], 3.3)
        self.assertEqual(scenes[0]["text"], "Пример текста")

    def test_renderer_handles_multiple_blocks_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            image = directory / "background.jpg"
            Image.new("RGB", (360, 640), (95, 130, 180)).save(image)
            scene = {
                "start": 0,
                "dur": 3,
                "speech_start": 0,
                "speech_end": 3,
                "text": "Первый яркий блок текста второй яркий блок текста",
                "camera": "none",
                "caption": "Подпись",
                "image": str(image),
                "danger": False,
            }
            cues = subtitles.prepare(
                [scene],
                (360, 640),
                {
                    "mode": "cycle",
                    "words": 4,
                    "size": 90,
                    "palette": ["#33ccff", "#ff33aa"],
                },
            )
            self.assertEqual(len(cues), 2)
            output = directory / "sample.mp4"
            _render_chunk([scene], 0, 30, 3, (360, 640), 10, str(output), 1)
            self.assertGreater(output.stat().st_size, 1000)
            for index, cue in enumerate(cues):
                timestamp = (cue["start"] + cue["end"]) / 2
                raw = subprocess.check_output(
                    [
                        FFMPEG,
                        "-loglevel",
                        "error",
                        "-ss",
                        str(timestamp),
                        "-i",
                        str(output),
                        "-frames:v",
                        "1",
                        "-f",
                        "rawvideo",
                        "-pix_fmt",
                        "rgb24",
                        "-",
                    ]
                )
                self.assertEqual(len(raw), 360 * 640 * 3)
                cyan = sum(
                    1
                    for r, g, b in zip(raw[0::3], raw[1::3], raw[2::3])
                    if r < 120 and g > 160 and b > 180
                )
                pink = sum(
                    1
                    for r, g, b in zip(raw[0::3], raw[1::3], raw[2::3])
                    if r > 170 and g < 130 and b > 120
                )
                self.assertGreater(cyan if index == 0 else pink, 20)
                self.assertGreater(
                    cyan if index == 0 else pink, pink if index == 0 else cyan
                )


class SubtitlePreviewTests(unittest.TestCase):
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

    def test_preview_never_calls_paid_provider(self):
        client = HTTPConnection(*self.httpd.server_address, timeout=10)
        try:
            payload = json.dumps({"subtitles": {"mode": "cycle"}, "page": 1}).encode()
            with (
                patch(
                    "server.request", side_effect=AssertionError("Paid provider called")
                ),
                patch("server.env", return_value=None),
            ):
                client.request(
                    "POST",
                    "/api/subtitles/preview",
                    body=payload,
                    headers={"Content-Type": "application/json"},
                )
                response = client.getresponse()
                body = response.read()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Content-Type"], "image/png")
            self.assertTrue(body.startswith(b"\x89PNG"))
        finally:
            client.close()

    def test_job_keeps_validated_subtitle_settings_without_running_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            client = HTTPConnection(*self.httpd.server_address, timeout=10)
            try:
                payload = json.dumps(
                    {
                        "topic": "Тест настроек",
                        "subtitles": {
                            "mode": "cycle",
                            "size": 70,
                            "outline": 0,
                            "palette": ["#ffffff", "#33ccff"],
                        },
                    }
                ).encode()
                with (
                    patch("server.JOBS", Path(directory)),
                    patch("server.env", return_value=None),
                    patch(
                        "server.request", side_effect=AssertionError("Provider called")
                    ),
                ):
                    client.request(
                        "POST",
                        "/api/jobs",
                        body=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    response = client.getresponse()
                    job = json.loads(response.read())
                    saved = json.loads(
                        (Path(directory) / job["id"] / "job.json").read_text()
                    )
                    self.assertEqual(
                        server.jobs_store().get(job["id"])["status"], "queued"
                    )
                self.assertEqual(response.status, 200)
                self.assertEqual(saved["subtitles"]["size"], 70)
                self.assertEqual(saved["subtitles"]["outline"], 1)
                self.assertEqual(saved["subtitles"]["palette"], ["#ffffff", "#33ccff"])
            finally:
                client.close()


class SubtitlePipelineTests(unittest.TestCase):
    def test_settings_reach_video_and_srt_is_in_archive(self):
        from factory import pipeline

        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory) / "job"
            directory.mkdir()
            (directory / "script.json").write_text(
                json.dumps({"title": "Тест", "scenes": [{"text": "Пример субтитров"}]})
            )

            def assemble(data, fmt, animate, out, log, clip_limit=None):
                self.assertEqual(data["subtitles"]["mode"], "cycle")
                self.assertEqual(data["subtitles"]["color"], "#33ccff")
                out.write_bytes(b"test-video")
                (out.parent / "subtitles.srt").write_text(
                    "1\n00:00:00,000 --> 00:00:01,000\nПример субтитров\n"
                )
                return out

            def cover(*args):
                Image.new("RGB", (120, 200), "blue").save(directory / "cover.jpg")

            with (
                patch(
                    "factory.pipeline.budget.limit",
                    return_value=contextlib.nullcontext(),
                ),
                patch("factory.pipeline.assemble", side_effect=assemble),
                patch("factory.pipeline.make_cover", side_effect=cover),
            ):
                result = pipeline.run(
                    "Тест",
                    "vertical",
                    1,
                    "none",
                    directory,
                    log=lambda _: None,
                    subtitles={"mode": "cycle", "color": "#33ccff"},
                )
            self.assertIn("subtitles.srt", result["files"])
            with zipfile.ZipFile(directory / "result.zip") as archive:
                self.assertIn("subtitles.srt", archive.namelist())
            self.assertEqual(
                json.loads((directory / "script.json").read_text())["subtitles"][
                    "mode"
                ],
                "cycle",
            )


if __name__ == "__main__":
    unittest.main()
