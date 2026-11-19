"""Private backups and reversible cache maintenance. Never overwrites an existing restore."""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path
from factory.config import ROOT, CACHE
from factory.files import atomic_json
from factory.store import JobStore, ACTIVE


def backup(destination: Path, root: Path = ROOT):
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destination.exists():
        raise ValueError("Архив уже существует")
    allowed = [
        p
        for p in root.rglob("*")
        if p.is_file()
        and not p.is_symlink()
        and p.relative_to(root).parts[0]
        in ("factory", "web", "assets", "jobs", "cache", "tests")
        and "__pycache__" not in p.parts
        and ".locks" not in p.parts
        and not any(part.endswith((".partial.mp4", ".tmp")) for part in p.parts)
    ]
    allowed += [
        root / name
        for name in (
            "server.py",
            "worker.py",
            "manage.py",
            "requirements.txt",
            "requirements.lock",
            "requirements-align.txt",
            "README.md",
            ".env.example",
            ".env",
        )
        if (root / name).is_file()
    ]
    temporary = destination.with_suffix(".partial.zip")
    manifest = {}
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    try:
        with (
            tempfile.TemporaryDirectory() as work,
            zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive,
        ):
            database = root / "jobs" / ".factory.sqlite3"
            snapshot = Path(work) / "database.sqlite3"
            if database.exists():
                with (
                    sqlite3.connect(database) as source,
                    sqlite3.connect(snapshot) as target,
                ):
                    source.backup(target)
            for path in allowed:
                relative = path.relative_to(root).as_posix()
                if path.name.startswith(".factory.sqlite3"):
                    if path.name != ".factory.sqlite3":
                        continue
                    path = snapshot
                digest = hashlib.sha256()
                with (
                    path.open("rb") as source,
                    archive.open(relative, "w", force_zip64=True) as target,
                ):
                    while content := source.read(1024 * 1024):
                        digest.update(content)
                        target.write(content)
                manifest[relative] = digest.hexdigest()
            archive.writestr(
                "backup-manifest.json", json.dumps({"version": 1, "files": manifest})
            )
        temporary.chmod(0o600)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return len(manifest)


def restore(archive_path: Path, destination: Path):
    if destination.exists():
        raise ValueError("Для восстановления нужен новый, несуществующий каталог")
    with zipfile.ZipFile(archive_path) as archive:
        info = json.loads(archive.read("backup-manifest.json"))
        if info.get("version") != 1 or len(info.get("files", {})) > 100000:
            raise ValueError("Неверный архив")
        names = archive.namelist()
        if len(set(names)) != len(names) or set(names) != set(info["files"]) | {
            "backup-manifest.json"
        }:
            raise ValueError("Состав архива не совпадает с манифестом")
        for name, digest in info["files"].items():
            path = Path(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name:
                raise ValueError("Небезопасный путь в архиве")
            measured = hashlib.sha256()
            with archive.open(name) as stream:
                while block := stream.read(1024 * 1024):
                    measured.update(block)
            if measured.hexdigest() != digest:
                raise ValueError("Нарушена целостность архива")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=destination.parent) as work:
            tree = Path(work) / "restore"
            tree.mkdir(mode=0o700)
            for name in info["files"]:
                path = tree / name
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with archive.open(name) as source, path.open("wb") as target:
                    shutil.copyfileobj(source, target, 1024 * 1024)
                path.chmod(0o600)
            tree.rename(destination)
    return len(info["files"])


def cleanup(root: Path = ROOT, days=30, apply=False):
    if any(j["status"] in ACTIVE for j in JobStore(root / "jobs").list()):
        raise ValueError("Сначала дождитесь освобождения очереди")
    before = time.time() - days * 86400
    files = [
        p
        for p in (root / "cache").rglob("*")
        if p.is_file() and ".locks" not in p.parts and p.stat().st_mtime < before
    ]
    total = sum(p.stat().st_size for p in files)
    batch = root / ".trash-cache" / time.strftime("%Y%m%d-%H%M%S")
    if apply:
        batch.mkdir(parents=True, exist_ok=False, mode=0o700)
        for source in files:
            relative = source.relative_to(root / "cache")
            target = batch / "files" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
        atomic_json(
            batch / "manifest.json",
            {"files": [str(p.relative_to(root / "cache")) for p in files]},
        )
    return {
        "files": len(files),
        "bytes": total,
        "moved": apply,
        "batch": str(batch) if apply else None,
    }


def restore_cache(batch: Path, cache: Path = CACHE):
    data = json.loads((batch / "manifest.json").read_text())
    for name in data["files"]:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Некорректный путь")
        if (cache / relative).exists():
            raise ValueError("В кэше уже есть такой файл; перезапись запрещена")
    for name in data["files"]:
        source = batch / "files" / name
        target = cache / name
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
    return len(data["files"])


NICHES = [
    "Что если…", "Страшные истории", "Космос", "Выживание", "Тайны истории", "Психология",
    "Мотивация", "Загадки природы", "Технологии будущего", "Городские легенды", "Животные",
    "Невероятные совпадения", "Детективы", "Мифы и легенды", "Наука простыми словами",
    "Путешествия", "Лайфхаки", "Истории успеха", "Неразгаданные тайны", "Сказки для взрослых",
]
STYLE_SCENE = "the hero stands on a hill at sunset looking at a small town below, wide shot"
SUBTITLE_SCENE = "the hero walks through a quiet evening street with warm lights, medium shot"


def topic_library(path: Path = ROOT / "web" / "data" / "topics.json", count=100):
    """Разовая платная генерация библиотеки тем; дальше помощник листает её бесплатно."""
    from factory import writer
    from factory.config import key
    from factory.http import generation_key

    library = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    angles = ["", " — неочевидные и спорные", " — личные истории и случаи", " — короткие факты и вопросы"]
    with generation_key(key()):
        for niche in NICHES:
            topics = library.get(niche, [])
            for angle in angles:  # по 50: длинный список модель иногда обрывает или зацикливает
                if len(topics) >= count:
                    break
                topics += [t for t in writer.topics(f"Темы для ниши «{niche}»{angle}", "ru", 50) if t not in topics]
                library[niche] = topics[:count]
                atomic_json(path, library)
    return {niche: len(items) for niche, items in library.items()}


def visual_assets(root: Path = ROOT / "web" / "img"):
    """Разовая генерация превью стилей и подложек превью субтитров (~$0.04)."""
    from PIL import Image
    from factory import images
    from factory.config import CHARACTER, STYLE, STYLES, STYLE_TAIL, key
    from factory.http import generation_key

    jobs = [(f"styles/{name}.webp", STYLES[name]["prompt"] + STYLE_TAIL, STYLE_SCENE, (512, 640), (320, 400))
            for name in STYLES if name != "custom"]
    jobs += [("subtitle-vertical.webp", STYLE, SUBTITLE_SCENE, (768, 1344), (540, 960)),
             ("subtitle-horizontal.webp", STYLE, SUBTITLE_SCENE, (1344, 768), (960, 540))]
    with generation_key(key()):
        for name, style, scene, size, final in jobs:
            target = root / name
            if target.is_file():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(images.fetch(scene, style, CHARACTER, 7, size)) as image:
                image.convert("RGB").resize(final, Image.LANCZOS).save(target, "WEBP", quality=82)
    return sorted(str(p.relative_to(root)) for p in root.rglob("*.webp"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("backup")
    p.add_argument(
        "--output",
        type=Path,
        default=ROOT
        / "backups"
        / ("shorts-" + time.strftime("%Y%m%d-%H%M%S") + ".zip"),
    )
    p = commands.add_parser("restore")
    p.add_argument("archive", type=Path)
    p.add_argument("destination", type=Path)
    p = commands.add_parser("cleanup")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--apply", action="store_true")
    p = commands.add_parser("restore-cache")
    p.add_argument("batch", type=Path)
    commands.add_parser("topics")
    commands.add_parser("assets")
    args = parser.parse_args()
    if args.command == "backup":
        print(json.dumps({"files": backup(args.output), "archive": str(args.output)}))
    elif args.command == "restore":
        print(json.dumps({"files": restore(args.archive, args.destination)}))
    elif args.command == "cleanup":
        print(json.dumps(cleanup(days=max(1, args.days), apply=args.apply)))
    elif args.command == "restore-cache":
        print(json.dumps({"files": restore_cache(args.batch)}))
    elif args.command == "topics":
        print(json.dumps(topic_library(), ensure_ascii=False))
    elif args.command == "assets":
        print(json.dumps(visual_assets()))
