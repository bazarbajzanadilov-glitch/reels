"""Optional local word timing. No paid transcription endpoint is used."""

import importlib.util
import re
import subprocess
from difflib import SequenceMatcher
from functools import lru_cache
from .config import ROOT
from .files import atomic_json, fingerprint
from .execution import check_cancelled
from .ff import FFMPEG


def available():
    return importlib.util.find_spec("whisper") is not None


@lru_cache(maxsize=1)
def model():
    if not available():
        raise RuntimeError(
            "Для синхронизации по словам установите requirements-align.txt"
        )
    import whisper

    return whisper.load_model("base", device="cpu", download_root=str(ROOT / ".models"))


def align(scenes, voices, lang, directory, log=print):
    engine = model()
    for i, (scene, (wav, _)) in enumerate(zip(scenes, voices)):
        check_cancelled()
        expected = scene["text"].split()
        path = directory / (
            "alignment-"
            + fingerprint({"wav": wav, "text": expected, "lang": lang})
            + ".json"
        )
        if path.exists():
            import json

            scene["word_timings"] = json.loads(path.read_text())
            continue
        import numpy as np

        samples = subprocess.check_output(
            [
                FFMPEG,
                "-nostdin",
                "-loglevel",
                "error",
                "-i",
                str(wav),
                "-f",
                "f32le",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-",
            ],
            timeout=120,
        )
        audio = np.frombuffer(samples, dtype=np.float32).copy()
        result = engine.transcribe(
            audio,
            language=lang,
            word_timestamps=True,
            initial_prompt=scene["text"],
            fp16=False,
            verbose=None,
        )
        words = [
            w
            for segment in result.get("segments", [])
            for w in segment.get("words", [])
            if w.get("word", "").strip()
        ]
        clean = lambda word: re.sub(r"\W", "", word.casefold())
        pairs = SequenceMatcher(
            None,
            [clean(w) for w in expected],
            [clean(w["word"]) for w in words],
            autojunk=False,
        )
        matched = {}
        for block in pairs.get_matching_blocks():
            for offset in range(block.size):
                matched[block.a + offset] = words[block.b + offset]
        if len(matched) < len(expected) * 0.7:
            raise RuntimeError(
                "Не удалось уверенно сопоставить речь и текст. Выберите синхронизацию по фразам или исправьте SRT вручную"
            )
        timings = []
        for n in range(len(expected)):
            if n in matched:
                start = float(matched[n]["start"])
                end = float(matched[n]["end"])
            else:
                left = max((j for j in matched if j < n), default=None)
                right = min((j for j in matched if j > n), default=None)
                a = float(matched[left]["end"]) if left is not None else 0
                b = (
                    float(matched[right]["start"])
                    if right is not None
                    else scene["speech_end"] - scene["speech_start"]
                )
                first = (left + 1) if left is not None else 0
                last = right if right is not None else len(expected)
                step = max(0, b - a) / max(1, last - first)
                start = a + (n - first) * step
                end = start + step
            timings.append(
                {
                    "start": scene["speech_start"] + start,
                    "end": scene["speech_start"] + end,
                }
            )
        scene["word_timings"] = timings
        atomic_json(path, timings)
        log(f"синхронизация: {i + 1}/{len(scenes)}")
