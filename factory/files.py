"""Atomic outputs, cache locks and media validation, without extra dependencies."""

import fcntl
import hashlib
import io
import json
import os
import subprocess
import tempfile
import wave
from contextlib import contextmanager
from pathlib import Path

from PIL import Image
from .ff import FFMPEG


def atomic_bytes(path: Path, content: bytes, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + path.name + "-", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path: Path, value):
    atomic_bytes(
        path, json.dumps(value, ensure_ascii=False, indent=1, allow_nan=False).encode()
    )


@contextmanager
def path_lock(path: Path):
    lock_dir = path.parent / ".locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(str(path.resolve()).encode()).hexdigest()
    with (lock_dir / name).open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def valid_image(path):
    try:
        with Image.open(path) as image:
            image.verify()
        return True
    except (OSError, ValueError):
        return False


def valid_audio(path):
    try:
        with wave.open(str(path)) as wav:
            return (
                wav.getnframes() > 0
                and wav.getframerate() == 44100
                and wav.getnchannels() == 1
            )
    except (OSError, EOFError, wave.Error):
        return False


def valid_video(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size < 32:
        return False
    try:
        return (
            subprocess.run(
                [
                    FFMPEG,
                    "-v",
                    "error",
                    "-i",
                    str(path),
                    "-map",
                    "0:v:0",
                    "-frames:v",
                    "1",
                    "-f",
                    "null",
                    "-",
                ],
                capture_output=True,
                timeout=30,
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


def jpeg_bytes(image, quality=92):
    output = io.BytesIO()
    image.convert("RGB").save(output, format="JPEG", quality=quality)
    return output.getvalue()


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, default=str, allow_nan=False
        ).encode()
    ).hexdigest()[:24]
