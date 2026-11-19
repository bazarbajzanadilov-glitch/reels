import contextlib
import importlib.util
import json
import tempfile
import threading
import unittest
import wave
import zipfile
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import manage
import server
from factory import alignment, editing, pipeline, subtitles
from factory.files import atomic_json, valid_video
from factory.validation import InvalidRequest


def script():
    return {
        "title": "Тест",
        "scenes": [
            {
                "text": "Первый блок субтитров.",
                "image": "blue landscape",
                "caption": "",
                "motion": "slow motion",
            }
        ],
        "voice_provider": "gemini",
        "style_key": "2d",
        "lang": "ru",
        "subtitles": {"mode": "cycle"},
        "clip_limit": 0,
    }


class WorkflowTests(unittest.TestCase):
    def test_extra_styles_are_selectable_with_safe_budget(self):
        from factory.config import STYLES
        from factory.validation import job_options
        for style in ("cyberpunk", "gouache", "woodcut", "vhs", "stained_glass", "isometric"):
            self.assertEqual(job_options({"topic": "Тест", "style": style})["style"], style)
            self.assertTrue(STYLES[style]["prompt"])
            self.assertTrue(STYLES[style]["motion"])
            self.assertGreater(STYLES[style]["budget"][0], 0)

    def test_parallel_stage_progress_is_preserved(self):
        from factory.store import JobStore
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory))
            store.put({"id": "test", "topic": "test", "status": "running", "created": "2026-01-01"})
            store.progress("test", "этап:voice:running")
            store.progress("test", "этап:images:running")
            store.progress("test", "озвучка 2/4")
            store.progress("test", "картинки 4/4")
            job = store.get("test")
            self.assertEqual(job["stages"]["voice"], {"state": "running", "completed": 2, "total": 4})
            self.assertEqual(job["stages"]["images"]["state"], "done")
            self.assertEqual(job["progress"], "картинки 4/4")

    def test_progress_view_is_computed_from_stages(self):
        from factory.store import progress_view
        job = {"status": "running", "animate": "none", "stages": {
            "script": {"state": "done"}, "voice": {"state": "running", "completed": 1, "total": 2},
            "render": {"state": "running", "completed": 50, "total": 100}}}
        view = progress_view(job)
        self.assertEqual(view["percent"], 8 + 6 + 25 + 12)
        self.assertEqual(view["stage"], "Монтаж видео")
        self.assertEqual(progress_view({"status": "done"})["percent"], 100)
        self.assertEqual(progress_view({"status": "queued"}), {"percent": 0, "stage": "В очереди"})

    def test_render_percent_message_updates_stage(self):
        from factory.store import JobStore
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory))
            store.put({"id": "test", "topic": "test", "status": "running", "created": "2026-01-01"})
            store.progress("test", "монтаж 40%")
            self.assertEqual(store.get("test")["stages"]["render"], {"state": "running", "completed": 40, "total": 100})

    def test_unpaid_cancellation_is_trashed_and_paid_one_is_kept(self):
        from factory.store import JobStore
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory))
            base = {"topic": "test", "status": "queued", "created": "2026-01-01"}
            store.put({**base, "id": "free"})
            self.assertTrue(store.cancel("free")["deleted_at"])
            store.put({**base, "id": "paid", "status": "cancelled", "accounting": "confirmed", "cost": {"total": 0.05}})
            store.put({**base, "id": "pending", "status": "cancelled", "accounting": "pending"})
            store.put({**base, "id": "kept", "status": "cancelled", "kept": True})
            self.assertFalse(store.discard_unpaid("paid"))
            self.assertFalse(store.discard_unpaid("kept"))
            self.assertTrue(store.discard_unpaid("pending"))
            self.assertTrue(store.get("pending")["auto_deleted"])
            store.patch("pending", cost={"total": 0.02})  # провайдер показал списание позже
            self.assertTrue(store.discard_unpaid("pending"))
            self.assertIsNone(store.get("pending")["deleted_at"])

    def test_page_never_calls_paid_generation_on_its_own(self):
        """Платные запросы — создание ролика и сообщения в чат; чат отправляет только по «Отправить»."""
        scripts = "".join(p.read_text(encoding="utf-8") for p in (Path(server.ROOT) / "web" / "js").glob("*.js"))
        self.assertNotIn("/api/assistant", scripts)
        self.assertNotIn("/data/topics.json", scripts)
        source = Path(server.__file__).read_text(encoding="utf-8")
        self.assertNotIn("generation_key", source)

    def test_chat_validates_history_and_picks_model(self):
        from factory import chat
        with self.assertRaises(chat.ChatError):
            chat.reply("gpt", [])
        with self.assertRaises(chat.ChatError):
            chat.reply("unknown", [{"role": "user", "content": "привет"}])
        with self.assertRaises(chat.ChatError):
            chat.clean_messages([{"role": "system", "content": "x"}])
        sent = []

        def fake(url, data=None, headers=None, timeout=0, tries=0, api_key=None):
            sent.append(json.loads(data))
            return json.dumps({"choices": [{"message": {"content": "- Идея один"}}]}).encode()

        with patch("factory.chat.request", side_effect=fake), patch("factory.chat.key", return_value="k"):
            self.assertEqual(chat.reply("claude", [{"role": "user", "content": "идеи"}]), "- Идея один")
        self.assertEqual(sent[0]["model"], chat.MODELS["claude"]["model"])
        self.assertEqual(sent[0]["messages"][0]["role"], "system")

    def test_customer_script_reaches_the_writer_prompt(self):
        from factory import writer
        prompts = []

        def ask(prompt, timeout=400):
            prompts.append(prompt)
            return {"title": "T", "scenes": [{"text": "фраза"}] * 10}

        with patch("factory.writer._ask", side_effect=ask):
            writer.write("Тема", 1, "hero", script="Мой {особый} текст")
        self.assertIn("Мой {особый} текст", prompts[0])

    def test_review_does_not_generate_images_or_video(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "job"
            root.mkdir()
            atomic_json(root / "script.json", script())
            with (
                patch(
                    "factory.pipeline.budget.limit",
                    return_value=contextlib.nullcontext(),
                ),
                patch("factory.pipeline.assemble") as render,
                patch("factory.pipeline.make_cover") as cover,
            ):
                result = pipeline.run(
                    "Тест",
                    "vertical",
                    1,
                    "none",
                    root,
                    log=lambda _: None,
                    script_only=True,
                )
            self.assertTrue(result["draft"])
            render.assert_not_called()
            cover.assert_not_called()

    def test_srt_validates_order_and_preserves_user_text(self):
        result = editing.parse_srt(
            "1\n00:00:01,000 --> 00:00:02,000\nПример текста\n\n2\n00:00:02,000 --> 00:00:03,000\nКелесі блок\n"
        )
        self.assertEqual(result[1]["text"], "Келесі блок")
        with self.assertRaises(InvalidRequest):
            editing.parse_srt("1\n00:00:02,000 --> 00:00:01,000\nbad")

    def test_custom_timing_keeps_color_through_scene_boundary_and_exports_ass(self):
        scenes = [
            {"start": 0, "dur": 2, "text": "one"},
            {"start": 2, "dur": 2, "text": "two"},
        ]
        cues = subtitles.prepare(
            scenes,
            (1080, 1920),
            {"mode": "cycle"},
            [{"start": 1, "end": 3, "text": "Один блок через две сцены"}],
        )
        self.assertEqual(
            scenes[0]["subtitle_cues"][0]["index"],
            scenes[1]["subtitle_cues"][0]["index"],
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "test.ass"
            subtitles.write_ass(cues, (1080, 1920), {"mode": "cycle"}, output)
            content = output.read_text()
            self.assertIn("Dialogue:", content)
            self.assertIn("PlayResY: 1920", content)
            self.assertIn(r"\pos(", content)

    @unittest.skipUnless(importlib.util.find_spec("numpy"), "нужен numpy из requirements-align.txt")
    def test_local_word_alignment_uses_original_text(self):
        scenes = [{"text": "Первый блок текста", "speech_start": 1, "speech_end": 4}]
        response = {
            "segments": [
                {
                    "words": [
                        {"word": "Первый", "start": 0, "end": 0.5},
                        {"word": "блок", "start": 0.5, "end": 1},
                        {"word": "текста", "start": 1, "end": 2},
                    ]
                }
            ]
        }
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("factory.alignment.model") as model,
            patch("factory.alignment.subprocess.check_output", return_value=b"\0" * 64),
        ):
            model.return_value.transcribe.return_value = response
            alignment.align(
                scenes, [("test.wav", 3)], "ru", Path(directory), log=lambda _: None
            )
            self.assertEqual(scenes[0]["word_timings"][0]["start"], 1)
            self.assertEqual(scenes[0]["word_timings"][-1]["end"], 3)
            alignment.align(
                scenes, [("test.wav", 3)], "ru", Path(directory), log=lambda _: None
            )
            self.assertEqual(model.return_value.transcribe.call_count, 1)

    def test_remount_renders_real_video_without_any_provider_call(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            atomic_json(root / "script.json", script())
            image = root / "source.jpg"
            Image.new("RGB", (120, 200), "blue").save(image)
            wav = root / "voice.wav"
            with wave.open(str(wav), "w") as stream:
                stream.setparams((1, 2, 44100, 0, "NONE", "NONE"))
                stream.writeframes(b"\0\0" * 17640)
            Image.new("RGB", (120, 200), "blue").save(root / "cover.jpg")
            for name in ["youtube", "instagram", "tiktok", "facebook"]:
                (root / (name + ".txt")).write_text("test")
            formats = {
                "vertical": {"size": (120, 200), "image": (120, 200), "aspect": "9:16"}
            }
            with (
                patch("factory.assemble.FORMATS", formats),
                patch("factory.audio.CACHE", root / "cache"),
                patch("factory.assemble.images.fetch", return_value=image),
                patch(
                    "factory.assemble.tts.synthesize_all",
                    return_value=[(str(wav), 0.4)],
                ),
                patch(
                    "factory.http._open", side_effect=AssertionError("Provider called")
                ) as provider,
            ):
                result = pipeline.remount(root, "vertical", "none", log=lambda _: None)
            provider.assert_not_called()
            self.assertTrue(valid_video(root / "video.mp4"))
            self.assertIn("subtitles.ass", result["files"])
            with zipfile.ZipFile(root / "result.zip") as archive:
                self.assertIn("subtitles.srt", archive.namelist())

    def test_backup_and_restore_preserve_data_and_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "source"
            (root / "jobs" / "job").mkdir(parents=True)
            (root / "jobs" / "job" / "video.mp4").write_bytes(b"test-media")
            archive = Path(directory) / "backup.zip"
            manage.backup(archive, root)
            restored = Path(directory) / "restored"
            manage.restore(archive, restored)
            self.assertEqual(
                (restored / "jobs" / "job" / "video.mp4").read_bytes(), b"test-media"
            )
            with self.assertRaises(ValueError):
                manage.restore(archive, restored)

    def test_restore_rejects_path_traversal(self):
        import hashlib

        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "evil.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("../bad", b"bad")
                output.writestr(
                    "backup-manifest.json",
                    json.dumps(
                        {
                            "version": 1,
                            "files": {"../bad": hashlib.sha256(b"bad").hexdigest()},
                        }
                    ),
                )
            with self.assertRaises(ValueError):
                manage.restore(archive, Path(directory) / "restore")
            self.assertFalse((Path(directory) / "bad").exists())


class EditorHTTPTests(unittest.TestCase):
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

    def test_edit_then_queue_and_soft_delete_restore(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("server.JOBS", Path(directory)),
            patch("server.env", return_value=None),
        ):
            root = Path(directory)
            store = server.jobs_store()
            job = {
                "id": "draft",
                "topic": "test",
                "format": "vertical",
                "animate": "none",
                "minutes": 1,
                "status": "draft",
                "created": "2026-11-18",
            }
            store.put(job)
            atomic_json(root / "draft" / "script.json", script())

            def call(action, data):
                client = HTTPConnection(*self.httpd.server_address, timeout=5)
                try:
                    client.request(
                        "POST",
                        "/api/jobs/draft/" + action,
                        body=json.dumps(data).encode(),
                        headers={"Content-Type": "application/json"},
                    )
                    response = client.getresponse()
                    value = json.loads(response.read())
                    self.assertEqual(response.status, 200, value)
                    return value
                finally:
                    client.close()

            changed = script()
            changed["scenes"][0]["text"] = "Исправленный текст"
            call("script", changed)
            self.assertEqual(
                editing.load_script(root / "draft")["scenes"][0]["text"],
                "Исправленный текст",
            )
            self.assertTrue(call("trash", {})["deleted_at"])
            self.assertIsNone(call("restore", {})["deleted_at"])
            result = call("render", changed)
            self.assertEqual(result["status"], "queued")
            self.assertEqual(result["task"], "render")
