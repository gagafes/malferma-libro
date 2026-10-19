"""Hostile ebook input must be bounded before expensive allocations/decoding.

SPDX-License-Identifier: GPL-3.0-or-later
"""

from pathlib import Path
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

from malferma_libro import books, cbz, covers, opds


class ParserSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def archive(self, entries=3, compression=zipfile.ZIP_STORED):
        path = self.root / "hostile.epub"
        with zipfile.ZipFile(path, "w", compression=compression) as archive:
            for index in range(entries):
                archive.writestr(f"chapter{index}.xhtml", "<p>Readable text</p>")
        return path

    def test_entry_limit_is_checked_before_zipinfo_allocation(self):
        path = self.archive()
        with patch.object(books, "MAX_ZIP_ENTRIES", 2), patch.object(
            books.zipfile, "ZipFile", side_effect=AssertionError("ZipInfo allocation")
        ) as constructor, self.assertRaises(books.BookError):
            books.load_book(path)
        constructor.assert_not_called()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "Requires POSIX named pipes")
    def test_archive_pipe_is_rejected_without_waiting_for_a_writer(self):
        path = self.root / "pipe.epub"
        os.mkfifo(path)
        code = """from pathlib import Path
import sys
from malferma_libro.books import BookError, _Archive
try:
    _Archive(Path(sys.argv[1]))
except BookError:
    pass
else:
    raise AssertionError('A pipe was accepted as an archive')
"""
        subprocess.run([sys.executable, "-c", code, str(path)], check=True, timeout=3,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "Requires POSIX named pipes")
    def test_text_file_swapped_for_a_pipe_is_rejected_at_open(self):
        path = self.root / "pipe.txt"
        os.mkfifo(path)
        code = """from pathlib import Path
import sys
from unittest.mock import patch
from malferma_libro.books import BookError, load_book
# Simulate the earlier path check seeing the original regular file.
with patch.object(Path, 'is_file', return_value=True):
    try:
        load_book(Path(sys.argv[1]))
    except BookError:
        pass
    else:
        raise AssertionError('A pipe was accepted as a text file')
"""
        subprocess.run([sys.executable, "-c", code, str(path)], check=True, timeout=3,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def test_existing_symbolic_links_to_regular_books_remain_supported(self):
        target = self.root / "original.txt"
        target.write_text("Readable text", encoding="utf-8")
        link = self.root / "linked.txt"
        link.symlink_to(target)
        self.assertEqual(books.load_book(link).chapters[0].text, "Readable text")
        target = self.archive()
        link = self.root / "linked.epub"
        link.symlink_to(target)
        archive = books._Archive(link)
        try:
            self.assertEqual(archive.read("chapter0.xhtml"), b"<p>Readable text</p>")
        finally:
            archive.close()

    def test_directory_byte_limit_is_checked_before_zipinfo_allocation(self):
        path = self.archive()
        with patch.object(books, "MAX_ZIP_DIRECTORY_BYTES", 64), patch.object(
            books.zipfile, "ZipFile", side_effect=AssertionError("ZipInfo allocation")
        ) as constructor, self.assertRaises(books.BookError):
            books.load_book(path)
        constructor.assert_not_called()

    def test_forged_directory_count_is_rejected_before_zipinfo_allocation(self):
        path = self.archive()
        data = bytearray(path.read_bytes())
        end = data.rfind(b"PK\x05\x06")
        struct.pack_into("<HH", data, end + 8, 1, 1)
        path.write_bytes(data)
        with patch.object(books.zipfile, "ZipFile", side_effect=AssertionError("ZipInfo allocation")) as constructor:
            with self.assertRaises(books.BookError):
                books.load_book(path)
        constructor.assert_not_called()

    def test_memory_hungry_zip_compression_is_rejected_before_decoding(self):
        for compression in (zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA):
            path = self.archive(compression=compression)
            with self.subTest(compression=compression), patch.object(
                zipfile, "_get_decompressor", side_effect=AssertionError("Decoder allocation")
            ) as decoder, self.assertRaises(books.BookError):
                books.load_book(path)
            decoder.assert_not_called()

    def test_wide_html_element_limit_is_enforced(self):
        with patch.object(books, "MAX_XML_NODES", 8), self.assertRaises(books.BookError):
            books._html(b"<body>" + b"<p>text</p>" * 8 + b"</body>", "chapter.xhtml")
        text, _heading = books._html(b"<p>Still readable</p>", "chapter.xhtml")
        self.assertEqual(text, "Still readable")

    def test_entity_declarations_are_rejected_before_parsing_in_all_xml_callers(self):
        for encoding in ("utf-8", "utf-16", "utf-32"):
            for prefix in ("", "<!-- <!DOCTYPE ignored -->"):
                source = (prefix + '<!DOCTYPE FictionBook [<!ENTITY secret "expanded">]>'
                          '<FictionBook><body><p>&secret;</p></body></FictionBook>').encode(encoding)
                with self.subTest(encoding=encoding, prefix=prefix):
                    with patch.object(books, "parse_xml", side_effect=AssertionError("Unsafe XML parser input")) as parse:
                        with self.assertRaises(books.BookError):
                            books._xml(source, "hostile.fb2")
                    parse.assert_not_called()
                    with patch.object(opds, "parse_xml", side_effect=AssertionError("Unsafe XML parser input")) as parse:
                        with self.assertRaises(opds.OPDSError):
                            opds.parse_catalog(source, "https://example.org/feed")
                    parse.assert_not_called()
                    with patch.object(cbz, "parse_xml", side_effect=AssertionError("Unsafe XML parser input")) as parse:
                        self.assertEqual(cbz._metadata(source), ("", ""))
                    parse.assert_not_called()

    def test_xml_declaration_literals_in_comments_and_cdata_remain_text(self):
        source = ('<!-- <!DOCTYPE ignored [<!ENTITY harmless "literal">] -->'
                  '<FictionBook><body><p><![CDATA[<!ENTITY ordinary "book text">]]></p></body></FictionBook>')
        path = self.root / "literal.fb2"
        path.write_text(source, encoding="utf-8")
        self.assertEqual(books.load_book(path).chapters[0].text, '<!ENTITY ordinary "book text">')
        path.write_bytes('<FictionBook><body><p>Українська</p></body></FictionBook>'.encode("utf-16"))
        self.assertEqual(books.load_book(path).chapters[0].text, "Українська")

    def test_legacy_epub_external_doctype_does_not_open_a_connection(self):
        source = b'<!DOCTYPE html SYSTEM "https://example.invalid/private.dtd"><html><p>Readable</p></html>'
        with patch("socket.create_connection", side_effect=AssertionError("External DTD request")), patch(
            "urllib.request.urlopen", side_effect=AssertionError("External DTD request")
        ):
            root = books._xml(source, "navigation.xhtml", allow_doctype=True)
        self.assertEqual(root.find("p").text, "Readable")

    def test_cover_reference_limit_precedes_uri_processing(self):
        with patch.object(covers, "MAX_COVER_REFERENCE_CHARS", 32), patch.object(
            covers, "urlsplit", side_effect=AssertionError("Oversized URI processing")
        ) as parse:
            for base, href in (("x" * 33, "image.png"), ("", "x" * 33)):
                with self.subTest(base=base, href=href), self.assertRaises(ValueError):
                    covers._resolve(base, href)
        parse.assert_not_called()

    def test_nested_cover_bases_stop_at_the_reference_budget(self):
        root = ET.fromstring('<package xml:base="1234567890/"><manifest xml:base="1234567890/">'
                             '<item xml:base="1234567890/"/><item href="cover.png"/>'
                             '</manifest></package>')
        with patch.object(covers, "MAX_COVER_REFERENCE_CHARS", 32):
            nodes = list(covers._walk_bases(root, ""))
        self.assertEqual([node.tag for node, _base in nodes], ["package", "manifest", "item"])
        self.assertTrue(all(len(base) <= 32 for _node, base in nodes))

    def test_cover_attempt_budget_is_shared_by_guide_and_wrapper_images(self):
        package = ET.fromstring('<package><guide>' + ''.join(
            f'<reference type="cover" href="cover{index}.xhtml"/>' for index in range(8)
        ) + '</guide></package>')
        wrapper = ('<html><body>' + ''.join(f'<img src="image{index}.png"/>' for index in range(8))
                   + '</body></html>').encode()
        with patch.object(covers, "MAX_COVER_CANDIDATES", 4), patch.object(
            covers, "_archive_cover", return_value=None
        ) as image, patch.object(covers, "_archive_read", return_value=wrapper) as metadata:
            self.assertIsNone(covers.epub_cover(object(), package, ""))
        self.assertEqual(image.call_count, 4)
        self.assertEqual(metadata.call_count, 1)

    def test_repeated_guide_paths_are_not_processed_repeatedly(self):
        package = ET.fromstring('<package><guide>' + '<reference type="cover" href="cover.xhtml"/>' * 32
                                + '</guide></package>')
        with patch.object(covers, "_archive_cover", return_value=None) as image, patch.object(
            covers, "_archive_read", return_value=b"<html><body>No artwork</body></html>"
        ) as metadata:
            self.assertIsNone(covers.epub_cover(object(), package, ""))
        self.assertEqual(image.call_count, 1)
        self.assertEqual(metadata.call_count, 1)

    def test_fb2_cover_candidates_have_a_small_attempt_budget(self):
        root = ET.fromstring('<FictionBook><description><title-info><coverpage>'
                             + '<image href="#cover"/>' * 32
                             + '</coverpage></title-info></description><binary id="cover">AA==</binary></FictionBook>')
        with patch.object(covers, "MAX_COVER_CANDIDATES", 4), patch.object(
            covers, "validate_cover", return_value=None
        ) as validate:
            self.assertIsNone(covers.fb2_cover(root))
        self.assertEqual(validate.call_count, 4)


if __name__ == "__main__":
    unittest.main()
