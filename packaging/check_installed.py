#!/usr/bin/python3
"""Smoke-check an installed DEB and isolated data across an APT upgrade.

Run ``check --package-version VERSION`` after installation. Run ``seed`` with
the old package installed, upgrade through APT, then run ``verify`` with the
same --profile directory. Only seed/verify use that explicitly selected test
profile; no real user library is opened. These are automated checks, not a
manual desktop, screen-reader or audio test.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


INSTALLED = Path("/usr/share/malferma-libro")
LAUNCHER = "/usr/bin/malferma-libro"
APP_ID = "io.github.otkrytaya_kniga.Reader"
BOOK_TEXT = ("A small book for an installation test.\n\n"
             "Українська: читання. Deutsch: Bücher. Esperanto: libro.\n") * 60


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def installed_module():
    expected = INSTALLED / "malferma_libro/__init__.py"
    require(expected.is_file(), f"Installed module is missing: {expected}")
    sys.path.insert(0, str(INSTALLED))
    import malferma_libro

    require(Path(malferma_libro.__file__).resolve() == expected.resolve(),
            "The check imported a source checkout instead of the installed package")
    return malferma_libro


def run(*command: str, cwd: str | Path = "/tmp") -> str:
    environment = dict(os.environ, LC_ALL="C.UTF-8")
    for variable in ("PYTHONPATH", "PYTHONHOME", "DISPLAY", "WAYLAND_DISPLAY"):
        environment.pop(variable, None)
    result = subprocess.run(command, cwd=cwd, env=environment, check=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", timeout=30)
    return result.stdout


def file_hashes(root: Path) -> dict[str, str]:
    result = {}
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), f"Unexpected symlink in test profile: {path}")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def seed(profile: Path) -> None:
    from malferma_libro.storage import Library

    require(not profile.is_symlink(), "The test profile must not be a symlink")
    require(not profile.exists() or (profile.is_dir() and not any(profile.iterdir())),
            "Seed needs a new or empty test profile; existing data will not be overwritten")
    profile.mkdir(parents=True, exist_ok=True)
    source = profile / "Читання — Bücher.txt"
    source.write_text(BOOK_TEXT, encoding="utf-8")
    library = Library(profile / "library")
    book = library.import_book(source)
    library.update_settings({"font_size": 28, "theme": "dark", "interface_language": "de"})
    library.update_reading_progress(book["id"], 0, 97, 12.5)
    library.add_bookmark(book["id"], 0, 97, "Upgrade bookmark", note="Збережена нотатка")
    library.add_catalog("Test catalog", "https://example.org/opds.xml")
    library.mark_opened(book["id"])
    expected = {
        "files": file_hashes(library.root),
        "books": library.books,
        "settings": library.settings,
        "catalogs": library.catalogs,
        "last_book_id": book["id"],
    }
    (profile / "expected.json").write_text(
        json.dumps(expected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Seeded an isolated test library with the installed package.", flush=True)


def verify(profile: Path) -> None:
    from malferma_libro.books import load_book
    from malferma_libro.storage import Library

    require(not profile.is_symlink(), "The test profile must not be a symlink")
    expected = json.loads((profile / "expected.json").read_text(encoding="utf-8"))
    root = profile / "library"
    require(file_hashes(root) == expected["files"],
            "Package installation changed or removed files in the test library")
    library = Library(root)
    require(not library.warnings, f"Loading the test library produced warnings: {library.warnings}")
    require(library.books == expected["books"], "Books, positions or bookmarks changed")
    require(library.settings == expected["settings"], "Reader settings changed")
    require(library.catalogs == expected["catalogs"], "OPDS catalog settings changed")
    last = library.last_opened_book()
    require(last is not None and last["id"] == expected["last_book_id"],
            "The last opened book was not preserved")
    content = load_book(Path(last["path"]))
    require(BOOK_TEXT.strip() == content.chapters[0].text.strip(),
            "The managed book no longer contains the original text")
    print("Installed package preserved and reopened the seeded library.", flush=True)


def check(package_version: str, module) -> None:
    status = run("dpkg-query", "-W", "-f=${Status}\n${Version}\n", "malferma-libro").splitlines()
    require(status == ["install ok installed", package_version],
            f"Unexpected installed package state: {status}")
    require(package_version.split("-", 1)[0] == module.__version__,
            "The installed application and Debian package versions disagree")
    require(not run("dpkg", "--verify", "malferma-libro").strip(),
            "Installed package files failed dpkg verification")
    require(run(LAUNCHER, "--version").strip() == f"{module.APP_NAME} {module.__version__}",
            "The installed launcher reported an unexpected version")
    require("--manual" in run(LAUNCHER, "--help"), "Installed CLI help is missing")
    assets = INSTALLED / "malferma_libro/assets"
    for language in ("ru", "en", "de", "uk"):
        filename = "MANUAL.md" if language == "ru" else f"MANUAL.{language}.md"
        manual = (assets / "docs" / filename).read_text(encoding="utf-8")
        require(bool(manual.strip()) and run(LAUNCHER, f"--manual={language}") == manual,
                f"The installed {language} manual does not match its resource")
    require(run(LAUNCHER, "--license") == (assets / "docs/LICENSE").read_text(encoding="utf-8"),
            "Installed CLI license text is incomplete")
    for name in ("LICENSE", "copyright", "README.md", "FONT_LICENSES.md", "LOGO_LICENSE.md"):
        require((Path("/usr/share/doc/malferma-libro") / name).stat().st_size > 0,
                f"Installed documentation is empty: {name}")
    desktop = f"/usr/share/applications/{APP_ID}.desktop"
    run("desktop-file-validate", desktop)
    for path in (
        Path(f"/usr/share/icons/hicolor/scalable/apps/{APP_ID}.svg"),
        Path(f"/usr/share/metainfo/{APP_ID}.metainfo.xml"),
    ):
        require(path.stat().st_size > 0, f"Missing installed desktop resource: {path}")
    for language in ("", "de", "uk"):
        path = Path("/usr/share/man") / language / "man1/malferma-libro.1.gz"
        require(b".TH" in gzip.decompress(path.read_bytes()), f"Invalid installed man page: {path}")
    default_manual = Path("/usr/share/man/man1/malferma-libro.1.gz").resolve()
    require(any(Path(name).resolve() == default_manual
                for name in run("man", "-w", "malferma-libro").splitlines()),
            "man could not locate the installed command-line manual")
    from malferma_libro.appearance import _FONT_FILES

    for name in _FONT_FILES:
        require((assets / "fonts" / name).stat().st_size > 0, f"Missing installed font: {name}")
    import gi
    import markdown_it

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk

    require(Gtk.get_major_version() == 4 and Adw.get_major_version() == 1,
            "The required GTK/libadwaita runtime could not be loaded")
    require(bool(markdown_it.MarkdownIt().render("**Installed**")), "Markdown runtime failed")
    for command in ("pdftotext", "pdftoppm", "djvused", "ddjvu"):
        require(shutil.which(command) is not None, f"Missing document helper: {command}")
    with tempfile.TemporaryDirectory(prefix="malferma-installed-") as temporary:
        profile = Path(temporary) / "profile"
        seed(profile)
        verify(profile)
    print(f"Installed DEB {package_version}: CLI, resources, dependencies and library checks passed.",
          flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    commands.add_parser("check").add_argument("--package-version", required=True)
    for mode in ("seed", "verify"):
        commands.add_parser(mode).add_argument("--profile", type=Path, required=True)
    args = parser.parse_args()
    try:
        module = installed_module()
        if args.mode == "check":
            check(args.package_version, module)
        else:
            profile = args.profile.absolute()
            {"seed": seed, "verify": verify}[args.mode](profile)
    except (OSError, ValueError, RuntimeError, ImportError, subprocess.SubprocessError) as error:
        print(f"Installed-package check failed: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
