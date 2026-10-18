"""OPDS parsing and bounded downloads, with no live network requests.

SPDX-License-Identifier: GPL-3.0-or-later
"""

import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from malferma_libro.opds import Acquisition, OPDSError, download_book, parse_catalog, fetch_catalog
from malferma_libro.tasks import OperationToken, TaskCancelled


BASE = "https://books.example.org/opds/catalog.xml"
ACQUIRE = "http://opds-spec.org/acquisition/open-access"


def feed(body, *, attributes=""):
    return f'<feed xmlns="http://www.w3.org/2005/Atom" {attributes}><title>Відкрита бібліотека</title>{body}</feed>'.encode("utf-8")


class FakeResponse(io.BytesIO):
    def __init__(self, data, *, url="https://books.example.org/book.txt", content_type="text/plain", length=None):
        super().__init__(data)
        self.url = url
        self.headers = {"Content-Type": content_type}
        if length is not None:
            self.headers["Content-Length"] = str(length)

    def geturl(self):
        return self.url


class CatalogTests(unittest.TestCase):
    def test_namespace_metadata_and_relative_urls(self):
        xml = feed(f'''<link rel="next" href="?page=2"/><link rel="search" type="application/atom+xml" href="search?q={{searchTerms}}"/>
        <entry><title>Contra spem spero!</title><author><name>Леся Українка</name></author><author><name>Редактор</name></author>
        <link rel="{ACQUIRE}" type="application/epub+zip" href="../books/poem.epub"/>
        <summary>Українська поезія 🙂</summary></entry>''')
        page = parse_catalog(xml, BASE)
        self.assertEqual(page.title, "Відкрита бібліотека")
        self.assertEqual(page.next_url, "https://books.example.org/opds/catalog.xml?page=2")
        self.assertEqual(page.search_url, "https://books.example.org/opds/search?q={searchTerms}")
        book = page.entries[0]
        self.assertEqual(book.author, "Леся Українка, Редактор")
        self.assertEqual(book.downloads[0].url, "https://books.example.org/books/poem.epub")
        self.assertEqual(book.summary, "Українська поезія 🙂")

    def test_xml_base_is_applied_at_feed_entry_and_link_levels(self):
        xml = feed(f'<entry xml:base="authors/"><title>Поезія</title><link xml:base="../downloads/" rel="{ACQUIRE}" type="text/plain" href="poem.txt"/></entry>', attributes='xml:base="https://cdn.example.org/public/"')
        self.assertEqual(parse_catalog(xml, BASE).entries[0].downloads[0].url, "https://cdn.example.org/public/downloads/poem.txt")

    def test_supported_acquisition_families(self):
        formats = {
            "application/epub+zip": ".epub", "application/x-fictionbook+xml": ".fb2",
            "application/x-fictionbook+zip": ".fb2.zip", "text/plain": ".txt",
            "text/html": ".html", "application/xhtml+xml": ".xhtml",
            "text/markdown": ".md", "application/vnd.comicbook+zip": ".cbz",
            "application/pdf": ".pdf", "image/vnd.djvu": ".djvu",
        }
        links = "".join(f'<link rel="{ACQUIRE}" type="{mime}" href="download{extension}"/>' for mime, extension in formats.items())
        downloads = parse_catalog(feed(f"<entry><title>Formats</title>{links}</entry>"), BASE).entries[0].downloads
        self.assertEqual([item.mime_type for item in downloads], list(formats))
        self.assertEqual(len(downloads), 10)

    def test_opaque_mime_uses_filename_and_canonical_aliases(self):
        xml = feed(f'<entry><title>Aliases</title><link rel="{ACQUIRE}" type="application/octet-stream" href="poem.DJV"/><link rel="{ACQUIRE}" type="application/zip" href="book.fb2.zip"/></entry>')
        self.assertEqual([item.label for item in parse_catalog(xml, BASE).entries[0].downloads], ["DJVU", "FB2.ZIP"])

    def test_duplicate_downloads_and_unsupported_purchase_flows_are_omitted(self):
        xml = feed(f'''<entry><title>Book</title><link rel="{ACQUIRE}" type="text/plain" href="poem.txt"/>
        <link rel="{ACQUIRE}" type="text/plain" href="poem.txt"/>
        <link rel="http://opds-spec.org/acquisition/buy" type="application/epub+zip" href="buy.epub"/>
        <link rel="{ACQUIRE}" type="application/x-executable" href="program.exe"/></entry>''')
        self.assertEqual(len(parse_catalog(xml, BASE).entries[0].downloads), 1)

    def test_subcatalog_and_thumbnail_are_selected_without_network(self):
        xml = feed('''<entry><title>Authors</title><link rel="subsection" type="application/atom+xml;profile=opds-catalog" href="authors"/>
        <link rel="http://opds-spec.org/image" type="image/jpeg" href="cover.jpg"/>
        <link rel="http://opds-spec.org/image/thumbnail" type="image/png" href="small.png"/></entry>''')
        with patch("malferma_libro.opds._open_url", side_effect=AssertionError("Parser must not fetch resources")):
            entry = parse_catalog(xml, BASE).entries[0]
        self.assertEqual(entry.catalog_url, "https://books.example.org/opds/authors")
        self.assertEqual(entry.cover_url, "https://books.example.org/opds/small.png")

    def test_html_summary_removes_executable_content(self):
        xml = feed('<entry><title>Summary</title><summary type="html">&lt;p&gt;Вітаю &amp;amp; hello&lt;/p&gt;&lt;script&gt;hidden()&lt;/script&gt;&lt;p&gt;שלום&lt;/p&gt;</summary></entry>')
        self.assertEqual(parse_catalog(xml, BASE).entries[0].summary, "Вітаю & hello שלום")

    def test_unsafe_links_are_omitted(self):
        links = "".join(f'<link rel="{ACQUIRE}" type="text/plain" href="{href}"/>' for href in ("file:///etc/passwd", "javascript:alert(1)", "ftp://example.org/a.txt", "https://user:pass@example.org/a.txt", "https://example.org:99999/a.txt"))
        self.assertEqual(parse_catalog(feed(f"<entry><title>Unsafe</title>{links}</entry>"), BASE).entries[0].downloads, [])

    def test_invalid_catalog_urls_are_rejected_before_reading(self):
        for address in ("file:///etc/passwd", "https://user:pass@example.org/opds", "https://example.org:99999/opds", "https://example.org/\nheader", "https://exam\u00a0ple.org/opds"):
            with self.subTest(address=address), self.assertRaises(OPDSError):
                parse_catalog(feed(""), address)

    def test_entity_and_malformed_catalogs_are_rejected(self):
        for xml in (b'<html>not atom</html>', b'<feed>', b'<!DOCTYPE feed [<!ENTITY x "expanded">]><feed>&x;</feed>'):
            with self.subTest(xml=xml), self.assertRaises(OPDSError):
                parse_catalog(xml, BASE)

    def test_opensearch_description_is_not_exposed_as_direct_search(self):
        page = parse_catalog(feed('<link rel="search" type="application/opensearchdescription+xml" href="search.xml"/>'), BASE)
        self.assertIsNone(page.search_url)

    def test_unicode_urls_are_encoded_without_losing_search_templates(self):
        page = parse_catalog(feed(f'<link rel="search" type="application/atom+xml" href="пошук?q={{searchTerms}}&amp;мова=uk"/><entry><title>Надія</title><link rel="{ACQUIRE}" type="text/plain" href="Леся Українка.txt"/></entry>'), "https://bücher.example.org/opds/")
        self.assertEqual(page.entries[0].downloads[0].url, "https://xn--bcher-kva.example.org/opds/%D0%9B%D0%B5%D1%81%D1%8F%20%D0%A3%D0%BA%D1%80%D0%B0%D1%97%D0%BD%D0%BA%D0%B0.txt")
        self.assertIn("q={searchTerms}", page.search_url)
        page.search_url.encode("ascii")
        path_search = parse_catalog(feed('<link rel="search" type="application/atom+xml" href="пошук/{searchTerms}"/>'), BASE)
        self.assertIn("/{searchTerms}", path_search.search_url)
        path_search.search_url.encode("ascii")

    def test_unicode_catalog_request_is_ascii_before_urllib_opens_it(self):
        response = FakeResponse(feed(""), url="https://bücher.example.org/книги/каталог", content_type="application/atom+xml")
        opener = Mock()
        opener.open.return_value = response
        with patch("malferma_libro.opds.build_opener", return_value=opener):
            page = fetch_catalog("https://bücher.example.org/книги/каталог?q=поезія")
        request = opener.open.call_args.args[0]
        self.assertEqual(request.host, "xn--bcher-kva.example.org")
        request.selector.encode("ascii")
        self.assertEqual(request.get_header("User-agent"), "MalfermaLibro/0.1.0")
        self.assertEqual(page.title, "Відкрита бібліотека")

    def test_encoded_paths_and_local_ipv6_catalogs_are_preserved(self):
        xml = feed(f'<entry><title>Local</title><link rel="{ACQUIRE}" type="text/plain" href="books/poem%20one.txt"/></entry>')
        page = parse_catalog(xml, "http://[::1]:8080/opds/")
        self.assertEqual(page.entries[0].downloads[0].url, "http://[::1]:8080/opds/books/poem%20one.txt")


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.acquisition = Acquisition("https://books.example.org/book.txt", "text/plain", "Poem")

    def test_download_preserves_existing_filename_and_unicode_content(self):
        existing = self.root / "book.txt"
        existing.write_bytes(b"original")
        payload = "Леся Українка 🙂".encode("utf-8")
        with patch("malferma_libro.opds._open_url", return_value=FakeResponse(payload, length=len(payload))):
            downloaded = download_book(self.acquisition, self.root)
        self.assertEqual(downloaded.name, "book (1).txt")
        self.assertEqual(existing.read_bytes(), b"original")
        self.assertEqual(downloaded.read_bytes(), payload)
        self.assertFalse(list(self.root.glob(".download-*")))

    def test_short_response_is_rejected_without_partial_file(self):
        with patch("malferma_libro.opds._open_url", return_value=FakeResponse(b"short", length=100)):
            with self.assertRaises(OPDSError):
                download_book(self.acquisition, self.root)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_response_format_mismatch_is_rejected(self):
        with patch("malferma_libro.opds._open_url", return_value=FakeResponse(b"<html>login</html>", content_type="text/html")):
            with self.assertRaises(OPDSError):
                download_book(self.acquisition, self.root)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_unsafe_redirect_target_is_rejected(self):
        with patch("malferma_libro.opds._open_url", return_value=FakeResponse(b"secret", url="file:///etc/passwd")):
            with self.assertRaises(OPDSError):
                download_book(self.acquisition, self.root)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_cancelled_download_never_opens_network(self):
        token = OperationToken()
        token.cancel()
        with patch("malferma_libro.opds._open_url") as opener:
            with self.assertRaises(TaskCancelled):
                download_book(self.acquisition, self.root, cancel=token)
        opener.assert_not_called()

    def test_markdown_accepts_plain_text_from_raw_file_hosts(self):
        acquisition = Acquisition("https://books.example.org/poem.md", "text/markdown", "Poem")
        with patch("malferma_libro.opds._open_url", return_value=FakeResponse(b"# Title", url=acquisition.url)):
            path = download_book(acquisition, self.root)
        self.assertEqual(path.name, "poem.md")
        self.assertEqual(path.read_bytes(), b"# Title")

    def test_download_cancelled_during_read_removes_partial_file(self):
        token = OperationToken()

        class CancelDuringRead(FakeResponse):
            def read(self, size=-1):
                data = super().read(size)
                token.cancel()
                return data

        with patch("malferma_libro.opds._open_url", return_value=CancelDuringRead(b"Partial book")):
            with self.assertRaises(TaskCancelled):
                download_book(self.acquisition, self.root, cancel=token)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_download_rejects_oversize_stream_without_content_length(self):
        with patch("malferma_libro.opds.MAX_BOOK_BYTES", 8), patch("malferma_libro.opds._open_url", return_value=FakeResponse(b"0123456789")):
            with self.assertRaises(OPDSError):
                download_book(self.acquisition, self.root)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_unicode_download_keeps_human_readable_filename(self):
        address = "https://bücher.example.org/Леся Українка.txt"
        acquisition = Acquisition(address, "text/plain", "Поезія")
        with patch("malferma_libro.opds._open_url", return_value=FakeResponse("Надія".encode(), url=address)) as opener:
            path = download_book(acquisition, self.root)
        self.assertEqual(path.name, "Леся Українка.txt")
        self.assertEqual(path.read_text(), "Надія")
        opener.call_args.args[0].encode("ascii")


if __name__ == "__main__":
    unittest.main()
