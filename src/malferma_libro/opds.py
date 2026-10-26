"""Read public OPDS 1.x catalogs and download supported ebook files.

Only HTTP(S) URLs without embedded credentials are accepted, including after
redirects. HTTP remains available for local catalogs such as Calibre.
"""

from __future__ import annotations

from dataclasses import dataclass
from http.client import IncompleteRead
from html.parser import HTMLParser
from pathlib import Path
import os
import re
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request
import xml.etree.ElementTree as ET

from .i18n import _
from . import __version__
from .covers import CoverData, MAX_COVER_BYTES, validate_cover
from .network import fetch_response
from .tasks import check_cancel, report_progress
from .xmlutil import XMLLimitError, parse_xml


DEFAULT_TIMEOUT = 20
COVER_TIMEOUT = 8
CATALOG_TRANSFER_TIMEOUT = 30
COVER_TRANSFER_TIMEOUT = 15
BOOK_TRANSFER_TIMEOUT = 300
MAX_CATALOG_BYTES = 5 * 1024 * 1024
MAX_BOOK_BYTES = 64 * 1024 * 1024
MAX_CBZ_DOWNLOAD_BYTES = 512 * 1024 * 1024
MAX_XML_DEPTH = 128
MAX_XML_NODES = 200_000
MAX_URL_CHARS = 8192
MAX_CATALOG_ENTRIES = 2048
MAX_ENTRY_LINKS = 128
MAX_CATALOG_REFERENCES = 8192
MAX_CATALOG_URL_CHARS = 2 * 1024 * 1024
MAX_FILENAME_BYTES = 255
_COLLISION_SUFFIX = " (9999)"
USER_AGENT = f"MalfermaLibro/{__version__}"
_XML_BASE = "{http://www.w3.org/XML/1998/namespace}base"
_ATOM_TYPES = {"application/atom+xml", "application/xml", "text/xml"}
_ACQUISITION_RELS = {
    "http://opds-spec.org/acquisition",
    "http://opds-spec.org/acquisition/open-access",
    "https://opds-spec.org/acquisition",
    "https://opds-spec.org/acquisition/open-access",
}
_COVER_RELS = {
    "http://opds-spec.org/image", "https://opds-spec.org/image",
    "http://opds-spec.org/cover", "https://opds-spec.org/cover",
    "cover", "x-stanza-cover-image",
}
_THUMBNAIL_RELS = {
    "http://opds-spec.org/image/thumbnail", "https://opds-spec.org/image/thumbnail",
    "http://opds-spec.org/thumbnail", "https://opds-spec.org/thumbnail",
    "thumbnail", "x-stanza-cover-image-thumbnail",
}
_COVER_MIMES = {
    "image/png": "image/png", "image/x-png": "image/png",
    "image/jpeg": "image/jpeg", "image/jpg": "image/jpeg", "image/pjpeg": "image/jpeg",
}
_OPAQUE_MIMES = {"", "application/octet-stream", "binary/octet-stream"}
_MIME_EXTENSIONS = {
    "application/epub+zip": ".epub",
    "application/x-fictionbook+xml": ".fb2",
    "application/fb2+xml": ".fb2",
    "text/fb2+xml": ".fb2",
    "application/x-fictionbook+zip": ".fb2.zip",
    "application/fb2+zip": ".fb2.zip",
    "application/x-fb2+zip": ".fb2.zip",
    "text/plain": ".txt",
    "text/html": ".html",
    "application/xhtml+xml": ".xhtml",
    "text/markdown": ".md",
    "text/x-markdown": ".md",
    "application/vnd.comicbook+zip": ".cbz",
    "application/x-cbz": ".cbz",
    "application/pdf": ".pdf",
    "image/vnd.djvu": ".djvu",
    "image/x-djvu": ".djvu",
    "application/vnd.djvu": ".djvu",
    "application/x-djvu": ".djvu",
}


class OPDSError(ValueError):
    """A catalog or download could not be read safely."""


@dataclass(frozen=True)
class Acquisition:
    url: str
    mime_type: str
    label: str


@dataclass(frozen=True)
class CatalogEntry:
    title: str
    author: str
    summary: str
    catalog_url: str | None
    downloads: list[Acquisition]
    cover_url: str | None = None


@dataclass(frozen=True)
class CatalogPage:
    title: str
    entries: list[CatalogEntry]
    next_url: str | None
    search_url: str | None


def _validate_url(url: str) -> str:
    if not isinstance(url, str) or not url:
        raise OPDSError(_("Не указан адрес каталога."))
    if len(url) > MAX_URL_CHARS:
        raise OPDSError(_("Неверный адрес сервера."))
    url = url.strip()
    if any(ord(char) < 32 or ord(char) == 127 for char in url):
        raise OPDSError(_("Адрес содержит недопустимые символы."))
    try:
        parts = urlsplit(url)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            raise OPDSError(_("Допустимы только адреса HTTP и HTTPS."))
        if parts.username is not None or parts.password is not None:
            raise OPDSError(_("Адреса с логином или паролем не поддерживаются."))
        if "\\" in parts.netloc or " " in parts.netloc:
            raise OPDSError(_("Неверный адрес сервера."))
        port = parts.port  # Validate malformed or out-of-range ports before urllib.
        host = parts.hostname.encode("idna").decode("ascii")
        if any(character.isspace() for character in host):
            raise OPDSError(_("Неверный адрес сервера."))
        if ":" in host:
            host = "[" + host + "]"
        netloc = host + (f":{port}" if port is not None else "")
        # Feeds often contain human-readable Unicode IRIs. urllib needs an
        # ASCII host and request target; retain existing escapes and direct
        # OPDS search placeholders while encoding book names and queries.
        parts = parts._replace(
            netloc=netloc,
            path=quote(parts.path, safe="/%:@!$&'()*+,;=-._~{}"),
            query=quote(parts.query, safe="/?%:@!$&'()*+,;=-._~{}"),
            fragment="",
        )
    except ValueError as exc:
        if isinstance(exc, OPDSError):
            raise
        raise OPDSError(_("Неверный адрес сервера.")) from exc
    result = urlunsplit(parts)
    if len(result) > MAX_URL_CHARS:
        raise OPDSError(_("Неверный адрес сервера."))
    return result


def _resolve_url(href: str, base: str) -> str | None:
    if len(href) > MAX_URL_CHARS or len(base) > MAX_URL_CHARS:
        return None
    if not href.strip():
        return None
    try:
        return _validate_url(urljoin(base, href.strip()))
    except (OPDSError, ValueError):
        return None


class _CatalogURLs:
    """Budget resolution work and retained URLs, including duplicate links."""

    def __init__(self, cancel):
        self.cancel = cancel
        self.references = self.characters = 0

    def resolve(self, href, base):
        check_cancel(self.cancel)
        self.references += 1
        if self.references > MAX_CATALOG_REFERENCES:
            raise OPDSError(_("Каталог слишком большой."))
        url = _resolve_url(href, base)
        self.characters += len(url) if url else 0
        if self.characters > MAX_CATALOG_URL_CHARS:
            raise OPDSError(_("Каталог слишком большой."))
        return url

    def base(self, element, parent):
        value = element.get(_XML_BASE)
        return (self.resolve(value, parent) or parent) if value else parent

    def links(self, element):
        links = _children(element, "link")
        if len(links) > MAX_ENTRY_LINKS:
            raise OPDSError(_("Каталог слишком большой."))
        return links


class _SafeRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            redirect = super().redirect_request(
                req, fp, code, msg, headers, _validate_url(newurl)
            )
        except Exception:
            # Rejected redirects also own an open server response. Do not
            # leak its socket, or drain an attacker-controlled response body.
            fp.close()
            raise
        if redirect is not None:
            # urllib otherwise reads the entire redirect body without a limit
            # before closing it. Its HTTPResponse.read() returns b"" once closed.
            fp.close()
        return redirect


def _open_url(url: str, accept: str, *, timeout=None, limit=MAX_CATALOG_BYTES,
              cancel=None, total_timeout=CATALOG_TRANSFER_TIMEOUT):
    request = Request(
        _validate_url(url), headers={"User-Agent": USER_AGENT, "Accept": accept}
    )
    return fetch_response(request, policy="opds", limit=limit, cancel=cancel,
                          socket_timeout=DEFAULT_TIMEOUT if timeout is None else timeout,
                          total_timeout=total_timeout)


def _check_length(response, limit: int) -> int | None:
    value = response.headers.get("Content-Length")
    if value:
        try:
            length = int(value)
        except ValueError:
            return None
        if length > limit:
            raise OPDSError(_("Размер ответа превышает допустимый предел."))
        return length if length >= 0 else None
    return None


def _read_bounded(response, limit: int, *, cancel=None) -> bytes:
    expected = _check_length(response, limit)
    chunks = []
    total = 0
    report_progress(cancel, 0, expected)
    while True:
        check_cancel(cancel)
        chunk = response.read(min(64 * 1024, limit - total + 1))
        check_cancel(cancel)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise OPDSError(_("Размер ответа превышает допустимый предел."))
        chunks.append(chunk)
        report_progress(cancel, total, expected)
    if expected is not None and total != expected:
        raise OPDSError(_("Сервер передал неполный файл."))
    return b"".join(chunks)


def _network_error(exc: Exception) -> OPDSError:
    if isinstance(exc, HTTPError):
        # urllib exposes an error response as a readable exception. It is not
        # entered by the caller's response context manager when open() fails.
        exc.close()
        return OPDSError(_("Сервер вернул ошибку HTTP {code}.").format(code=exc.code))
    return OPDSError(_('Не удалось получить данные: {exc}').format(exc=exc))


def fetch_catalog(url: str, *, cancel=None) -> CatalogPage:
    """Fetch an Atom feed with a timeout and a bounded response size."""
    try:
        check_cancel(cancel)
        with _open_url(url, "application/atom+xml, application/xml;q=0.9",
                       cancel=cancel) as response:
            check_cancel(cancel)
            final_url = _validate_url(response.geturl())
            data = _read_bounded(response, MAX_CATALOG_BYTES, cancel=cancel)
        check_cancel(cancel)
        page = parse_catalog(data, final_url, cancel=cancel)
        check_cancel(cancel)
        return page
    except IncompleteRead as exc:
        check_cancel(cancel)
        raise OPDSError(_("Сервер передал неполный файл.")) from exc
    except (URLError, OSError, TimeoutError) as exc:
        check_cancel(cancel)
        raise _network_error(exc) from exc


def download_cover(url: str, *, token=None) -> CoverData | None:
    """Explicitly fetch one bounded PNG/JPEG; malformed images have no cover.

    Feed parsing never calls this function. The application decides whether a
    supplied catalog image should be requested. Raster validation is shared
    with embedded local covers; active image formats are not accepted.
    """
    check_cancel(token)
    url = _validate_url(url)
    try:
        with _open_url(url, "image/png, image/jpeg", timeout=COVER_TIMEOUT,
                       limit=MAX_COVER_BYTES, cancel=token,
                       total_timeout=COVER_TRANSFER_TIMEOUT) as response:
            check_cancel(token)
            _validate_url(response.geturl())
            content_type = _mime(response.headers.get("Content-Type", ""))
            if content_type not in _COVER_MIMES and content_type not in _OPAQUE_MIMES:
                raise OPDSError(_("Сервер вернул файл неподдерживаемого типа."))
            data = _read_bounded(response, MAX_COVER_BYTES, cancel=token)
        check_cancel(token)
        cover = validate_cover(data, content_type)
        check_cancel(token)
        if cover is not None and content_type in _COVER_MIMES:
            if cover.mime_type != _COVER_MIMES[content_type]:
                raise OPDSError(_("Сервер вернул файл неподдерживаемого типа."))
        return cover
    except IncompleteRead as exc:
        check_cancel(token)
        raise OPDSError(_("Сервер передал неполный файл.")) from exc
    except (URLError, OSError, TimeoutError) as exc:
        check_cancel(token)
        raise _network_error(exc) from exc


def _local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in element if _local_name(child) == name]


def _content(element: ET.Element) -> str:
    return " ".join(" ".join(element.itertext()).split())


def _child_text(element: ET.Element, name: str) -> str:
    children = _children(element, name)
    return _content(children[0]) if children else ""


class _HTMLText(HTMLParser):
    _BREAKS = {"p", "div", "br", "li", "blockquote", "pre", "hr", "tr", "td", "th",
               "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in self._BREAKS:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1
        if tag in self._BREAKS:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)

    def append_xhtml(self, element: ET.Element):
        tag = _local_name(element)
        self.handle_starttag(tag, element.attrib.items())
        if element.text:
            self.handle_data(element.text)
        for child in element:
            self.append_xhtml(child)
            if child.tail:
                self.handle_data(child.tail)
        self.handle_endtag(tag)


def _summary(entry: ET.Element) -> str:
    candidates = _children(entry, "summary") or _children(entry, "content")
    if not candidates:
        return ""
    element = candidates[0]
    content_type = element.get("type", "text").lower()
    if content_type not in {"html", "xhtml", "text/html"}:
        return _content(element)
    parser = _HTMLText()
    if content_type == "xhtml":
        # XML has already decoded text entities. Passing that text through an
        # HTML parser again would interpret literal <...> as markup and expose
        # text from script/style elements after their tags had been discarded.
        parser.append_xhtml(element)
    else:
        parser.feed(_content(element))
    return " ".join("".join(parser.parts).split())


def _mime(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()


def _book_extension(mime_type: str, url: str) -> str | None:
    mime_type = _mime(mime_type)
    if mime_type in _MIME_EXTENSIONS:
        return _MIME_EXTENSIONS[mime_type]
    if mime_type not in {"", "application/octet-stream", "binary/octet-stream", "application/zip"}:
        return None
    path = unquote(urlsplit(url).path).lower()
    extensions = ((".fb2.zip", ".cbz") if mime_type == "application/zip" else
                  (".fb2.zip", ".epub", ".fb2", ".txt", ".pdf", ".djvu", ".djv",
                   ".html", ".htm", ".xhtml", ".md", ".markdown", ".cbz"))
    extension = next((extension for extension in extensions if path.endswith(extension)), None)
    # Both suffixes denote the same format. Use one canonical suffix so a
    # redirect or a MIME alias does not produce a false format mismatch.
    return {".djv": ".djvu", ".htm": ".html", ".markdown": ".md"}.get(extension, extension)


def _book_format(extension: str) -> str:
    """Compare format families while retaining useful HTML/Markdown suffixes."""
    return {".htm": ".html", ".xhtml": ".html", ".markdown": ".md"}.get(extension, extension)


def parse_catalog(data: bytes, base_url: str, *, cancel=None) -> CatalogPage:
    """Parse OPDS 1.x Atom; unsafe links and unsupported acquisition flows are omitted.

    A direct search template is exposed only when it contains ``{searchTerms}``.
    OpenSearch description documents are not fetched automatically.
    """
    check_cancel(cancel)
    base_url = _validate_url(base_url)
    if len(data) > MAX_CATALOG_BYTES:
        raise OPDSError(_("Каталог слишком большой."))
    # Removing NULs also detects declarations in UTF-16 and UTF-32 XML.
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", data.replace(b"\x00", b""), re.I):
        raise OPDSError(_("Каталоги с DTD или XML-сущностями не поддерживаются."))
    try:
        root = parse_xml(data, max_nodes=MAX_XML_NODES, max_depth=MAX_XML_DEPTH)
    except XMLLimitError as exc:
        raise OPDSError(_('Каталог: {exc}.').format(exc=exc)) from exc
    except (ET.ParseError, LookupError, ValueError) as exc:
        raise OPDSError(_("Сервер вернул некорректный XML-каталог.")) from exc
    check_cancel(cancel)
    if _local_name(root) != "feed":
        raise OPDSError(_("Ожидался OPDS-каталог в формате Atom."))
    urls = _CatalogURLs(cancel)
    feed_base = urls.base(root, base_url)
    next_url = None
    search_url = None
    for link in urls.links(root):
        rels = set(link.get("rel", "").split())
        url = urls.resolve(link.get("href", ""), urls.base(link, feed_base))
        if "next" in rels and url:
            next_url = url
        if ("search" in rels and url and "{searchTerms}" in url
                and _mime(link.get("type", "")) in _ATOM_TYPES | {""}):
            search_url = url
    entries = []
    elements = _children(root, "entry")
    if len(elements) > MAX_CATALOG_ENTRIES:
        raise OPDSError(_("Каталог слишком большой."))
    for element in elements:
        check_cancel(cancel)
        entry_base = urls.base(element, feed_base)
        downloads = []
        catalog_url = None
        cover_url = None
        cover_rank = 2
        seen = set()
        for link in urls.links(element):
            url = urls.resolve(link.get("href", ""), urls.base(link, entry_base))
            if not url:
                continue
            rels = set(link.get("rel", "").split())
            mime_type = _mime(link.get("type", ""))
            if rels & (_COVER_RELS | _THUMBNAIL_RELS):
                rank = 0 if rels & _THUMBNAIL_RELS else 1
                if rank < cover_rank and mime_type in _COVER_MIMES.keys() | _OPAQUE_MIMES:
                    cover_url, cover_rank = url, rank
            if rels & _ACQUISITION_RELS:
                extension = _book_extension(mime_type, url)
                if extension and url not in seen:
                    label = link.get("title", "").strip() or extension.lstrip(".").upper()
                    downloads.append(Acquisition(url, mime_type, label))
                    seen.add(url)
            elif mime_type in _ATOM_TYPES and (not rels or rels & {"subsection", "alternate", "http://opds-spec.org/subsection"}):
                catalog_url = catalog_url or url
        authors = [_child_text(author, "name") for author in _children(element, "author")]
        entries.append(CatalogEntry(
            title=_child_text(element, "title") or _("Без названия"),
            author=", ".join(author for author in authors if author),
            summary=_summary(element),
            catalog_url=catalog_url,
            downloads=downloads,
            cover_url=cover_url,
        ))
    return CatalogPage(_child_text(root, "title") or _("Каталог"), entries, next_url, search_url)


def _safe_filename(url: str, label: str, extension: str) -> str:
    name = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
    html_endpoint = (name.lower().endswith((".html", ".htm", ".xhtml"))
                     and _book_format(extension) != ".html")
    if not name or name.lower().endswith((".php", ".asp", ".aspx")) or html_endpoint:
        name = label or _("Книга")
    # Never allow paths, invisible controls, or shell/Windows-special filenames.
    name = re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]', "_", name).strip(" .")
    # An actual HTML or Markdown filename is a document, not a generic server
    # endpoint. Preserve its spelling, suffix alias and case instead of
    # replacing it with the acquisition label or appending a second suffix.
    aliases = {".html": (".html", ".htm", ".xhtml"), ".md": (".md", ".markdown")}
    alias = next((value for value in aliases.get(_book_format(extension), ())
                  if name.lower().endswith(value)), None)
    if alias:
        extension = name[-len(alias):]
        name = name[:-len(alias)]
    elif name.lower().endswith(extension):
        name = name[:-len(extension)]
    elif extension == ".djvu" and name.lower().endswith(".djv"):
        name = name[:-4]
    name = name[:120].strip(" .") or _("Книга")
    # Linux limits a filename in bytes. Leave room for the extension and the
    # largest suffix used by _commit_download, and only cut whole characters.
    budget = MAX_FILENAME_BYTES - len(os.fsencode(extension + _COLLISION_SUFFIX))
    while len(os.fsencode(name)) > budget:
        name = name[:-1]
    name = name.strip(" .") or _("Книга")
    return name + extension


def _commit_download(temporary: Path, directory: Path, filename: str) -> Path:
    original = Path(filename)
    suffix = ".fb2.zip" if filename.lower().endswith(".fb2.zip") else original.suffix
    stem = filename[:-len(suffix)] if suffix else filename
    for number in range(10000):
        name = filename if number == 0 else f"{stem} ({number}){suffix}"
        destination = directory / name
        try:
            # Link creation is atomic and does not overwrite an existing book.
            os.link(temporary, destination)
            return destination
        except FileExistsError:
            continue
    raise OPDSError(_("Не удалось подобрать свободное имя файла."))


def download_book(acquisition: Acquisition, destination_dir: Path, *, cancel=None) -> Path:
    """Download a supported ebook atomically, without replacing existing files."""
    check_cancel(cancel)
    url = _validate_url(acquisition.url)
    extension = _book_extension(acquisition.mime_type, url)
    if not extension:
        raise OPDSError(_("Этот формат книги не поддерживается."))
    limit = MAX_CBZ_DOWNLOAD_BYTES if extension == ".cbz" else MAX_BOOK_BYTES
    directory = Path(destination_dir)
    temporary = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        check_cancel(cancel)
        with _open_url(url, acquisition.mime_type or "application/octet-stream",
                       limit=limit, cancel=cancel, total_timeout=BOOK_TRANSFER_TIMEOUT) as response:
            check_cancel(cancel)
            final_url = _validate_url(response.geturl())
            content_type = _mime(response.headers.get("Content-Type", ""))
            if content_type and content_type not in {"application/octet-stream", "binary/octet-stream"}:
                actual_extension = _book_extension(content_type, final_url)
                # Plain text is valid Markdown. Raw-file hosts commonly send
                # it for a Markdown acquisition or a known .md URL; keep the
                # requested interpretation without reclassifying ordinary TXT.
                if content_type == "text/plain" and _book_format(extension) == ".md":
                    actual_extension = extension
                if (content_type == "application/zip" and actual_extension is None
                        and extension in {".epub", ".fb2.zip", ".cbz"}):
                    actual_extension = extension
                if not actual_extension:
                    raise OPDSError(_("Сервер вернул файл неподдерживаемого типа."))
                if _book_format(actual_extension) != _book_format(extension):
                    raise OPDSError(_("Формат ответа не совпадает с форматом книги."))
            expected = _check_length(response, limit)
            with tempfile.NamedTemporaryFile(prefix=".download-", dir=directory, delete=False) as handle:
                temporary = Path(handle.name)
                total = 0
                report_progress(cancel, 0, expected)
                while True:
                    check_cancel(cancel)
                    chunk = response.read(min(64 * 1024, limit - total + 1))
                    check_cancel(cancel)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > limit:
                        raise OPDSError(_("Книга превышает допустимый размер."))
                    handle.write(chunk)
                    report_progress(cancel, total, expected)
                check_cancel(cancel)
                handle.flush()
                os.fsync(handle.fileno())
                check_cancel(cancel)
        if expected is not None and total != expected:
            raise OPDSError(_("Сервер передал неполный файл."))
        if not total:
            raise OPDSError(_("Сервер вернул пустой файл."))
        filename = _safe_filename(final_url, acquisition.label, extension)
        check_cancel(cancel)
        return _commit_download(temporary, directory, filename)
    except IncompleteRead as exc:
        check_cancel(cancel)
        raise OPDSError(_("Сервер передал неполный файл.")) from exc
    except (URLError, OSError, TimeoutError) as exc:
        check_cancel(cancel)
        raise _network_error(exc) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
