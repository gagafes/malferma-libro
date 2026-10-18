"""Real ebook fixtures and hostile-input regressions.

SPDX-License-Identifier: GPL-3.0-or-later
"""

from pathlib import Path
import stat
import tempfile
import unittest
import warnings
import zipfile

from malferma_libro.books import BookError, load_book


FB2 = '''<?xml version="1.0" encoding="UTF-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
 <description><title-info><book-title>Contra spem spero!</book-title>
 <author><first-name>Леся</first-name><last-name>Українка</last-name></author>
 </title-info></description>
 <body><section id="poem"><title><p>Надія</p></title>
 <p>Гетьте, думи, ви хмари осінні!</p>
 <section id="second"><title><p>Друга строфа</p></title><p>Так! я буду крізь сльози сміятись.</p></section>
 </section></body>
 <body name="notes"><section id="n1"><title><p>1</p></title><p>Примітка автора.</p></section></body>
</FictionBook>'''


def write_epub(path, *, chapter_href="chapter.xhtml", extra=(), overrides=None):
    """Create a small EPUB 3 with nested navigation and notes in reading order."""
    files = {
        "mimetype": "application/epub+zip",
        "META-INF/container.xml": '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>',
        "OPS/book.opf": f'''<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
        <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Між рядків</dc:title><dc:creator>Леся Українка</dc:creator></metadata>
        <manifest><item id="main" href="{chapter_href}" media-type="application/xhtml+xml"/>
        <item id="notes" href="notes.xhtml" media-type="application/xhtml+xml"/>
        <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/></manifest>
        <spine><itemref idref="main"/><itemref idref="notes"/></spine></package>''',
        "OPS/chapter.xhtml": '''<!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml"><head><title>Hidden</title><script>discardMe()</script></head><body><h1 id="start">Надія</h1><p>Гетьте, думи!</p><h2 id="next">Наступна строфа</h2><p>שלום مرحبًا 🙂</p></body></html>''',
        "OPS/notes.xhtml": '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body epub:type="endnotes"><h1>Примечания</h1><p id="n1">Точне пояснення.</p></body></html>',
        "OPS/nav.xhtml": '''<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body><nav epub:type="toc"><ol><li><a href="chapter.xhtml#start">Поезія</a><ol><li><a href="chapter.xhtml#next">Строфа</a></li></ol></li><li epub:type="endnotes"><a href="notes.xhtml#n1">Пояснення</a></li></ol></nav></body></html>''',
    }
    files.update(overrides or {})
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in files.items():
            archive.writestr(name, value)
        for name, value in extra:
            archive.writestr(name, value)
    return path


class BookLoadingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write(self, name, data):
        path = self.root / name
        path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
        return path

    def test_utf8_book_keeps_multilingual_text(self):
        book = load_book(self.write("Поезія.txt", "\ufeff  Українська  мова\n\nשלום مرحبًا Ĝojo 🙂  "))
        self.assertEqual((book.title, book.format), ("Поезія", "TXT"))
        self.assertEqual(book.chapters[0].text, "Українська мова\n\nשלום مرحبًا Ĝojo 🙂")

    def test_windows_1251_is_supported(self):
        text = "Ще не вмерла України і слава, і воля"
        book = load_book(self.write("старе.txt", text.encode("cp1251")))
        self.assertEqual(book.chapters[0].text, text)

    def test_binary_and_empty_text_are_rejected(self):
        for data in (b"hello\x00world", b" \n\t "):
            with self.subTest(data=data), self.assertRaises(BookError):
                load_book(self.write("bad.txt", data))

    def test_missing_unsupported_and_directory_paths_are_rejected(self):
        for path in (self.root / "missing.txt", self.root, self.write("book.exe", b"MZ")):
            with self.subTest(path=path), self.assertRaises(BookError):
                load_book(path)

    def test_fb2_metadata_nested_sections_and_notes(self):
        book = load_book(self.write("poem.fb2", FB2))
        self.assertEqual((book.title, book.author, book.format), ("Contra spem spero!", "Леся Українка", "FB2"))
        self.assertEqual([chapter.kind for chapter in book.chapters], ["chapter", "chapter", "notes"])
        self.assertIn("Гетьте, думи", book.chapters[0].text)
        self.assertNotIn("Так!", book.chapters[0].text)
        self.assertIn("Так!", book.chapters[1].text)
        self.assertGreater(book.outline[1].level, book.outline[0].level)
        self.assertEqual(book.outline[-1].kind, "notes")
        self.assertIn("n1", book.chapters[-1].anchors)

    def test_compressed_fb2_loads_without_extracting_files(self):
        path = self.root / "poem.fb2.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("books/poem.fb2", FB2)
        self.assertEqual(load_book(path).author, "Леся Українка")
        self.assertEqual(sorted(item.name for item in self.root.iterdir()), ["poem.fb2.zip"])

    def test_compressed_fb2_requires_exactly_one_book(self):
        path = self.root / "bad.fb2.zip"
        for names in (("readme.txt",), ("first.fb2", "second.fb2")):
            with zipfile.ZipFile(path, "w") as archive:
                for name in names:
                    archive.writestr(name, FB2)
            with self.subTest(names=names), self.assertRaises(BookError):
                load_book(path)

    def test_fb2_rejects_wrong_root_and_entity_expansion(self):
        for xml in ('<document><p>Text</p></document>', '<!DOCTYPE FictionBook [<!ENTITY x "expanded">]><FictionBook><body><p>&x;</p></body></FictionBook>'):
            with self.subTest(xml=xml), self.assertRaises(BookError):
                load_book(self.write("unsafe.fb2", xml))

    def test_epub_reads_spine_and_resolves_navigation_anchors(self):
        book = load_book(write_epub(self.root / "poem.epub"))
        self.assertEqual((book.title, book.author, book.format), ("Між рядків", "Леся Українка", "EPUB"))
        self.assertEqual(len(book.chapters), 2)
        self.assertEqual([entry.title for entry in book.outline], ["Поезія", "Строфа", "Пояснення"])
        entry = book.outline[1]
        self.assertEqual((entry.chapter, entry.level), (0, 1))
        self.assertTrue(book.chapters[0].text[entry.offset:].startswith("Наступна строфа"))
        self.assertEqual(book.chapters[-1].kind, "notes")
        self.assertNotIn("discardMe", book.chapters[0].text)
        self.assertIn("שלום مرحبًا 🙂", book.chapters[0].text)

    def test_epub3_navigation_does_not_read_unused_broken_ncx(self):
        # Old export tools may leave a stale compatibility NCX beside the
        # authoritative EPUB 3 TOC. It must not stop a readable book opening.
        for legacy in (b"<ncx>", None):
            with self.subTest(legacy=legacy):
                path = write_epub(self.root / "legacy.epub")
                with zipfile.ZipFile(path) as archive:
                    package = archive.read("OPS/book.opf").decode("utf-8")
                package = package.replace("</manifest>", '<item id="ncx" href="legacy.ncx" media-type="application/x-dtbncx+xml"/></manifest>')
                package = package.replace("<spine>", '<spine toc="ncx">')
                extra = (("OPS/legacy.ncx", legacy),) if legacy is not None else ()
                book = load_book(write_epub(path, overrides={"OPS/book.opf": package}, extra=extra))
                self.assertEqual([entry.title for entry in book.outline], ["Поезія", "Строфа", "Пояснення"])

    def test_epub_ncx_remains_a_fallback_without_epub3_navigation(self):
        path = write_epub(self.root / "epub2.epub")
        with zipfile.ZipFile(path) as archive:
            package = archive.read("OPS/book.opf").decode("utf-8")
        package = package.replace('properties="nav"', '')
        package = package.replace("</manifest>", '<item id="ncx" href="legacy.ncx" media-type="application/x-dtbncx+xml"/></manifest>')
        package = package.replace("<spine>", '<spine toc="ncx">')
        ncx = '<ncx><navMap><navPoint><navLabel><text>Legacy chapter</text></navLabel><content src="chapter.xhtml#next"/></navPoint></navMap></ncx>'
        book = load_book(write_epub(path, overrides={"OPS/book.opf": package}, extra=(("OPS/legacy.ncx", ncx),)))
        self.assertEqual(book.outline[0].title, "Legacy chapter")
        self.assertTrue(book.chapters[0].text[book.outline[0].offset:].startswith("Наступна строфа"))

    def test_epub_text_limits_nesting_before_scanning_bad_closing_tags(self):
        chapter = "<html><body>" + "<div>" * 129 + "Readable text" + "</missing>" * 129 + "</div>" * 129 + "</body></html>"
        path = write_epub(self.root / "deep.epub", overrides={"OPS/chapter.xhtml": chapter})
        with self.assertRaises(BookError):
            load_book(path)

    def test_epub_rejects_archive_traversal_and_absolute_paths(self):
        for name in ("../escape.txt", "/absolute.txt", "C:/escape.txt", "dir\\escape.txt", "dir/./escape.txt"):
            with self.subTest(name=name), self.assertRaises(BookError):
                load_book(write_epub(self.root / "unsafe.epub", extra=((name, "payload"),)))
        self.assertFalse((self.root.parent / "escape.txt").exists())

    def test_epub_rejects_duplicate_member_names(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            path = write_epub(self.root / "duplicate.epub", extra=(("OPS/chapter.xhtml", "different"),))
        with self.assertRaises(BookError):
            load_book(path)

    def test_epub_rejects_symlink_members(self):
        info = zipfile.ZipInfo("link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaises(BookError):
            load_book(write_epub(self.root / "link.epub", extra=((info, "/etc/passwd"),)))

    def test_epub_internal_references_cannot_leave_archive(self):
        for href in ("../../outside.xhtml", "https://example.org/book.xhtml", "%2e%2e/%2e%2e/outside.xhtml", "%2fetc/passwd"):
            with self.subTest(href=href), self.assertRaises(BookError):
                load_book(write_epub(self.root / "external.epub", chapter_href=href))

    def test_malformed_epub_is_a_user_facing_book_error(self):
        with self.assertRaises(BookError):
            load_book(self.write("broken.epub", b"not zip"))


if __name__ == "__main__":
    unittest.main()
