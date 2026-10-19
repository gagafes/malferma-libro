#!/usr/bin/python3
"""Build reproducible Debian and source archives without root or network access.

The single version source is src/malferma_libro/__init__.py. Set
SOURCE_DATE_EPOCH to a nonnegative Unix timestamp to choose archive timestamps;
the default is zero. Source archives contain project inputs, never dist/, Git
metadata, caches, local environments or previously built packages.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import gzip
import hashlib
import io
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRECTORIES = ("src", "data", "docs", "packaging", "po", "tests", ".github")
SOURCE_FILES = (
    "LICENSE", "README.md", "Makefile", "pyproject.toml", "MANIFEST.in",
    ".gitignore", ".gitattributes", ".editorconfig",
)
IGNORED_DIRECTORIES = {"__pycache__", ".git", ".venv", "venv", "build", "dist", ".pytest_cache"}
IGNORED_SUFFIXES = {".pyc", ".pyo", ".deb"}


def ignored_input(relative: Path) -> bool:
    """Keep local environments, caches and editor backups out of releases."""
    return relative.suffix in IGNORED_SUFFIXES or any(
        part in IGNORED_DIRECTORIES or part.endswith(".egg-info")
        or part == ".env" or part.startswith(".env.")
        or part == ".DS_Store" or part.endswith("~")
        for part in relative.parts
    )


def version(root: Path = ROOT) -> str:
    """Read metadata without importing GTK or executing application code."""
    tree = ast.parse((root / "src/malferma_libro/__init__.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if isinstance(value, str) and re.fullmatch(r"\d+\.\d+\.\d+", value):
                return value
    raise ValueError("__version__ must be a literal major.minor.patch string")


def source_epoch() -> int:
    raw = os.environ.get("SOURCE_DATE_EPOCH", "0")
    if not raw.isascii() or not raw.isdecimal():
        raise ValueError("SOURCE_DATE_EPOCH must be a nonnegative integer")
    epoch = int(raw)
    if epoch > 0xFFFFFFFF:
        raise ValueError("SOURCE_DATE_EPOCH exceeds the gzip timestamp range")
    return epoch


def source_files(root: Path = ROOT) -> list[Path]:
    """Explicit release inputs, independent of whether Git was initialized."""
    for name in SOURCE_FILES:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Required release input must be a regular file: {name}")
    candidates = [root / name for name in SOURCE_FILES]
    candidates.extend(root.glob("*.md"))
    for name in SOURCE_DIRECTORIES:
        directory = root / name
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError(f"Required source directory must be a real directory: {name}")
        candidates.extend(directory.rglob("*"))
    result = []
    for path in candidates:
        relative = path.relative_to(root)
        if ignored_input(relative):
            continue
        if path.is_symlink():
            raise ValueError(f"Release inputs must not contain symlinks: {relative}")
        if path.is_file():
            result.append(path)
    return sorted(set(result), key=lambda item: item.relative_to(root).as_posix())


def file_mode(path: Path, root: Path) -> int:
    relative = path.relative_to(root).as_posix()
    return 0o755 if relative == "packaging/malferma-libro" else 0o644


def build_source(root: Path, output: Path, epoch: int) -> list[Path]:
    files = source_files(root)
    release_version = version(root)
    prefix = f"malferma-libro-{release_version}"
    output.mkdir(parents=True, exist_ok=True)
    archive_paths = [output / f"malferma-libro_{release_version}_source.tar.gz",
                     output / f"malferma-libro_{release_version}_source.zip"]
    # ZIP dates begin in 1980; clamp its timestamp without affecting tar/DEB.
    zip_epoch = min(max(epoch, 315532800), 4354819198)
    zip_date = datetime.fromtimestamp(zip_epoch, timezone.utc).timetuple()[:6]
    with tempfile.TemporaryDirectory(prefix=".source-", dir=output) as temporary:
        tar_path = Path(temporary) / archive_paths[0].name
        with tar_path.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", mtime=epoch, fileobj=raw) as compressed:
                with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                    for path in files:
                        contents = path.read_bytes()
                        entry = tarfile.TarInfo(f"{prefix}/{path.relative_to(root).as_posix()}")
                        entry.size = len(contents)
                        entry.mode = file_mode(path, root)
                        entry.mtime = epoch
                        entry.uid = entry.gid = 0
                        entry.uname = entry.gname = "root"
                        archive.addfile(entry, io.BytesIO(contents))
        zip_path = Path(temporary) / archive_paths[1].name
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in files:
                entry = zipfile.ZipInfo(f"{prefix}/{path.relative_to(root).as_posix()}", date_time=zip_date)
                entry.create_system = 3
                entry.external_attr = (0o100000 | file_mode(path, root)) << 16
                entry.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(entry, path.read_bytes(), compresslevel=9)
        for temporary_path, destination in zip((tar_path, zip_path), archive_paths):
            temporary_path.replace(destination)
    return archive_paths


def _copy_file(source: Path, destination: Path, mode: int = 0o644):
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"Package input must be a regular file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    destination.chmod(mode)


def _copy_tree(source: Path, destination: Path):
    if not source.is_dir() or source.is_symlink():
        raise ValueError(f"Package input must be a real directory: {source}")
    for path in sorted(source.rglob("*")):
        if ignored_input(path.relative_to(source)):
            continue
        if path.is_symlink():
            raise ValueError(f"Package inputs must not contain symlinks: {path}")
        if path.is_file():
            _copy_file(path, destination / path.relative_to(source))


def build_deb(root: Path, output: Path, epoch: int) -> Path:
    """Stage only application/runtime assets and documentation, then call dpkg."""
    # Apply the same release boundary to both formats: a symlinked source
    # ancestor or document must not silently import external/private files.
    source_files(root)
    release_version = version(root)
    if shutil.which("dpkg-deb") is None:
        raise RuntimeError("dpkg-deb is required; install the Debian dpkg-dev package")
    output.mkdir(parents=True, exist_ok=True)
    destination = output / f"malferma-libro_{release_version}_all.deb"
    with tempfile.TemporaryDirectory(prefix=".deb-", dir=output) as temporary:
        stage = Path(temporary) / "package"
        stage.mkdir(mode=0o755)
        _copy_tree(root / "src/malferma_libro", stage / "usr/share/malferma-libro/malferma_libro")
        _copy_file(root / "packaging/malferma-libro", stage / "usr/bin/malferma-libro", 0o755)
        for name in ("applications", "icons", "metainfo"):
            _copy_tree(root / "data" / name, stage / "usr/share" / name)
        documentation = stage / "usr/share/doc/malferma-libro"
        for path in sorted(root.glob("*.md")):
            _copy_file(path, documentation / path.name)
        for path in sorted((root / "docs").glob("*.md")):
            _copy_file(path, documentation / path.name)
        _copy_file(root / "LICENSE", documentation / "LICENSE")
        _copy_file(root / "packaging/copyright", documentation / "copyright")
        for path in sorted((root / "data").rglob("malferma-libro.1")):
            language = path.parent.relative_to(root / "data")
            manual = stage / "usr/share/man" / language / "man1/malferma-libro.1.gz"
            manual.parent.mkdir(parents=True, exist_ok=True)
            manual.write_bytes(gzip.compress(path.read_bytes(), mtime=0))
            manual.chmod(0o644)
        payload = sorted(path for path in stage.rglob("*") if path.is_file())
        installed_size = (sum(path.stat().st_size for path in payload) + 1023) // 1024
        control = stage / "DEBIAN"
        control.mkdir(mode=0o755)
        template = (root / "packaging/control.in").read_text(encoding="utf-8")
        (control / "control").write_text(template.format(
            version=release_version, installed_size=installed_size), encoding="utf-8")
        (control / "md5sums").write_text("".join(
            f"{hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()}  {path.relative_to(stage).as_posix()}\n"
            for path in payload), encoding="utf-8")
        for path in [stage, *stage.rglob("*")]:
            if path.is_dir():
                path.chmod(0o755)
            else:
                path.chmod(0o755 if path == stage / "usr/bin/malferma-libro" else 0o644)
            os.utime(path, (epoch, epoch))
        environment = dict(os.environ, SOURCE_DATE_EPOCH=str(epoch), TZ="UTC", LC_ALL="C.UTF-8")
        built = Path(temporary) / destination.name
        subprocess.run(["dpkg-deb", "--root-owner-group", "--uniform-compression", "-Zxz", "-z6",
                        "--build", str(stage), str(built)], check=True, env=environment)
        built.replace(destination)
    return destination


def write_checksums(output: Path, release_version: str):
    paths = [output / f"malferma-libro_{release_version}_{suffix}"
             for suffix in ("all.deb", "source.tar.gz", "source.zip")]
    if any(path.is_symlink() for path in paths):
        raise ValueError("Release artifacts must not be symlinks")
    paths = [path for path in paths if path.is_file()]
    (output / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in paths), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=("deb", "source", "all"))
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args(argv)
    try:
        epoch = source_epoch()
        paths = []
        if args.target in {"deb", "all"}:
            paths.append(build_deb(ROOT, args.output, epoch))
        if args.target in {"source", "all"}:
            paths.extend(build_source(ROOT, args.output, epoch))
        write_checksums(args.output, version(ROOT))
        for path in paths:
            print(path)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Build failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
