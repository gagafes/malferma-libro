#!/usr/bin/python3
"""Capture the real GTK application with an isolated demonstration library.

Run from a graphical X11 session, or with:
  xvfb-run -a -s '-screen 0 1600x1200x24' dbus-run-session -- \
    /usr/bin/python3 -B packaging/screenshots.py

Dependencies: the application's GTK4/libadwaita runtime, python3-cairo,
Xvfb (for headless capture), and ImageMagick's import command. No network,
personal library, external artwork, desktop mock-up, or modified UI is used.
Each scene runs in a fresh process with temporary XDG directories.

SPDX-License-Identifier: GPL-3.0-or-later
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from xml.sax.saxutils import escape
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SCENES = ("reading-light", "reading-dark", "library-light")
WIDTH, HEIGHT = 1440, 1000
POEM_SOURCE = "https://uk.wikisource.org/wiki/Сторінка:Леся_Українка._На_крилах_пісень._1892.pdf/28"
POEM = """Ні долі ні волі у ме́не нема
Зосталася тілько надія одна:

Надія вернутись ще раз на Вкраїну,
Поглянуть іще раз на рідну країну,

Поглянуть іще раз на синій Дніпро, —
Там жити, чі вмерти, мені все їдно;

Поглянуть іще раз на степ, могилки́,
В останнє згадати палкиї гадки́....

Ні долі, ні волі у мене нема,
Зосталася тілько надія одна.
"""


def _art(path: Path, *, cover: bool = False, variant: int = 0) -> bytes:
    """Draw original geometric artwork, never artwork from a book edition."""
    import cairo

    width, height = (360, 500) if cover else (1200, 300)
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, width, height)
    context = cairo.Context(surface)
    palettes = (("#102e47", "#f3d999", "#388788"),
                ("#494338", "#eee1ba", "#91ad8e"),
                ("#423e63", "#eee2be", "#9a9fc3"))

    def colour(value):
        context.set_source_rgb(*(int(value[index:index + 2], 16) / 255
                                 for index in (1, 3, 5)))

    background, gold, accent = palettes[variant % len(palettes)]
    colour(background)
    context.paint()
    if cover:
        colour(gold)
        context.set_line_width(2)
        context.rectangle(23, 23, width - 46, height - 46)
        context.stroke()
        context.arc(width / 2, 190, 72, 0, 6.283185307)
        context.fill()
        colour(accent)
        context.move_to(48, 330)
        context.curve_to(100, 270, 120, 285, 180, 310)
        context.curve_to(240, 285, 260, 270, 312, 330)
        context.line_to(312, 370)
        context.curve_to(250, 330, 235, 330, 180, 350)
        context.curve_to(125, 330, 110, 330, 48, 370)
        context.close_path()
        context.fill()
        colour(gold)
        context.select_font_face("Noto Sans", cairo.FONT_SLANT_NORMAL,
                                 cairo.FONT_WEIGHT_NORMAL)
        context.set_font_size(18)
        title = ("НАДІЯ", "QUIET PAGES", "SMALL ATLAS")[variant % 3]
        extents = context.text_extents(title)
        context.move_to((width - extents.width) / 2 - extents.x_bearing, 425)
        context.show_text(title)
    else:
        colour(gold)
        context.arc(890, 95, 54, 0, 6.283185307)
        context.fill()
        colour(accent)
        context.move_to(0, 185)
        context.curve_to(260, 105, 360, 215, 590, 175)
        context.curve_to(860, 90, 980, 235, 1200, 130)
        context.line_to(1200, height)
        context.line_to(0, height)
        context.close_path()
        context.fill()
        colour(gold)
        context.set_line_width(5)
        context.move_to(0, 245)
        context.curve_to(340, 145, 490, 285, 720, 218)
        context.curve_to(940, 155, 1080, 215, 1200, 195)
        context.stroke()
    surface.write_to_png(str(path))
    return path.read_bytes()


def _epub(path: Path, title: str, author: str, chapters, cover: bytes,
          illustration: bytes | None = None, *, language="en") -> None:
    manifest = ''.join(f'<item id="c{index}" href="chapter{index}.xhtml" '
                       'media-type="application/xhtml+xml"/>'
                       for index in range(len(chapters)))
    spine = ''.join(f'<itemref idref="c{index}"/>' for index in range(len(chapters)))
    nav = ''.join(f'<li><a href="chapter{index}.xhtml">{escape(heading)}</a></li>'
                  for index, (heading, _body) in enumerate(chapters))
    package = ('<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
               'unique-identifier="book"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
               f'<dc:identifier id="book">urn:malferma-demo:{escape(path.stem)}</dc:identifier>'
               f'<dc:title>{escape(title)}</dc:title><dc:creator>{escape(author)}</dc:creator>'
               f'<dc:language>{language}</dc:language>'
               '<meta property="dcterms:modified">2026-01-01T00:00:00Z</meta></metadata>'
               f'<manifest>{manifest}<item id="nav" href="nav.xhtml" '
               'media-type="application/xhtml+xml" properties="nav"/>'
               '<item id="cover" href="cover.png" media-type="image/png" properties="cover-image"/>'
               + ('<item id="landscape" href="landscape.png" media-type="image/png"/>'
                  if illustration else '')
               + f'</manifest><spine>{spine}</spine></package>')
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", '<container version="1.0" '
                         'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                         '<rootfiles><rootfile full-path="OPS/book.opf" '
                         'media-type="application/oebps-package+xml"/></rootfiles></container>')
        archive.writestr("OPS/book.opf", package)
        archive.writestr("OPS/nav.xhtml", '<html xmlns="http://www.w3.org/1999/xhtml" '
                         'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Contents</title>'
                         f'</head><body><nav epub:type="toc"><ol>{nav}</ol></nav></body></html>')
        for index, (heading, body) in enumerate(chapters):
            archive.writestr(f"OPS/chapter{index}.xhtml", '<html xmlns="http://www.w3.org/1999/xhtml">'
                             f'<head><title>{escape(heading)}</title></head><body>{body}</body></html>')
        archive.writestr("OPS/cover.png", cover)
        if illustration:
            archive.writestr("OPS/landscape.png", illustration)


def _fixture_library(root: Path):
    from malferma_libro.books import load_book
    from malferma_libro.storage import Library

    library = Library()
    cover = _art(root / "nadia-cover.png", cover=True)
    landscape = _art(root / "landscape.png")
    body = '<h1>Надія</h1><p><img src="landscape.png" alt="Стилізований річковий краєвид"/></p><p>'
    body += '<br/>'.join(escape(line) for line in POEM.strip().splitlines()) + '</p>'
    notes = ('<h1>Про видання</h1><p>Леся Українка. «Надія» (1880).</p>'
             '<p>Оригінальний український текст. Ілюстрацію та обкладинку створено '
             'спеціально для демонстрації Malferma Libro; вони не належать до історичного видання.</p>')
    path = root / "Надія.epub"
    _epub(path, "Надія", "Леся Українка", [("Надія", body), ("Про видання", notes)],
          cover, landscape, language="uk")
    book = load_book(path)
    record = library.import_book(path, book)

    quiet_cover = _art(root / "quiet-cover.png", cover=True, variant=1)
    quiet = root / "Quiet Pages.fb2"
    quiet.write_text('<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" '
                     'xmlns:xlink="http://www.w3.org/1999/xlink"><description><title-info>'
                     '<author><first-name>Malferma Libro</first-name><last-name>demo</last-name></author>'
                     '<book-title>Quiet Pages</book-title><lang>en</lang>'
                     '<coverpage><image xlink:href="#cover"/></coverpage></title-info></description>'
                     '<body><section><title><p>A place to read</p></title>'
                     '<p>The window is open. Somewhere outside, a branch taps softly against the wall. '
                     'There is time for another page, and then perhaps a cup of tea.</p>'
                     '<p>This is an original demonstration text for Malferma Libro.</p></section></body>'
                     '<binary id="cover" content-type="image/png">'
                     + base64.b64encode(quiet_cover).decode("ascii") + '</binary></FictionBook>',
                     encoding="utf-8")
    library.import_book(quiet)
    atlas = root / "A Small Atlas.epub"
    _epub(atlas, "A Small Atlas", "Malferma Libro demo",
          [("Lines and shapes", '<h1>Lines and shapes</h1><p>A circle marks a beginning. '
            'A line carries the eye across the page. A little space makes room for both.</p>'
            '<p>This is an original demonstration text for Malferma Libro.</p>')],
          _art(root / "atlas-cover.png", cover=True, variant=2))
    library.import_book(atlas)
    return library, record, book


def _pump(GLib, duration=0.1):
    deadline = time.monotonic() + duration
    context = GLib.MainContext.default()
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        time.sleep(0.005)


def _wait(GLib, condition, message, timeout=15):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        _pump(GLib)
    if not condition():
        raise RuntimeError(message)


def _capture(scene: str, output: Path) -> dict:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    gi.require_version("GdkX11", "4.0")
    from gi.repository import Adw, GdkX11, Gio, GLib, Gtk

    if not Gtk.init_check():
        raise RuntimeError("A graphical X11 display is required; use xvfb-run.")
    Adw.init()
    from malferma_libro import __version__
    from malferma_libro.app import ReaderApplication, ReaderWindow

    root = Path(os.environ["XDG_DATA_HOME"]).parent
    library, record, book = _fixture_library(root)
    theme = "dark" if scene.endswith("dark") else "light"
    library.settings.update({"interface_language": "en", "theme": theme,
                             "interface_theme": theme, "auto_hide_header": False})
    library.save()
    application = ReaderApplication()
    application.set_flags(application.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
    application.register(None)
    window = ReaderWindow(application)
    try:
        window.set_default_size(WIDTH, HEIGHT)
        window.present()
        _pump(GLib, 0.3)
        window.show_book(record, book)
        if scene.startswith("library"):
            window.stack.set_visible_child_name("library")
            window.refresh_library()
            def covers_ready():
                visible = [widget for widget in window._cover_targets if widget.get_mapped()]
                return len(visible) >= 4 and all(widget.cover_loaded for widget in visible)

            _wait(GLib, covers_ready, "Visible covers did not finish loading")
        else:
            _wait(GLib, lambda: bool(window._illustration_resident),
                  "The demonstration illustration did not finish loading")
        if window._status_toast is not None:
            window._status_toast.dismiss()
        window.set_focus(None)
        _pump(GLib, 0.7)
        # GTK's X11 client-side decorations can subtract their shadow extents
        # from the default content size. Keep the native allocation intact.
        window_width, window_height = window.get_width(), window.get_height()
        if not (1200 <= window_width <= WIDTH and 800 <= window_height <= HEIGHT):
            raise RuntimeError(f"Unexpected window dimensions: {window_width}×{window_height}")
        xid = GdkX11.X11Surface.get_xid(window.get_surface())
        subprocess.run(["import", "-window", str(xid), "-strip", str(output)],
                       check=True, timeout=30)
        data = output.read_bytes()
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            raise RuntimeError("The native screenshot was not saved as PNG")
        width, height = struct.unpack(">II", data[16:24])
        return {"file": output.name, "scene": scene, "width": width, "height": height,
                "window_width": window_width, "window_height": window_height,
                "sha256": hashlib.sha256(data).hexdigest(),
                "application_version": __version__, "gtk_version": '.'.join(map(str, (
                    Gtk.get_major_version(), Gtk.get_minor_version(), Gtk.get_micro_version()))),
                "libadwaita_version": '.'.join(map(str, (
                    Adw.get_major_version(), Adw.get_minor_version(), Adw.get_micro_version())))}
    finally:
        window.close()
        _pump(GLib, 0.1)
        application.quit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "screenshots",
                        help="Destination directory (default: docs/screenshots)")
    parser.add_argument("--scene", choices=SCENES, help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    sys.path.insert(0, str(ROOT / "src"))
    output = arguments.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if arguments.scene:
        print(json.dumps(_capture(arguments.scene, output / f"{arguments.scene}.png"), ensure_ascii=False))
        return 0
    if shutil.which("import") is None:
        parser.error("ImageMagick's import command is required (Debian package: imagemagick)")
    captures = []
    for scene in SCENES:
        with tempfile.TemporaryDirectory(prefix="malferma-screenshot-") as temporary:
            root = Path(temporary)
            environment = os.environ.copy()
            environment.update({"XDG_DATA_HOME": str(root / "data"),
                                "XDG_CONFIG_HOME": str(root / "config"),
                                "XDG_CACHE_HOME": str(root / "cache"),
                                "XDG_RUNTIME_DIR": str(root / "runtime"),
                                "GDK_BACKEND": "x11", "GDK_SCALE": "1",
                                "GDK_DPI_SCALE": "1", "GSK_RENDERER": "cairo",
                                "GSETTINGS_BACKEND": "memory", "GTK_CSD": "1",
                                "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "LANGUAGE": "en"})
            environment.pop("GTK_THEME", None)
            (root / "runtime").mkdir(mode=0o700)
            result = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()),
                                     "--scene", scene, "--output", str(output)],
                                    env=environment, capture_output=True, text=True, timeout=60)
            if result.returncode:
                sys.stderr.write(result.stdout + result.stderr)
                return result.returncode
            captures.append(json.loads(result.stdout.strip().splitlines()[-1]))
            print(f"Captured {scene}.png", flush=True)
    manifest = {"captured_at": datetime.now(timezone.utc).isoformat(),
                "capture_method": "Unaltered native X11 window captured with ImageMagick import",
                "interface_language": "en", "scale": 1, "screenshots": captures,
                "content": {"poem": "Леся Українка. Надія (1880), original Ukrainian text",
                            "poem_source": POEM_SOURCE,
                            "poem_license": "Public domain (author died in 1913)",
                            "demo_prose_and_artwork": "Original fixtures generated by packaging/screenshots.py",
                            "demo_license": "GPL-3.0-or-later"}}
    (output / "capture-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
