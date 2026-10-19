"""Inline EPUB/FB2 illustrations retain canonical Unicode text and safe bounds.

SPDX-License-Identifier: GPL-3.0-or-later
"""

import base64
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import zlib

from malferma_libro import books
from malferma_libro.books import BookError, load_book
from malferma_libro.tasks import OperationToken, TaskCancelled


def png(width=2, height=3):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    pixels = (b"\0" + b"\x50\x96\xdc" * width) * height
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


# A self-generated 2x3 solid-colour JPEG; no image library is needed by the tests.
JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwc"
    "KDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
    "MjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAADAAIDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcI"
    "CQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRol"
    "JicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ip"
    "qrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAA"
    "AAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLR"
    "ChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaX"
    "mJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEA"
    "PwCzRRRX1R82f//Z")


class InlineBookImagesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def epub(self, body, assets=None, *, extra_chapters=()):
        path = self.root / "illustrated.epub"
        chapters = [("chapter.xhtml", body), *extra_chapters]
        manifest = "".join(f'<item id="c{i}" href="{name}" media-type="application/xhtml+xml"/>'
                           for i, (name, _text) in enumerate(chapters))
        spine = "".join(f'<itemref idref="c{i}"/>' for i in range(len(chapters)))
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>')
            archive.writestr("OPS/book.opf", '<package><metadata><title>Illustrated</title></metadata>'
                             f'<manifest>{manifest}</manifest><spine>{spine}</spine></package>')
            for name, markup in chapters:
                archive.writestr("OPS/" + name, f'<html><body>{markup}</body></html>')
            for name, data in (assets or {}).items():
                archive.writestr(name, data)
        return path

    def fb2(self, body, binaries=None, *, description="", compressed=False):
        payloads = "".join(f'<binary id="{identifier}" content-type="image/png">{data}</binary>'
                           for identifier, data in (binaries or {}).items())
        source = ('<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" '
                  'xmlns:xlink="http://www.w3.org/1999/xlink">'
                  f'<description><title-info><book-title>Illustrated</book-title>{description}</title-info></description>'
                  f'{body}{payloads}</FictionBook>')
        path = self.root / ("illustrated.fb2.zip" if compressed else "illustrated.fb2")
        if compressed:
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("books/illustrated.fb2", source)
        else:
            path.write_text(source, encoding="utf-8")
        return path

    def test_epub_preserves_text_anchors_unicode_and_image_order(self):
        markup = '<p id="start">  שלום 🙂\tУкраїна <img src="images/one.png" alt="Малюнок"/>  مرحبا</p><p id="end">End<img src="images/two.jpg"/></p>'
        baseline = books._html_details(f'<html><body>{markup}</body></html>'.encode(), "OPS/chapter.xhtml")
        chapter = load_book(self.epub(markup, {"OPS/images/one.png": png(), "OPS/images/two.jpg": JPEG})).chapters[0]
        self.assertEqual((chapter.text, chapter.anchors), (baseline.text, baseline.anchors))
        self.assertEqual([image.image.kind for image in chapter.images], ["png", "jpeg"])
        self.assertEqual(chapter.images[0].alt, "Малюнок")
        self.assertEqual(chapter.images[0].offset, chapter.text.index("مرحبا"))
        self.assertEqual(chapter.images[1].offset, len(chapter.text))
        self.assertEqual((chapter.images[1].image.width, chapter.images[1].image.height), (2, 3))

    def test_epub_percent_encoded_relative_paths_and_xml_base(self):
        markup = ('<div xml:base="images/"><img src="%D0%BC%D0%B0%D0%BB%D1%8E%D0%BD%D0%BE%D0%BA.png"/>'
                  '<div xml:base="../other/"><img src="two.png"/></div><img src="first.png"/></div><p>Readable</p>')
        chapter = load_book(self.epub(markup, {"OPS/images/малюнок.png": png(), "OPS/other/two.png": png(3, 2),
                                             "OPS/images/first.png": png(1, 1)})).chapters[0]
        self.assertEqual([image.image.width for image in chapter.images], [2, 3, 1])
        self.assertEqual(chapter.text, "Readable")

    def test_epub_huge_inherited_xml_base_does_not_expand_each_tiny_image_uri(self):
        markup = ('<p id="before">שלום 🙂 Україна</p><div xml:base="' + "a" * (1024 * 1024)
                  + '/">' + '<img src="a"/>' * 2048 + '</div><p id="after">Readable</p>')
        data = f'<html><body>{markup}</body></html>'.encode()
        baseline = books._html_details(data, "OPS/chapter.xhtml")
        # An oversized inherited base is discarded before _reference can create
        # a megabyte-long derived path for every tiny image reference.
        with patch.object(books, "_reference", wraps=books._reference) as resolve:
            content = books._html_details(data, "OPS/chapter.xhtml", image_limit=2048)
        resolve.assert_not_called()
        self.assertEqual(content.images, [])
        self.assertEqual((content.text, content.anchors), (baseline.text, baseline.anchors))

    def test_epub_overlong_image_sources_and_resolved_bases_only_disable_artwork(self):
        limit = books.MAX_IMAGE_REFERENCE_CHARS
        markup = ('<p>Readable</p><img src="' + "a" * (limit + 1) + '"/>'
                  '<div xml:base="' + "b" * (limit - 1) + '/"><img src="one.png"/></div>'
                  '<div xml:base="' + "b" * (limit - 4) + '/"><img src="one.png"/></div>'
                  '<img src="' + "c" * limit + '"/><img src="one.png"/>')
        chapter = load_book(self.epub(markup, {"OPS/one.png": png()})).chapters[0]
        self.assertEqual(chapter.text, "Readable")
        self.assertEqual(len(chapter.images), 1)
        # A long mandatory chapter path also cannot multiply into image paths.
        with patch.object(books, "_reference", wraps=books._reference) as resolve:
            content = books._html_details(b'<p>Readable</p><img src="a"/>', "a" * (limit + 1), image_limit=2048)
        resolve.assert_not_called()
        self.assertEqual(content.text, "Readable")
        self.assertEqual(content.images, [])
        self.assertEqual(books._reference("OPS/book.opf", "a" * (limit + 1)), "OPS/" + "a" * (limit + 1))

    def test_epub_svg_wrappers_extract_rasters_without_exposing_svg_text(self):
        markup = ('<svg xmlns:xlink="http://www.w3.org/1999/xlink"><g xml:base="images/">'
                  '<image xlink:href="one.png"/></g><text>Hidden vector text</text></svg>'
                  '<svg><image href="images/two.jpg"/></svg><p>Readable</p>')
        chapter = load_book(self.epub(markup, {"OPS/images/one.png": png(), "OPS/images/two.jpg": JPEG})).chapters[0]
        self.assertEqual(chapter.text, "Readable")
        self.assertEqual([image.image.kind for image in chapter.images], ["png", "jpeg"])
        self.assertEqual([image.offset for image in chapter.images], [0, 0])

    def test_epub_ignores_unsafe_urls_missing_corrupt_and_vector_assets(self):
        urls = ["https://example.org/p.png", "//example.org/p.png", "file:///etc/passwd", "data:image/png;base64,AAAA",
                "../../outside.png", "%2Fetc/passwd", "images%5Coutside.png", "missing.png", "broken.png", "vector.svg"]
        markup = "<p>Safe</p>" + "".join(f'<img src="{url}"/>' for url in urls)
        markup += '<div xml:base="https://example.org/"><img src="good.png"/></div>'
        with patch("urllib.request.urlopen", side_effect=AssertionError("Books must stay offline")):
            chapter = load_book(self.epub(markup, {"OPS/broken.png": b"not an image", "OPS/vector.svg": b'<svg/>',
                                                   "OPS/good.png": png()})).chapters[0]
        self.assertEqual(chapter.text, "Safe")
        self.assertEqual(chapter.images, [])

    def test_epub_deduplicates_assets_across_paths_and_chapters(self):
        data = png()
        with patch.object(books, "validate_illustration", wraps=books.validate_illustration) as validate:
            book = load_book(self.epub('<p>A<img src="one.png"/><img src="copy.png"/></p>',
                                      {"OPS/one.png": data, "OPS/copy.png": data},
                                      extra_chapters=(("two.xhtml", '<p>B<img src="one.png"/></p>'),)))
        self.assertEqual(validate.call_count, 1)
        images = [image.image for chapter in book.chapters for image in chapter.images]
        self.assertEqual(len(images), 3)
        self.assertTrue(all(image is images[0] for image in images))

    def test_epub_remote_manifest_artwork_is_optional(self):
        path = self.epub('<p>Readable</p><img src="https://example.org/a.png"/>')
        with zipfile.ZipFile(path) as archive:
            contents = {name: archive.read(name) for name in archive.namelist()}
        contents["OPS/book.opf"] = contents["OPS/book.opf"].replace(
            b"</manifest>", b'<item id="remote" href="https://example.org/a.png" media-type="image/png"/></manifest>')
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in contents.items():
                archive.writestr(name, data)
        self.assertEqual(load_book(path).chapters[0].text, "Readable")

    def test_corrupt_duplicate_images_are_validated_only_once(self):
        with patch.object(books, "validate_illustration", wraps=books.validate_illustration) as validate:
            chapter = load_book(self.epub('<p>Readable</p><img src="one.png"/><img src="copy.png"/>',
                                         {"OPS/one.png": b"not an image", "OPS/copy.png": b"not an image"})).chapters[0]
        self.assertEqual(validate.call_count, 1)
        self.assertEqual(chapter.images, [])

    def test_epub_retains_images_after_the_archive_is_removed(self):
        path = self.epub('<p>Text<img src="one.png"/></p>', {"OPS/one.png": png()})
        book = load_book(path)
        path.unlink()
        self.assertEqual(book.chapters[0].images[0].image.data, png())

    def test_image_only_epub_is_readable_but_empty_or_broken_image_only_is_not(self):
        book = load_book(self.epub('<img src="one.png"/>', {"OPS/one.png": png()}))
        self.assertEqual(book.chapters[0].text, "")
        self.assertEqual(book.chapters[0].images[0].offset, 0)
        for markup in ("", '<img src="missing.png"/>'):
            with self.subTest(markup=markup), self.assertRaises(BookError):
                load_book(self.epub(markup))

    def test_epub_cover_only_document_preserves_existing_text_chapter_indices_and_titles(self):
        body = '<p id="start">First 🙂</p>'
        following = '<p id="second">Second</p>'
        old = load_book(self.epub("", extra_chapters=(("body.xhtml", body), ("next.xhtml", following))))
        book = load_book(self.epub('<img src="cover.png"/>', {"OPS/cover.png": png()},
                                  extra_chapters=(("body.xhtml", body), ("next.xhtml", following))))
        self.assertEqual([(chapter.title, chapter.text) for chapter in book.chapters],
                         [(chapter.title, chapter.text) for chapter in old.chapters])
        self.assertEqual(len(book.chapters), 2)
        self.assertEqual(book.chapters[0].anchors["start"], old.chapters[0].anchors["start"])
        self.assertEqual(book.chapters[1].anchors["second"], old.chapters[1].anchors["second"])
        self.assertEqual(book.chapters[0].images[0].offset, 0)
        self.assertEqual([entry.chapter for entry in book.outline], [0, 0, 1])

    def test_epub_interstitial_and_trailing_images_keep_source_order_and_outline_offsets(self):
        assets = {f"OPS/{width}.png": png(width, 1) for width in range(1, 8)}
        book = load_book(self.epub('<img src="1.png"/>', assets, extra_chapters=(
            ("first.xhtml", '<p>A<img src="2.png"/></p>'),
            ("between.xhtml", '<img src="3.png"/>'),
            ("second.xhtml", '<img src="4.png"/><p>B</p><img src="7.png"/>'),
            ("tail1.xhtml", '<img src="5.png"/>'),
            ("tail2.xhtml", '<img src="6.png"/>'),
        )))
        self.assertEqual([chapter.text for chapter in book.chapters], ["A", "B"])
        self.assertEqual([image.image.width for image in book.chapters[0].images], [1, 2])
        self.assertEqual([image.offset for image in book.chapters[0].images], [0, 1])
        self.assertEqual([image.image.width for image in book.chapters[1].images], [3, 4, 7, 5, 6])
        self.assertEqual([image.offset for image in book.chapters[1].images], [0, 0, 1, 1, 1])
        self.assertEqual([entry.chapter for entry in book.outline], [0, 0, 1, 1, 1, 1])
        self.assertEqual([entry.offset for entry in book.outline], [0, 0, 0, 0, 1, 1])

    def test_image_only_epub_keeps_separate_reading_documents(self):
        book = load_book(self.epub('<img src="one.png"/>', {"OPS/one.png": png()},
                                  extra_chapters=(("second.xhtml", '<img src="one.png"/>'),)))
        self.assertEqual([chapter.text for chapter in book.chapters], ["", ""])
        self.assertEqual([len(chapter.images) for chapter in book.chapters], [1, 1])
        self.assertEqual([entry.chapter for entry in book.outline], [0, 1])

    def test_book_wide_reference_unique_and_bytes_limits_preserve_text(self):
        markup = '<p>Readable</p><img src="one.png"/><img src="two.png"/><img src="one.png"/>'
        assets = {"OPS/one.png": png(), "OPS/two.png": png(3, 2)}
        for setting, maximum, expected in (("MAX_IMAGE_REFERENCES", 2, 2), ("MAX_ILLUSTRATIONS", 1, 2),
                                           ("MAX_ILLUSTRATION_TOTAL", len(png()), 2),
                                           ("MAX_ILLUSTRATION_BYTES", len(png()) - 1, 0)):
            with self.subTest(setting=setting), patch.object(books, setting, maximum):
                chapter = load_book(self.epub(markup, assets)).chapters[0]
                self.assertEqual(chapter.text, "Readable")
                self.assertEqual(len(chapter.images), expected)

    def test_fb2_preserves_text_and_places_each_image_in_its_section_or_notes(self):
        body = ('<body><section id="main"><title><p>Main</p></title><p>שלום 🙂 <image xlink:href="#one"/> Україна</p>'
                '<section id="nested"><title><p>Nested</p></title><p>Nested text<image xlink:href="#two"/></p></section>'
                '</section></body><body name="notes"><section id="note"><title><p>Note</p></title>'
                '<p>Note text<image xlink:href="#one"/></p></section></body>')
        binaries = {"one": base64.b64encode(png()).decode(), "two": base64.b64encode(JPEG).decode()}
        with patch.object(books, "validate_illustration", wraps=books.validate_illustration) as validate:
            book = load_book(self.fb2(body, binaries))
        self.assertEqual(validate.call_count, 2)
        self.assertEqual([chapter.kind for chapter in book.chapters], ["chapter", "chapter", "notes"])
        self.assertEqual([image.image.kind for chapter in book.chapters for image in chapter.images], ["png", "jpeg", "png"])
        self.assertEqual(book.chapters[0].text, "שלום 🙂 Україна")
        self.assertEqual(book.chapters[0].images[0].offset, book.chapters[0].text.index("Україна"))
        self.assertEqual(book.chapters[1].text, "Nested text")
        self.assertEqual(book.chapters[1].images[0].offset, len("Nested text"))
        self.assertEqual(book.chapters[2].anchors["note"], 0)

    def test_fb2_whitespace_base64_and_compressed_book(self):
        encoded = base64.b64encode(png()).decode()
        payload = "\n  ".join(encoded[index:index + 12] for index in range(0, len(encoded), 12))
        book = load_book(self.fb2('<body><section><p>A<image xlink:href="#one"/>B</p></section></body>',
                                  {"one": payload}, compressed=True))
        self.assertEqual(book.chapters[0].text, "AB")
        self.assertEqual(book.chapters[0].images[0].offset, 1)

    def test_fb2_ambiguous_binary_ids_are_ignored(self):
        path = self.fb2('<body><section><p>Readable<image xlink:href="#one"/></p></section></body>',
                        {"one": base64.b64encode(png()).decode()})
        source = path.read_text()
        source = source.replace("</FictionBook>", '<binary id="one">AAAA</binary></FictionBook>')
        path.write_text(source)
        chapter = load_book(path).chapters[0]
        self.assertEqual(chapter.text, "Readable")
        self.assertEqual(chapter.images, [])

    def test_fb2_invalid_or_external_images_do_not_break_the_text(self):
        for href, payload in (("#one", "!!!"), ("#one", "AAAA"), ("#one", "éééé"), ("#missing", "AAAA"),
                              ("https://example.org/p.png", "AAAA"), ("file:///etc/passwd", "AAAA")):
            with self.subTest(href=href, payload=payload):
                book = load_book(self.fb2(f'<body><section><p>Readable<image xlink:href="{href}"/></p></section></body>',
                                          {"one": payload}))
                self.assertEqual(book.chapters[0].text, "Readable")
                self.assertEqual(book.chapters[0].images, [])

    def test_fb2_description_cover_does_not_become_an_inline_image(self):
        book = load_book(self.fb2('<body><section><p>Readable</p></section></body>',
                                  {"one": base64.b64encode(png()).decode()},
                                  description='<coverpage><image xlink:href="#one"/></coverpage>'))
        self.assertEqual(book.chapters[0].images, [])
        self.assertIsNotNone(book.cover)

    def test_fb2_image_only_parent_and_nested_sections_keep_ownership(self):
        body = ('<body><section id="parent"><image xlink:href="#one"/><section id="child">'
                '<p>Child</p></section></section></body>')
        book = load_book(self.fb2(body, {"one": base64.b64encode(png()).decode()}))
        self.assertEqual([chapter.text for chapter in book.chapters], ["Child"])
        self.assertEqual([len(chapter.images) for chapter in book.chapters], [1])
        self.assertEqual(book.chapters[0].images[0].offset, 0)
        self.assertEqual([entry.chapter for entry in book.outline], [0, 0])

    def test_fb2_image_only_sections_and_notes_preserve_old_chapter_titles_and_indices(self):
        body = ('<body><section id="parent"><image xlink:href="#one"/><section id="child">'
                '<p>First</p><image xlink:href="#two"/></section></section>'
                '<section id="between"><image xlink:href="#three"/></section>'
                '<section id="second"><p>Second</p><image xlink:href="#four"/></section>'
                '<section id="tail"><image xlink:href="#five"/></section></body>'
                '<body name="notes"><image xlink:href="#six"/></body>'
                '<body name="notes"><section id="note"><p>Note</p><image xlink:href="#seven"/></section></body>')
        names = ("one", "two", "three", "four", "five", "six", "seven")
        binaries = {name: base64.b64encode(png(width, 1)).decode() for width, name in enumerate(names, 1)}
        old = load_book(self.fb2(body, {}))
        book = load_book(self.fb2(body, binaries))
        self.assertEqual([(chapter.title, chapter.text) for chapter in book.chapters],
                         [(chapter.title, chapter.text) for chapter in old.chapters])
        self.assertEqual([chapter.kind for chapter in book.chapters], ["chapter", "chapter", "notes"])
        self.assertEqual([image.image.width for image in book.chapters[0].images], [1, 2])
        self.assertEqual([image.image.width for image in book.chapters[1].images], [3, 4])
        self.assertEqual([image.image.width for image in book.chapters[2].images], [5, 6, 7])
        self.assertEqual([image.offset for image in book.chapters[2].images], [0, 0, len("Note")])
        self.assertEqual(book.chapters[0].anchors["parent"], old.chapters[0].anchors["parent"])
        self.assertTrue(all(0 <= entry.chapter < 3 for entry in book.outline))

    def test_fb2_trailing_image_only_notes_append_after_the_last_text(self):
        body = ('<body><section><p>Readable</p><image xlink:href="#one"/></section></body>'
                '<body name="notes"><section id="tail"><image xlink:href="#two"/></section></body>')
        book = load_book(self.fb2(body, {"one": base64.b64encode(png(1, 1)).decode(),
                                       "two": base64.b64encode(png(2, 1)).decode()}))
        self.assertEqual([chapter.text for chapter in book.chapters], ["Readable"])
        self.assertEqual([image.image.width for image in book.chapters[0].images], [1, 2])
        self.assertEqual([image.offset for image in book.chapters[0].images], [len("Readable"), len("Readable")])
        self.assertEqual(book.outline[-1].chapter, 0)
        self.assertEqual(book.outline[-1].offset, len("Readable"))

    def test_image_only_fb2_keeps_separate_sections(self):
        body = '<body><section><image xlink:href="#one"/></section><section><image xlink:href="#one"/></section></body>'
        book = load_book(self.fb2(body, {"one": base64.b64encode(png()).decode()}))
        self.assertEqual([chapter.text for chapter in book.chapters], ["", ""])
        self.assertEqual([len(chapter.images) for chapter in book.chapters], [1, 1])

    def test_fb2_empty_or_missing_image_only_book_is_rejected(self):
        for body in ("<body/>", '<body><section><image xlink:href="#missing"/></section></body>'):
            with self.subTest(body=body), self.assertRaises(BookError):
                load_book(self.fb2(body))

    def test_fb2_oversized_binary_is_skipped_before_validation(self):
        body = '<body><section><p>Readable<image xlink:href="#one"/></p></section></body>'
        with patch.object(books, "MAX_ILLUSTRATION_BYTES", 8), patch.object(books, "validate_illustration") as validate:
            chapter = load_book(self.fb2(body, {"one": base64.b64encode(png()).decode()})).chapters[0]
        validate.assert_not_called()
        self.assertEqual(chapter.text, "Readable")
        self.assertEqual(chapter.images, [])

    def test_cancellation_between_illustrations_is_not_hidden_as_bad_artwork(self):
        token = OperationToken()
        def cancel_after_validate(data):
            image = original(data)
            token.cancel()
            return image
        original = books.validate_illustration
        with patch.object(books, "validate_illustration", side_effect=cancel_after_validate), self.assertRaises(TaskCancelled):
            load_book(self.epub('<p>A<img src="one.png"/></p>', {"OPS/one.png": png()}), cancel=token)


if __name__ == "__main__":
    unittest.main()
