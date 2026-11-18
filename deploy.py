"""Offline server readiness check and source-only release packaging."""

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import time

from factory.config import ROOT
from factory.ff import FFMPEG
from factory.resources import cpu_count, memory_available, render_workers


def check():
    errors, warnings = [], []
    for name in ("pillow", "imageio-ffmpeg"):
        try:
            importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            errors.append(f"Missing dependency: {name}")
    try:
        encoders = subprocess.check_output(
            [FFMPEG, "-hide_banner", "-encoders"], stderr=subprocess.STDOUT, timeout=15
        ).decode()
        if "libx264" not in encoders or " aac " not in encoders:
            errors.append("FFmpeg needs libx264 and AAC")
    except (OSError, subprocess.SubprocessError):
        errors.append("FFmpeg failed")
    for name in ("jobs", "cache"):
        directory = ROOT / name
        try:
            directory.mkdir(exist_ok=True)
            with tempfile.TemporaryFile(dir=directory) as stream:
                stream.write(b"check")
                stream.flush()
                os.fsync(stream.fileno())
        except OSError:
            errors.append(f"Not writable: {name}")
    database = ROOT / "jobs" / ".factory.sqlite3"
    if database.exists():
        try:
            with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
                if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    errors.append("SQLite integrity check failed")
        except sqlite3.Error:
            errors.append("Cannot read SQLite history")
    free = shutil.disk_usage(ROOT).free
    if free < 5 * 1024**3:
        warnings.append("Less than 5 GiB free; long videos need more working space")
    memory = memory_available()
    if memory is not None and memory < 2 * 1024**3:
        warnings.append(
            "Less than 2 GiB available memory; start with one render worker"
        )
    return dict(
        ready=not errors,
        cpu_quota=cpu_count(),
        available_memory_bytes=memory,
        render_workers=render_workers(),
        free_disk_bytes=free,
        errors=errors,
        warnings=warnings,
    )


def package(destination):
    if destination.exists():
        raise ValueError("Release already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    names = (
        "factory",
        "web",
        "assets",
        "tests",
        "server.py",
        "worker.py",
        "manage.py",
        "make_video.py",
        "deploy.py",
        "Dockerfile",
        "docker-compose.yml",
        "deploy",
        "requirements.txt",
        "requirements.lock",
        "requirements-align.txt",
        "requirements-align.lock",
        ".env.example",
        ".dockerignore",
        "README.md",
        "docs/DEPLOY.md",
    )
    files = []
    for name in names:
        path = ROOT / name
        candidates = path.rglob("*") if path.is_dir() else [path]
        files.extend(
            p
            for p in candidates
            if p.is_file()
            and not p.is_symlink()
            and "__pycache__" not in p.parts
            and p.suffix != ".pyc"
        )
    with destination.open("xb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            for path in sorted(files):
                archive.add(path, arcname=str(path.relative_to(ROOT)), recursive=False)
    return dict(archive=str(destination), files=len(files), contains_secrets=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("check", "package"))
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT
        / "releases"
        / ("shorts-" + time.strftime("%Y%m%d-%H%M%S") + ".tar.gz"),
    )
    args = parser.parse_args()
    result = check() if args.command == "check" else package(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.get("ready", True) else 1)
