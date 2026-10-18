"""HTML/CommonMark, real raster comics and Poppler integration fixtures.

SPDX-License-Identifier: GPL-3.0-or-later
"""

from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import zlib

from malferma_libro.books import BookError, load_book


def png(width, height):
    """Small valid RGB PNG built with the standard library, no fixture binary."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    pixels = (b"\0" + b"\xff\xcc\x80" * width) * height
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")


def write_pdf(path):
    """Two readable PDF pages, with proper object offsets and no external tools."""
    streams = [b"BT /F1 12 Tf 20 80 Td (First page) Tj ET", b"BT /F1 12 Tf 20 80 Td (Second page) Tj ET"]
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Resources << /Font << /F1 7 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Resources << /Font << /F1 7 0 R >> >> /Contents 6 0 R >>",
        b"<< /Length " + str(len(streams[0])).encode() + b" >>\nstream\n" + streams[0] + b"\nendstream",
        b"<< /Length " + str(len(streams[1])).encode() + b" >>\nstream\n" + streams[1] + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Title (Between the Lines) /Author (Test Author) >>",
    ]
    data, offsets = bytearray(b"%PDF-1.4\n"), [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R /Info 8 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    path.write_bytes(data)
    return path


class LocalMarkupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def load(self, name, data):
        path = self.root / name
        path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
        return load_book(path)

    def test_html_metadata_headings_anchors_and_inert_content(self):
        html = '''<!DOCTYPE html><html><head><title>Між рядків</title><meta name="author" content="Леся Українка"/><script>secretScript</script></head><body><h1 id="poem">Надія</h1><p>Гетьте, думи! 🙂</p><h2 id="second">Друга строфа</h2><p>שלום مرحبًا</p><style>secretStyle</style><iframe src="file:///etc/passwd">secretFrame</iframe><img src="https://example.org/private.png"/></body></html>'''
        with patch("urllib.request.urlopen", side_effect=AssertionError("Book loading must be offline")):
            book = self.load("poem.html", html)
        self.assertEqual((book.title, book.author, book.format), ("Між рядків", "Леся Українка", "HTML"))
        text = book.chapters[0].text
        self.assertIn("שלום مرحبًا", text)
        for hidden in ("secretScript", "secretStyle", "secretFrame", "/etc/passwd"):
            self.assertNotIn(hidden, text)
        self.assertEqual([entry.title for entry in book.outline], ["Надія", "Друга строфа"])
        self.assertTrue(text[book.outline[1].offset:].startswith("Друга строфа"))
        self.assertEqual(book.chapters[0].anchors["second"], book.outline[1].offset)

    def test_html_declared_legacy_charset(self):
        html = '<html><head><meta charset="windows-1251"></head><body><h1>Поезія</h1><p>Щастя</p></body></html>'
        book = self.load("legacy.htm", html.encode("cp1251"))
        self.assertIn("Щастя", book.chapters[0].text)

    def test_html_preformatted_text_keeps_indentation(self):
        book = self.load("code.xhtml", '<html><body><h1>Code</h1><pre>  first\n    second</pre></body></html>')
        self.assertIn("  first\n    second", book.chapters[0].text)

    def test_html_valueless_aria_attribute_is_inert_and_does_not_crash(self):
        book = self.load("aria.html", '<h1>Title</h1><p aria-hidden>Visible text</p><p aria-hidden="true">Hidden text</p><p aria-hidden="false">שלום مرحبًا</p>')
        self.assertIn("Visible text", book.chapters[0].text)
        self.assertIn("שלום مرحبًا", book.chapters[0].text)
        self.assertNotIn("Hidden text", book.chapters[0].text)

    def test_html_rejects_internal_entities_binary_and_nontext_charset(self):
        for data in ('<!DOCTYPE html [<!ENTITY x "boom">]><html><body>&x;</body></html>', b"<p>binary\0data</p>", '<meta charset="base64_codec"><p>SGVsbG8=</p>'):
            with self.subTest(data=data), self.assertRaises(BookError):
                self.load("bad.html", data)

    def test_markdown_reading_has_outline_and_code_preserves_whitespace(self):
        book = self.load("poem.md", "# Надія\n\n**Гетьте, думи!** 🙂\n\n## Друга строфа\n\n[Вірш](https://example.org)\n\n```text\n  line one\n    line two\n```\n")
        self.assertEqual(book.format, "Markdown")
        self.assertEqual(book.title, "Надія")
        self.assertEqual([entry.title for entry in book.outline], ["Надія", "Друга строфа"])
        self.assertIn("Гетьте, думи!", book.chapters[0].text)
        self.assertIn("  line one\n    line two", book.chapters[0].text)

    def test_markdown_html_is_literal_text_and_never_executed(self):
        book = self.load("literal.markdown", "# Example\n\n<script>alert('inert')</script>\n\n![Picture](https://example.org/a.png)\n")
        self.assertIn("<script>alert('inert')</script>", book.chapters[0].text)


class ComicTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def make_comic(self, *, extra=()):
        path = self.root / "comic.cbz"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("pages/page10.png", png(30, 40))
            archive.writestr("pages/page2.png", png(20, 25))
            archive.writestr("ComicInfo.xml", "<ComicInfo><Title>Малюнки</Title><Writer>Автор</Writer></ComicInfo>")
            archive.writestr("__MACOSX/ignored.png", png(1, 1))
            for name, data in extra:
                archive.writestr(name, data)
        return path

    def test_comic_metadata_natural_page_order_and_physical_pages(self):
        book = load_book(self.make_comic())
        self.assertEqual((book.title, book.author, book.format), ("Малюнки", "Автор", "CBZ"))
        self.assertEqual(len(book.chapters), 2)
        self.assertEqual(book.page_document.page_size(0), (20, 25))
        self.assertEqual(book.page_document.page_size(1), (30, 40))
        self.assertEqual(book.page_document.page_text(0), "")
        self.assertEqual([entry.kind for entry in book.outline], ["page", "page"])

    def test_comic_render_outputs_valid_png_and_cannot_replace_book(self):
        path = self.make_comic()
        book = load_book(path)
        output = self.root / "render.png"
        try:
            import gi
            gi.require_version("GdkPixbuf", "2.0")
        except (ImportError, ValueError):
            self.skipTest("GdkPixbuf is not installed; native image decoding was not tested")
        book.page_document.render_page(0, output, fit_width=80)
        header = output.read_bytes()[:24]
        self.assertEqual(header[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", header[16:24]), (80, 100))
        before = path.read_bytes()
        from malferma_libro.cbz import CbzError
        with self.assertRaises(CbzError):
            book.page_document.render_page(0, path)
        self.assertEqual(path.read_bytes(), before)

    def test_comic_rejects_archive_paths_and_empty_archive(self):
        for name in ("../escape.png", "/absolute.png", "pages\\escape.png", "C:/escape.png"):
            with self.subTest(name=name), self.assertRaises(BookError):
                load_book(self.make_comic(extra=((name, png(1, 1)),)))
        empty = self.root / "empty.cbz"
        with zipfile.ZipFile(empty, "w") as archive:
            archive.writestr("readme.txt", "No pages")
        with self.assertRaises(BookError):
            load_book(empty)

    def test_comic_bad_page_is_reported_when_visited(self):
        from malferma_libro.cbz import CbzError
        book = load_book(self.make_comic(extra=(("pages/page3.png", b"not an image"),)))
        self.assertEqual(len(book.chapters), 3)
        with self.assertRaises(CbzError):
            book.page_document.page_size(1)


@unittest.skipUnless(all(shutil.which(name) for name in ("pdfinfo", "pdftotext", "pdftoppm")), "Real Poppler utilities are not installed")
class PopplerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = write_pdf(self.root / "book.pdf")

    def test_pdf_real_metadata_page_count_and_text(self):
        book = load_book(self.path)
        self.assertEqual((book.title, book.author, book.format), ("Between the Lines", "Test Author", "PDF"))
        self.assertEqual(len(book.chapters), 2)
        self.assertEqual(book.page_document.page_size(0), (200, 100))
        self.assertIn("First page", book.page_document.page_text(0))
        self.assertIn("Second page", book.page_document.page_text(1))

    def test_pdf_real_render_and_source_protection(self):
        from malferma_libro.pdf import PdfError
        document = load_book(self.path).page_document
        output = document.render_page(1, self.root / "page.png", fit_width=400)
        header = output.read_bytes()[:24]
        self.assertEqual(header[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", header[16:24]), (400, 200))
        before = self.path.read_bytes()
        with self.assertRaises(PdfError):
            document.render_page(0, self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_pdf_is_a_book_error(self):
        self.path.write_bytes(b"not PDF")
        with self.assertRaises(BookError):
            load_book(self.path)


if __name__ == "__main__":
    unittest.main()
