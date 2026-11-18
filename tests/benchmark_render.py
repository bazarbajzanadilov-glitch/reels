"""Offline before/after comparison. No generated assets or provider requests.
Usage: .venv/bin/python tests/benchmark_render.py /path/to/old/render.py
"""

import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PIL import Image
from factory import render, subtitles, http
from factory.ff import FFMPEG


def compare(baseline, size=(540, 960), fps=30):
    spec = importlib.util.spec_from_file_location("factory._baseline", baseline)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    samples = {"before": [], "after": []}
    with (
        tempfile.TemporaryDirectory() as temporary,
        patch.object(http, "_open", side_effect=AssertionError("Offline benchmark")),
    ):
        root = Path(temporary)
        image = root / "source.png"
        Image.linear_gradient("L").resize(size).convert("RGB").save(image)
        for index in range(4):
            scene = dict(
                start=0,
                dur=1,
                image=str(image),
                camera=["zoom_in", "shake", "pan_left", "none"][index],
                danger=index % 2 == 1,
                caption="Проверка качества",
                text="Новый блок субтитров. Проверяем кадры.",
                speech_start=0,
                speech_end=0.95,
            )
            options = subtitles.normalize({"mode": "cycle", "words": 2})
            subtitles.prepare([scene], size, options)
            outputs = {}
            for label, module in (
                [("before", old), ("after", render)]
                if index % 2 == 0
                else [("after", render), ("before", old)]
            ):
                path = root / (label + ".mp4")
                started = time.perf_counter()
                module._render_chunk([scene], 0, fps, 1, size, fps, str(path), 1)
                samples[label].append(time.perf_counter() - started)
                raw = subprocess.check_output(
                    [
                        FFMPEG,
                        "-v",
                        "error",
                        "-i",
                        str(path),
                        "-f",
                        "rawvideo",
                        "-pix_fmt",
                        "rgb24",
                        "-",
                    ]
                )
                outputs[label] = hashlib.sha256(raw).hexdigest()
            if outputs["before"] != outputs["after"]:
                raise AssertionError(f"Frame difference in scene {index}")
    before, after = map(statistics.median, (samples["before"], samples["after"]))
    return {
        "size": size,
        "fps": fps,
        "scenes": 4,
        "decoded_frames_identical": True,
        "median_before_seconds": round(before, 3),
        "median_after_seconds": round(after, 3),
        "speedup": round(before / after, 3),
        "samples": samples,
    }


if __name__ == "__main__":
    print(
        json.dumps(
            compare(
                sys.argv[1],
                size=(1080, 1920) if "--full-hd" in sys.argv else (540, 960),
            ),
            indent=2,
        )
    )
