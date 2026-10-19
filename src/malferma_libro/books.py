"""Small, bounded ebook readers with no network access or executable content.

EPUB, FB2, HTML and Markdown are converted to plain text. PDF, DjVu and CBZ pages retain their
original layout and are rendered lazily, without executable content.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
import base64
import binascii
from dataclasses import dataclass, field
import hashlib
from html.parser import HTMLParser
import os
from pathlib import Path
import posixpath
import re
import stat
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile
import zlib

from .i18n import _
from .cbz import _directory_preflight
from .illustrations import (
    ImageData, InlineImage, validate_illustration,
    MAX_IMAGE_BYTES as MAX_ILLUSTRATION_BYTES,
    MAX_TOTAL_IMAGE_BYTES as MAX_ILLUSTRATION_TOTAL,
    MAX_IMAGES as MAX_ILLUSTRATIONS,
    MAX_IMAGE_REFERENCES,
)
from .tasks import check_cancel
from .xmlutil import XMLLimitError, parse_xml

if TYPE_CHECKING:
    from .covers import CoverData
    from .cbz import CbzDocument
    from .djvu import DjvuDocument
    from .pdf import PdfDocument


MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_CBZ_FILE_BYTES = 512 * 1024 * 1024
MAX_ZIP_BYTES = 128 * 1024 * 1024
MAX_ENTRY_BYTES = 32 * 1024 * 1024
MAX_ZIP_ENTRIES = 10_000
MAX_ZIP_DIRECTORY_BYTES = 8 * 1024 * 1024
MAX_XML_DEPTH = 128
MAX_XML_NODES = 200_000
MAX_TEXT_CHARS = 32 * 1024 * 1024
MAX_IMAGE_REFERENCE_CHARS = 4096
_XML_TOKENS = re.compile(
    br"<!--|<!\[CDATA\[|<!\s*(?P<kind>ENTITY|DOCTYPE)\b", re.I,
)
_SAFE_DOCTYPE = re.compile(
    br'''<!DOCTYPE\s+[A-Za-z_:][A-Za-z0-9_.:-]*'''
    br'''(?:\s+(?:SYSTEM\s+(?:"[^"\[\]]*"|'[^'\[\]]*')'''
    br'''|PUBLIC\s+(?:"[^"\[\]]*"|'[^'\[\]]*')'''
    br'''\s+(?:"[^"\[\]]*"|'[^'\[\]]*')))?\s*>''', re.I,
)


class BookError(ValueError):
    """A book is unsupported, malformed, unsafe or exceeds a resource limit."""


@dataclass
class Chapter:
    title: str
    text: str
    kind: str = "chapter"
    level: int = 0
    anchors: dict[str, int] = field(default_factory=dict)
    images: list[InlineImage] = field(default_factory=list)


@dataclass
class NavigationEntry:
    title: str
    chapter: int
    offset: int = 0
    level: int = 0
    kind: str = "chapter"


@dataclass
class Book:
    title: str
    author: str
    chapters: list[Chapter]
    format: str
    pdf_document: PdfDocument | None = None
    djvu_document: DjvuDocument | None = None
    outline: list[NavigationEntry] = field(default_factory=list)
    cover: CoverData | None = None
    cbz_document: CbzDocument | None = None

    @property
    def page_document(self) -> PdfDocument | DjvuDocument | CbzDocument | None:
        """Return the lazy backend for a document with fixed page layout."""
        return self.pdf_document or self.djvu_document or self.cbz_document


def _merge_image_only_chapters(chapters: list[Chapter], outline: list[NavigationEntry]) -> tuple[list[Chapter], list[NavigationEntry]]:
    """Keep existing text chapter indices while retaining adjacent artwork.

    Older versions omitted empty-text documents and sections entirely. Their
    artwork belongs before the next text chapter, or after the final one;
    image-only books retain their own reading documents instead.
    """
    reading = [index for index, chapter in enumerate(chapters) if chapter.text]
    if not reading or len(reading) == len(chapters):
        return chapters, outline
    targets: list[int] = [0] * len(chapters)
    following = reading[-1]
    for index in range(len(chapters) - 1, -1, -1):
        if chapters[index].text:
            following = index
        targets[index] = following
    new_indices = {index: number for number, index in enumerate(reading)}
    image_groups: list[list[InlineImage]] = [[] for _index in reading]
    deltas = [0] * len(chapters)
    for index, chapter in enumerate(chapters):
        target = targets[index]
        delta = len(chapters[target].text) if target < index else 0
        deltas[index] = delta
        image_groups[new_indices[target]].extend(
            InlineImage(image.offset + delta, image.image, image.alt) for image in chapter.images)
        if target != index:
            for anchor, offset in chapter.anchors.items():
                chapters[target].anchors.setdefault(anchor, offset + delta)
    kept = [chapters[index] for index in reading]
    for chapter, images in zip(kept, image_groups):
        chapter.images = images
    navigation = [NavigationEntry(entry.title, new_indices[targets[entry.chapter]],
                                  entry.offset + deltas[entry.chapter], entry.level, entry.kind)
                  for entry in outline]
    return kept, navigation


def file_size_limit(path: Path | str) -> int:
    """Comic archives have a separate bounded budget; text limits stay unchanged."""
    return MAX_CBZ_FILE_BYTES if Path(path).suffix.casefold() == ".cbz" else MAX_FILE_BYTES


def file_size_error(path: Path | str) -> str:
    return (_("Архив CBZ превышает допустимый размер (512 МиБ)") if Path(path).suffix.casefold() == ".cbz"
            else _("Книга превышает допустимый размер (64 МиБ)"))


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _inline(element: ET.Element | None) -> str:
    return " ".join("".join(element.itertext()).split()) if element is not None else ""


def _children(element: ET.Element, tag: str) -> list[ET.Element]:
    return [child for child in element if _local(child.tag) == tag]


def _child(element: ET.Element, tag: str) -> ET.Element | None:
    return next((child for child in element if _local(child.tag) == tag), None)


def _xml_declarations(data: bytes) -> Iterator[tuple[re.Match[bytes], int]]:
    """Scan each byte once, leaving comment/CDATA contents uninterpreted.

    Matching whole comments with a regular expression retries every opener
    when a damaged file contains many openers without a closing delimiter.
    An unfinished literal or declaration instead consumes the remaining input;
    the actual XML/HTML parser decides whether that input is well formed.
    """
    position = 0
    while token := _XML_TOKENS.search(data, position):
        kind = token.group("kind")
        if kind is None:
            closing = b"-->" if token.group() == b"<!--" else b"]]>"
            end = data.find(closing, token.end())
            if end < 0:
                return
            position = end + len(closing)
        else:
            end = data.find(b">", token.end())
            yield token, len(data) if end < 0 else end
            if end < 0:
                return
            position = end + 1


def _xml(data: bytes, label: str, *, allow_doctype: bool = False) -> ET.Element:
    if len(data) > MAX_ENTRY_BYTES:
        raise BookError(_('{label}: XML превышает допустимый размер').format(label=label))
    # Removing NULs also detects declarations in UTF-16/UTF-32 documents.
    declarations = data.replace(b"\x00", b"")
    for declaration, _end in _xml_declarations(declarations):
        kind = declaration.group("kind")
        if kind.upper() == b"ENTITY":
            raise BookError(_('{label}: объявления DTD и сущностей XML запрещены').format(label=label))
        # Older EPUBs commonly declare the standard XHTML/NCX external DTD.
        # ElementTree does not fetch it. Permit only the declaration itself,
        # never an internal subset or an entity definition.
        safe_doctype = _SAFE_DOCTYPE.match(declarations, declaration.start())
        if not allow_doctype or safe_doctype is None:
            raise BookError(_('{label}: объявления DTD и сущностей XML запрещены').format(label=label))
    try:
        root = parse_xml(data, max_nodes=MAX_XML_NODES, max_depth=MAX_XML_DEPTH)
    except XMLLimitError as exc:
        raise BookError(f"{label}: {exc}") from exc
    except (ET.ParseError, LookupError, ValueError) as exc:
        raise BookError(_('{label}: повреждённый XML').format(label=label)) from exc
    return root


def _clean_text(text: str) -> str:
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in text.replace("\xa0", " ").splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _clean_positions(text: str, positions: dict[object, int]) -> tuple[str, dict[object, int]]:
    """Apply the text whitespace rules while mapping raw boundaries to Unicode offsets.

    Each pass walks the matches and sorted anchors once. Mapping complete
    prefixes separately would take quadratic time for a book with many IDs.
    """
    if not positions:
        return _clean_text(text), {}
    for expression, replacement in (
        (r"\r\n|[\r\v\f\x1c-\x1e\x85\u2028\u2029]", "\n"),
        (r"[^\S\n]+", " "),
        (r" *\n *", "\n"),
        (r"\n{3,}", "\n\n"),
        (r"^\s+|\s+$", ""),
    ):
        ordered = sorted(positions.items(), key=lambda item: item[1])
        mapped: dict[object, int] = {}
        parts: list[str] = []
        index = cursor = length = 0
        for match in re.finditer(expression, text):
            while index < len(ordered) and ordered[index][1] < match.start():
                key, offset = ordered[index]
                mapped[key] = length + offset - cursor
                index += 1
            prefix = text[cursor:match.start()]
            parts.extend((prefix, replacement))
            length += len(prefix) + len(replacement)
            while index < len(ordered) and ordered[index][1] < match.end():
                # A boundary before a whitespace run stays before its
                # replacement; a boundary inside it targets the next text.
                mapped[ordered[index][0]] = length - len(replacement) if ordered[index][1] == match.start() else length
                index += 1
            cursor = match.end()
        while index < len(ordered):
            key, offset = ordered[index]
            mapped[key] = length + offset - cursor
            index += 1
        parts.append(text[cursor:])
        text, positions = "".join(parts), mapped
    return text, {key: min(len(text), max(0, offset)) for key, offset in positions.items()}


def _semantic_kind(values: str) -> str:
    tokens = set(values.lower().split())
    if tokens & {"notes", "comments", "commentary", "footnote", "endnote", "footnotes", "endnotes", "rearnotes", "doc-footnote", "doc-endnote", "doc-endnotes"}:
        return "notes"
    if tokens & {"appendix", "appendices", "doc-appendix"}:
        return "appendix"
    if tokens & {"frontmatter", "preface", "foreword", "introduction", "doc-preface", "doc-foreword", "doc-introduction"}:
        return "frontmatter"
    if tokens & {"bodymatter", "chapter", "part", "doc-chapter", "doc-part"}:
        return "chapter"
    return ""


def _title_kind(title: str) -> str:
    # Exact section labels are useful in older books without semantic markup;
    # ordinary chapter titles mentioning notes must remain ordinary chapters.
    label = title.casefold().strip(" \t\r\n.:;—–-[]()")
    if label in {"примечания", "сноски", "комментарии", "notes", "endnotes", "footnotes", "commentary"}:
        return "notes"
    if label in {"приложение", "приложения", "appendix", "appendices"}:
        return "appendix"
    return ""


def _element_kind(element: ET.Element) -> str:
    return _semantic_kind(" ".join(element.get(key, "") for key in (
        "{http://www.idpf.org/2007/ops}type", "epub:type", "type", "role", "name",
    )))


class _IllustrationStore:
    """A book-wide budget and cache; optional artwork never replaces its text."""

    def __init__(self, cancel=None) -> None:
        self.references = 0
        self.total_bytes = 0
        self.assets: dict[bytes, ImageData] = {}
        self.cache: dict[str, ImageData | None] = {}
        self.invalid: set[bytes] = set()
        self.cancel = cancel

    @property
    def remaining_references(self) -> int:
        return max(0, MAX_IMAGE_REFERENCES - self.references)

    def load(self, key: str, read: Callable[[], bytes | None]) -> ImageData | None:
        check_cancel(self.cancel)
        if not self.remaining_references:
            return None
        self.references += 1
        if key in self.cache:
            return self.cache[key]
        self.cache[key] = None
        data = read()
        if not data or len(data) > MAX_ILLUSTRATION_BYTES:
            return None
        digest = hashlib.sha256(data).digest()
        if digest in self.invalid:
            return None
        image = self.assets.get(digest)
        if image is not None:
            self.cache[key] = image
            return image
        if len(self.assets) >= MAX_ILLUSTRATIONS or self.total_bytes + len(data) > MAX_ILLUSTRATION_TOTAL:
            return None
        image = validate_illustration(data)
        check_cancel(self.cancel)
        if image is not None:
            self.assets[digest] = image
            self.cache[key] = image
            self.total_bytes += len(data)
        else:
            self.invalid.add(digest)
        return image


@dataclass
class _ImageReference:
    offset: int
    path: str
    alt: str = ""


def _image_reference(base: str | None, value: str) -> str | None:
    """Bound optional URI expansion before joining inherited xml:base values."""
    if base is None or len(base) > MAX_IMAGE_REFERENCE_CHARS or len(value) > MAX_IMAGE_REFERENCE_CHARS:
        return None
    try:
        path = _reference(base, value)
    except BookError:
        return None
    return path if len(path) <= MAX_IMAGE_REFERENCE_CHARS else None


class _TextHTML(HTMLParser):
    _blocks = {
        "address", "article", "aside", "blockquote", "dd", "div", "dl", "dt",
        "figcaption", "figure", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
        "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section", "table",
        "tr", "ul",
    }
    _hidden = {"head", "script", "style", "template", "svg", "math"}
    _void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, *, image_base: str | None = None, image_limit: int = 0) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden: list[str] = []
        self.heading_parts: list[str] = []
        self.heading = ""
        self.heading_tag: str | None = None
        self.pre_depth = 0
        self.length = 0
        self.anchors: dict[str, int] = {}
        self.anchor_kinds: dict[str, str] = {}
        self.elements: list[tuple[str, str]] = []
        self.root_kind = ""
        self.main_text = False
        self.note_text = False
        self.image_base = image_base
        self.image_limit = image_limit
        self.images: list[_ImageReference] = []
        self.image_contexts: list[tuple[str, str | None]] = []
        self.element_count = 0

    def _image_start(self, tag: str, attributes: dict[str, str | None]) -> None:
        if not self.image_limit:
            return
        base = self.image_contexts[-1][1] if self.image_contexts else self.image_base
        if base is not None and len(base) > MAX_IMAGE_REFERENCE_CHARS:
            base = None
        if "xml:base" in attributes and base is not None:
            value = attributes["xml:base"] or ""
            base = _image_reference(base, value)
            if base is not None and urlsplit(value).path.endswith("/"):
                base = base + "/" if len(base) < MAX_IMAGE_REFERENCE_CHARS else None
        # Keep SVG wrappers invisible to the text converter, but retain their
        # embedded raster image references. Script/head/template content stays hidden.
        allowed = not self.hidden or all(item == "svg" for item in self.hidden)
        source = None
        if tag == "img" and not self.hidden:
            source = attributes.get("src")
        elif tag == "image" and allowed:
            source = attributes.get("href") or attributes.get("xlink:href")
        if source and allowed and base is not None and len(self.images) < self.image_limit:
            path = _image_reference(base, source)
            if path is not None:
                self.images.append(_ImageReference(self.length, path, (attributes.get("alt") or "")[:4096]))
        # The optional resolver stays bounded even inside ignored SVG markup.
        if tag not in self._void and len(self.image_contexts) < MAX_XML_DEPTH:
            self.image_contexts.append((tag, base))

    def _append(self, value: str) -> None:
        self.parts.append(value)
        self.length += len(value)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.element_count += 1
        # EPUB text uses the same depth bound as its XML metadata. Without it,
        # mismatched closing tags repeatedly scan an unbounded element stack.
        if self.element_count > MAX_XML_NODES or len(self.elements) + len(self.hidden) >= MAX_XML_DEPTH:
            raise BookError(_("Файл разметки слишком сложный."))
        attributes = dict(attrs)
        self._image_start(tag, attributes)
        if self.hidden:
            if tag in self._hidden:
                self.hidden.append(tag)
            return
        if tag in self._hidden:
            self.hidden.append(tag)
            return
        inherited = self.elements[-1][1] if self.elements else ""
        explicit = _semantic_kind(" ".join(attributes.get(key) or "" for key in ("epub:type", "role")))
        kind = explicit or inherited
        if tag in {"html", "body"} and explicit:
            self.root_kind = explicit
        if tag not in self._void:
            self.elements.append((tag, kind))
        if tag == "pre":
            self.pre_depth += 1
        if tag in self._blocks:
            self._append("\n\n")
        elif tag == "br":
            self._append("\n")
        elif tag in {"td", "th"}:
            self._append(" | ")
        for anchor in (attributes.get("id"), attributes.get("name") if tag == "a" else None):
            if anchor and anchor not in self.anchors:
                self.anchors[anchor] = self.length
                self.anchor_kinds[anchor] = kind
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and not self.heading:
            self.heading_tag = tag
            self.heading_parts = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.image_contexts) - 1, -1, -1):
            if self.image_contexts[index][0] == tag:
                del self.image_contexts[index:]
                break
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
            return
        if self.heading_tag == tag:
            self.heading = " ".join("".join(self.heading_parts).split())
            self.heading_tag = None
        if tag == "pre" and self.pre_depth:
            self.pre_depth -= 1
        if tag in self._blocks:
            self._append("\n\n")
        for index in range(len(self.elements) - 1, -1, -1):
            if self.elements[index][0] == tag:
                del self.elements[index:]
                break

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            value = data if self.pre_depth else re.sub(r"\s+", " ", data)
            self._append(value)
            if value.strip():
                kind = self.elements[-1][1] if self.elements else ""
                if kind == "notes":
                    self.note_text = True
                else:
                    self.main_text = True
            if self.heading_tag:
                self.heading_parts.append(value)

    def unknown_decl(self, data: str) -> None:
        if data.startswith("CDATA["):
            # HTMLParser reports XML CDATA through this callback rather than
            # handle_data. Its contents stay literal, including angle brackets.
            self.handle_data(data[6:])


@dataclass
class _HTMLContent:
    text: str
    heading: str
    anchors: dict[str, int]
    anchor_kinds: dict[str, str]
    kind: str
    images: list[_ImageReference] = field(default_factory=list)


def _html_details(data: bytes, label: str, *, image_limit: int = 0) -> _HTMLContent:
    declarations = data.replace(b"\x00", b"")
    for declaration, end in _xml_declarations(declarations):
        kind = declaration.group("kind")
        if kind.upper() == b"ENTITY":
            raise BookError(_('{label}: объявления сущностей запрещены').format(label=label))
        # HTML's ordinary <!DOCTYPE html> is harmless; internal subsets are not.
        if declarations.find(b"[", declaration.end(), end) >= 0:
            raise BookError(_('{label}: объявления DTD запрещены').format(label=label))
    try:
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            value = data.decode("utf-16")
        else:
            encoding = re.search(br"<\?xml[^>]*encoding\s*=\s*['\"]([^'\"]+)", data[:512], re.I)
            value = data.decode(encoding.group(1).decode("ascii") if encoding else "utf-8-sig")
        parser = _TextHTML(image_base=label, image_limit=image_limit)
        parser.feed(value)
        parser.close()
    except (UnicodeError, LookupError, ValueError) as exc:
        raise BookError(_('{label}: не удалось прочитать текст EPUB').format(label=label)) from exc
    positions: dict[object, int] = dict(parser.anchors)
    positions.update({("image", index): image.offset for index, image in enumerate(parser.images)})
    text, mapped = _clean_positions("".join(parser.parts), positions)
    images = [_ImageReference(mapped[("image", index)], image.path, image.alt)
              for index, image in enumerate(parser.images)]
    anchors = {key: offset for key, offset in mapped.items() if isinstance(key, str)}
    kind = parser.root_kind or ("notes" if parser.note_text and not parser.main_text else "")
    return _HTMLContent(text, parser.heading, anchors, parser.anchor_kinds, kind, images)


def _html(data: bytes, label: str) -> tuple[str, str]:
    """Compatibility helper for existing callers that only need text and title."""
    content = _html_details(data, label)
    return content.text, content.heading


class _Archive:
    def __init__(self, path: Path) -> None:
        self._stream = None
        try:
            # ZipFile constructs every ZipInfo before infolist() can enforce a
            # count. Check the bounded directory on this same open file first.
            # A path swapped for a pipe must not block before fstat rejects it.
            source_path = path.resolve(strict=True)
            self._stream = os.fdopen(os.open(source_path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW), "rb")
            details = os.fstat(self._stream.fileno())
            if not stat.S_ISREG(details.st_mode) or not 0 < details.st_size <= MAX_FILE_BYTES:
                raise ValueError("Invalid ebook archive")
            _directory_preflight(self._stream, details.st_size, max_entries=MAX_ZIP_ENTRIES,
                                 max_directory_bytes=MAX_ZIP_DIRECTORY_BYTES)
            self.zip = zipfile.ZipFile(self._stream)
        except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
            if self._stream is not None:
                self._stream.close()
            raise BookError(_("Повреждённый ZIP-архив книги")) from exc
        self.names: set[str] = set()
        try:
            entries = self.zip.infolist()
            if len(entries) > MAX_ZIP_ENTRIES:
                raise BookError(_("Слишком много файлов в архиве книги"))
            total = 0
            for entry in entries:
                name = entry.filename
                if (
                    not name or name.startswith("/") or "\\" in name or "\x00" in name
                    or any(part in {".", ".."} for part in name.rstrip("/").split("/"))
                    or re.match(r"^[A-Za-z]:", name)
                ):
                    raise BookError(_("Недопустимый путь в архиве книги"))
                if name in self.names:
                    raise BookError(_("Повторяющиеся имена файлов в архиве книги"))
                self.names.add(name)
                if entry.flag_bits & 1:
                    raise BookError(_("Зашифрованные архивы книг не поддерживаются"))
                if entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise BookError(_("Повреждённый ZIP-архив книги"))
                if stat.S_ISLNK(entry.external_attr >> 16):
                    raise BookError(_("Символические ссылки в архиве книги запрещены"))
                if entry.file_size > MAX_ENTRY_BYTES:
                    raise BookError(_("Файл внутри книги превышает допустимый размер"))
                total += entry.file_size
                if total > MAX_ZIP_BYTES:
                    raise BookError(_("Распакованный размер книги превышает допустимый предел"))
        except Exception:
            self.close()
            raise

    def read(self, name: str) -> bytes:
        if name not in self.names or name.endswith("/"):
            raise BookError(_('В книге отсутствует файл: {name}').format(name=name))
        try:
            with self.zip.open(name) as stream:
                data = stream.read(MAX_ENTRY_BYTES + 1)
        except (OSError, RuntimeError, zipfile.BadZipFile, NotImplementedError, zlib.error) as exc:
            raise BookError(_('Не удалось распаковать файл книги: {name}').format(name=name)) from exc
        if len(data) > MAX_ENTRY_BYTES:
            raise BookError(_("Файл внутри книги превышает допустимый размер"))
        return data

    def close(self) -> None:
        self.zip.close()
        self._stream.close()


def _reference(base: str, href: str) -> str:
    try:
        url = urlsplit(href)
        if url.scheme or url.netloc:
            raise BookError(_("Внутренняя ссылка EPUB указывает за пределы книги"))
        path = unquote(url.path, errors="strict")
    except (UnicodeError, ValueError) as exc:
        raise BookError(_("Повреждённая внутренняя ссылка EPUB")) from exc
    if "\\" in path or "\x00" in path or path.startswith("/"):
        raise BookError(_("Недопустимый путь во внутренней ссылке EPUB"))
    result = posixpath.normpath(posixpath.join(posixpath.dirname(base), path)) if path else base
    if result == ".." or result.startswith("../") or result.startswith("/"):
        raise BookError(_("Внутренняя ссылка EPUB выходит за пределы архива"))
    return result


@dataclass
class _NavLink:
    title: str
    path: str
    fragment: str = ""
    level: int = 0
    kind: str = ""


def _nav_link(base: str, href: str, title: str, level: int, kind: str = "") -> _NavLink:
    path = _reference(base, href)
    try:
        fragment = unquote(urlsplit(href).fragment, errors="strict")
    except (UnicodeError, ValueError) as exc:
        raise BookError(_("Повреждённая внутренняя ссылка EPUB")) from exc
    return _NavLink(title, path, fragment, level, kind or _title_kind(title))


def _epub_navigation(archive: _Archive, manifest: dict[str, tuple[str, str, str]], spine: ET.Element) -> list[_NavLink]:
    links: list[_NavLink] = []
    for path, _media, properties in manifest.values():
        if "nav" not in properties.split():
            continue
        root = _xml(archive.read(path), path, allow_doctype=True)
        navs = [node for node in root.iter() if _local(node.tag) == "nav"]
        toc = next((node for node in navs if "toc" in node.attrib.get("{http://www.idpf.org/2007/ops}type", "").split()), None)
        for nav in ([toc] if toc is not None else navs[:1]):
            def walk_list(node: ET.Element, level: int, inherited: str = "") -> None:
                for item in node:
                    if _local(item.tag) not in {"li", "ol", "ul"}:
                        continue
                    if _local(item.tag) in {"ol", "ul"}:
                        walk_list(item, level, inherited)
                        continue
                    label = next((child for child in item if _local(child.tag) in {"a", "span"}), None)
                    kind = _element_kind(item) or (_element_kind(label) if label is not None else "") or inherited
                    title = _inline(label)
                    target = label if label is not None and label.get("href") else next(
                        (child for child in item.iter() if _local(child.tag) == "a" and child.get("href")), None)
                    if target is not None and title:
                        link = _nav_link(path, target.attrib["href"], title, level, kind)
                        links.append(link)
                        kind = link.kind or kind
                    for child in item:
                        if _local(child.tag) in {"ol", "ul"}:
                            walk_list(child, level + 1, kind)
            walk_list(nav, 0, _element_kind(nav))
    # EPUB 3 navigation is authoritative. Do not read an unused legacy NCX:
    # a stale/missing compatibility document must not break the working TOC.
    if links:
        return links
    ncx = manifest.get(spine.get("toc", ""))
    if ncx is None:
        ncx = next((item for item in manifest.values() if item[1] == "application/x-dtbncx+xml"), None)
    if ncx:
        root = _xml(archive.read(ncx[0]), ncx[0], allow_doctype=True)
        ncx_links: list[_NavLink] = []
        def walk_points(node: ET.Element, level: int, inherited: str = "") -> None:
            for point in _children(node, "navPoint"):
                label, content = _child(point, "navLabel"), _child(point, "content")
                title = _inline(label)
                kind = _element_kind(point) or _title_kind(title) or inherited
                if content is not None and content.get("src") and title:
                    ncx_links.append(_nav_link(ncx[0], content.attrib["src"], title, level, kind))
                walk_points(point, level + 1, kind)
        navmap = next((node for node in root.iter() if _local(node.tag) == "navMap"), None)
        if navmap is not None:
            walk_points(navmap, 0)
        links = ncx_links
    return links


def _epub_titles(archive: _Archive, manifest: dict[str, tuple[str, str, str]], spine: ET.Element) -> dict[str, str]:
    """Legacy flat title lookup, retained for callers outside the reader."""
    titles: dict[str, str] = {}
    for link in _epub_navigation(archive, manifest, spine):
        titles.setdefault(link.path, link.title)
    return titles


def _epub(path: Path, *, cancel=None) -> Book:
    archive = _Archive(path)
    try:
        container = _xml(archive.read("META-INF/container.xml"), "container.xml")
        rootfiles = [node for node in container.iter() if _local(node.tag) == "rootfile"]
        if not rootfiles or not rootfiles[0].get("full-path"):
            raise BookError(_("EPUB не содержит описания книги"))
        package_path = _reference("", rootfiles[0].attrib["full-path"])
        root = _xml(archive.read(package_path), package_path)
        metadata, manifest_node, spine = _child(root, "metadata"), _child(root, "manifest"), _child(root, "spine")
        if metadata is None or manifest_node is None or spine is None:
            raise BookError(_("В EPUB отсутствуют метаданные, список файлов или порядок глав"))
        title = next((_inline(node) for node in metadata if _local(node.tag) == "title" and _inline(node)), path.stem)
        author = ", ".join(_inline(node) for node in metadata if _local(node.tag) == "creator" and _inline(node))
        manifest: dict[str, tuple[str, str, str]] = {}
        manifest_ids: set[str] = set()
        for item in manifest_node:
            if _local(item.tag) != "item" or not item.get("id") or not item.get("href"):
                continue
            item_id = item.attrib["id"]
            if item_id in manifest_ids:
                raise BookError(_("Повторяющийся идентификатор в списке файлов EPUB"))
            manifest_ids.add(item_id)
            media = item.get("media-type", "")
            try:
                item_path = _reference(package_path, item.attrib["href"])
            except BookError:
                if media.startswith("image/"):
                    # An unusable optional manifest image must not invalidate
                    # otherwise local, readable chapter documents.
                    continue
                raise
            manifest[item_id] = (item_path, media, item.get("properties", ""))
        navigation = _epub_navigation(archive, manifest, spine)
        titles: dict[str, str] = {}
        links_by_path: dict[str, list[_NavLink]] = {}
        for link in navigation:
            titles.setdefault(link.path, link.title)
            links_by_path.setdefault(link.path, []).append(link)
        chapters: list[Chapter] = []
        locations: dict[str, int] = {}
        details: dict[str, _HTMLContent] = {}
        processed_spine: set[str] = set()
        text_chars = 0
        text_chapters = 0
        artwork = _IllustrationStore(cancel)

        def image_bytes(name: str) -> bytes | None:
            if name not in archive.names or name.endswith("/"):
                return None
            if archive.zip.getinfo(name).file_size > MAX_ILLUSTRATION_BYTES:
                return None
            try:
                return archive.read(name)
            except BookError:
                return None

        def append_document(chapter_path: str, content: _HTMLContent) -> None:
            nonlocal text_chars, text_chapters
            images = []
            for reference in content.images:
                image = artwork.load(reference.path, lambda name=reference.path: image_bytes(name))
                if image is not None:
                    images.append(InlineImage(reference.offset, image, reference.alt))
            if not content.text and not images:
                return
            text_chars += len(content.text)
            if text_chars > MAX_TEXT_CHARS:
                raise BookError(_("Текст книги превышает допустимый размер"))
            chapter_title = titles.get(chapter_path) or content.heading or _("Глава {number}").format(
                number=(text_chapters if content.text else len(chapters)) + 1)
            if content.text:
                text_chapters += 1
            document_links = links_by_path.get(chapter_path, [])
            first_link = document_links[0] if document_links else None
            title_kind = _title_kind(chapter_title) if first_link is None or not first_link.fragment or content.anchors.get(first_link.fragment, 0) == 0 else ""
            kind = content.kind or _title_kind(content.heading) or title_kind or "chapter"
            levels = [link.level for link in document_links]
            chapters.append(Chapter(chapter_title, content.text, kind, min(levels, default=0), content.anchors, images))
            locations.setdefault(chapter_path, len(chapters) - 1)
            details[chapter_path] = content

        for itemref in spine:
            check_cancel(cancel)
            if _local(itemref.tag) != "itemref" or itemref.get("linear", "yes") == "no":
                continue
            item = manifest.get(itemref.get("idref", ""))
            if item is None:
                raise BookError(_("Порядок глав EPUB ссылается на отсутствующий файл"))
            chapter_path, media, _properties = item
            if media not in {"application/xhtml+xml", "text/html"}:
                raise BookError(_("Неподдерживаемый формат главы EPUB: {media}").format(media=media or _("не указан")))
            if chapter_path in processed_spine:
                continue
            processed_spine.add(chapter_path)
            append_document(chapter_path, _html_details(archive.read(chapter_path), chapter_path,
                                                      image_limit=artwork.remaining_references))

        # A publisher may keep the notes outside the linear spine. Import only
        # local manifest documents explicitly linked by the TOC and identified
        # as notes, not arbitrary links or every nonlinear supplement.
        available = {item[0]: item[1] for item in manifest.values()}
        considered: set[str] = set(locations)
        for link in navigation:
            if link.path in considered or available.get(link.path) not in {"application/xhtml+xml", "text/html"}:
                continue
            considered.add(link.path)
            content = _html_details(archive.read(link.path), link.path, image_limit=artwork.remaining_references)
            supplementary_kind = content.kind or link.kind or _title_kind(content.heading)
            if supplementary_kind == "notes":
                append_document(link.path, content)
                if link.path in locations:
                    chapters[locations[link.path]].kind = "notes"
        if not chapters:
            raise BookError(_("EPUB не содержит доступных текстовых глав"))
        outline: list[NavigationEntry] = []
        for link in navigation:
            chapter_index = locations.get(link.path)
            if chapter_index is None:
                continue
            chapter = chapters[chapter_index]
            content = details[link.path]
            offset = chapter.anchors.get(link.fragment, 0) if link.fragment else 0
            kind = content.anchor_kinds.get(link.fragment) or content.kind or link.kind or chapter.kind
            outline.append(NavigationEntry(link.title, chapter_index, offset, link.level, kind))
        covered = {entry.chapter for entry in outline}
        missing = [NavigationEntry(chapter.title, index, level=chapter.level, kind=chapter.kind)
                   for index, chapter in enumerate(chapters) if index not in covered]
        # Merge missing reading documents in one pass while preserving the
        # source TOC's relative order, including non-monotonic fragment links.
        complete: list[NavigationEntry] = []
        cursor = 0
        for entry in outline:
            while cursor < len(missing) and missing[cursor].chapter < entry.chapter:
                complete.append(missing[cursor])
                cursor += 1
            complete.append(entry)
        complete.extend(missing[cursor:])
        outline = complete
        chapters, outline = _merge_image_only_chapters(chapters, outline)
        cover = None
        try:
            from .covers import epub_cover
            cover = epub_cover(archive, root, posixpath.dirname(package_path))
        except Exception:
            # Optional artwork must never prevent opening a readable book.
            pass
        return Book(title, author, chapters, "EPUB", outline=outline, cover=cover)
    finally:
        archive.close()


def _fb2_render(element: ET.Element, *, include_sections: bool = False,
                image_loader: Callable[[str], ImageData | None] | None = None,
                images: list[InlineImage] | None = None) -> tuple[str, dict[str, int], dict[int, int]]:
    parts: list[str] = []
    positions: dict[object, int] = {}
    length = 0
    artwork: list[tuple[ImageData, str]] = []
    blocks = {"p", "title", "subtitle", "v", "stanza", "poem", "cite", "epigraph", "text-author", "annotation", "section"}

    def append(value: str) -> None:
        nonlocal length
        parts.append(value)
        length += len(value)

    def visit(node: ET.Element, *, is_root: bool = False) -> None:
        tag = _local(node.tag)
        if (tag == "section" and not is_root and not include_sections) or tag == "binary":
            return
        if tag == "image":
            if image_loader is not None and images is not None:
                href = node.get("{http://www.w3.org/1999/xlink}href") or node.get("href", "")
                image = image_loader(href)
                if image is not None:
                    positions[("image", len(artwork))] = length
                    artwork.append((image, node.get("alt", "")[:4096]))
            return
        if tag == "empty-line":
            append("\n\n")
            return
        if tag in blocks:
            append("\n\n")
        if node.get("id"):
            positions.setdefault(node.attrib["id"], length)
        if tag == "section":
            positions[("section", id(node))] = length
        if node.text:
            append(node.text)
        for child in node:
            # The root title supplies the chapter's navigation label. Nested
            # note/poem titles remain in the reading text exactly once.
            if not (is_root and _local(child.tag) == "title"):
                visit(child)
            if child.tail:
                append(child.tail)
        if tag in blocks:
            append("\n\n")

    visit(element, is_root=True)
    text, mapped = _clean_positions("".join(parts), positions)
    anchors = {key: offset for key, offset in mapped.items() if isinstance(key, str)}
    sections = {key[1]: offset for key, offset in mapped.items() if isinstance(key, tuple) and key[0] == "section"}
    if images is not None:
        images.extend(InlineImage(mapped[("image", index)], image, alt) for index, (image, alt) in enumerate(artwork))
    return text, anchors, sections


def _fb2_text(element: ET.Element) -> str:
    return _fb2_render(element)[0]


def _fb2(data: bytes, path: Path, *, cancel=None) -> Book:
    root = _xml(data, path.name)
    if _local(root.tag) != "FictionBook":
        raise BookError(_("Файл не является книгой FB2"))
    description = _child(root, "description")
    info = _child(description, "title-info") if description is not None else None
    title = _inline(_child(info, "book-title")) if info is not None else ""
    authors = []
    if info is not None:
        for author in _children(info, "author"):
            name = " ".join(filter(None, (_inline(_child(author, part)) for part in ("first-name", "middle-name", "last-name"))))
            authors.append(name or _inline(_child(author, "nickname")))
    bodies = _children(root, "body")
    chapters: list[Chapter] = []
    outline: list[NavigationEntry] = []
    notes: list[tuple[ET.Element, str, int]] = []
    text_chars = 0
    text_chapters = 0
    artwork = _IllustrationStore(cancel)
    binaries: dict[str, ET.Element | None] = {}
    for binary in _children(root, "binary"):
        identifier = binary.get("id", "")
        if identifier:
            binaries[identifier] = None if identifier in binaries else binary

    def binary_bytes(identifier: str) -> bytes | None:
        binary = binaries.get(identifier)
        if binary is None:
            return None
        maximum = ((MAX_ILLUSTRATION_BYTES + 2) // 3) * 4
        parts, count = [], 0
        for part in binary.itertext():
            for start in range(0, len(part), 64 * 1024):
                check_cancel(cancel)
                compact = re.sub(r"\s+", "", part[start:start + 64 * 1024])
                count += len(compact)
                if count > maximum:
                    return None
                parts.append(compact)
        try:
            return base64.b64decode("".join(parts).encode("ascii"), validate=True)
        except (UnicodeError, binascii.Error, ValueError):
            return None

    def load_image(href: str) -> ImageData | None:
        if not href.startswith("#") or len(href) < 2:
            return None
        try:
            identifier = unquote(href[1:], errors="strict")
        except UnicodeError:
            return None
        return artwork.load(identifier, lambda: binary_bytes(identifier))

    def append_chapter(chapter: Chapter) -> int:
        nonlocal text_chars, text_chapters
        text_chars += len(chapter.text)
        if text_chars > MAX_TEXT_CHARS:
            raise BookError(_("Текст книги превышает допустимый размер"))
        chapters.append(chapter)
        if chapter.text:
            text_chapters += 1
        return len(chapters) - 1

    def section(node: ET.Element, default_title: str, level: int, inherited: str = "chapter") -> None:
        source_title = _inline(_child(node, "title"))
        chapter_title = source_title or default_title
        kind = _element_kind(node) or _title_kind(source_title) or inherited
        if kind == "notes":
            notes.append((node, chapter_title, max(0, level)))
            return
        images: list[InlineImage] = []
        text, anchors, _positions = _fb2_render(node, image_loader=load_image, images=images)
        chapter_index = len(chapters)
        entry = None
        if text or images:
            append_chapter(Chapter(chapter_title, text, kind, max(0, level), anchors, images))
        if text or images or _local(node.tag) == "section":
            entry = NavigationEntry(chapter_title, chapter_index, level=max(0, level), kind=kind)
            outline.append(entry)
        for child in _children(node, "section"):
            section(child, _("Раздел {number}").format(number=text_chapters + 1), level + 1, kind)
        if entry is not None and chapter_index == len(chapters):
            outline.remove(entry)
        elif entry is not None and not text and not images and node.get("id"):
            chapters[chapter_index].anchors.setdefault(node.attrib["id"], 0)

    for body in bodies:
        body_kind = _element_kind(body)
        if body_kind == "notes":
            label = _inline(_child(body, "title")) or (_("Комментарии") if body.get("name", "").casefold() == "comments" else _("Примечания"))
            notes.append((body, label, 0))
        else:
            section(body, title or path.stem.removesuffix(".fb2"), -1, body_kind or "chapter")
    # Appending grouped note bodies keeps all existing main chapter indices
    # stable, including when a note section appears inside a main section.
    for node, note_title, level in notes:
        images = []
        text, anchors, positions = _fb2_render(node, include_sections=True, image_loader=load_image, images=images)
        if not text and not images:
            continue
        chapter_index = append_chapter(Chapter(note_title, text, "notes", level, anchors, images))
        outline.append(NavigationEntry(note_title, chapter_index, level=level, kind="notes"))
        number = 0
        def note_entries(parent: ET.Element, depth: int) -> None:
            nonlocal number
            for child in _children(parent, "section"):
                number += 1
                label = _inline(_child(child, "title")) or child.get("id") or _("Примечание {number}").format(number=number)
                outline.append(NavigationEntry(label, chapter_index, positions.get(id(child), 0), depth, "notes"))
                note_entries(child, depth + 1)
        note_entries(node, level + 1)
    if not chapters:
        raise BookError(_("FB2 не содержит доступного текста"))
    chapters, outline = _merge_image_only_chapters(chapters, outline)
    cover = None
    try:
        from .covers import fb2_cover
        cover = fb2_cover(root)
    except Exception:
        pass
    return Book(title or path.stem.removesuffix(".fb2"), ", ".join(filter(None, authors)), chapters, "FB2", outline=outline, cover=cover)


def load_book(path: Path | str, *, cancel=None) -> Book:
    """Load supported text books and fixed-layout documents, raising BookError.

    PDF and DjVu loading reads metadata only. Page text and raster images are
    requested from ``page_document`` as the reader visits each page.
    """
    path = Path(path)
    check_cancel(cancel)
    try:
        size = path.stat().st_size
        if not path.is_file():
            raise BookError(_("Указанный путь не является файлом"))
        if size > file_size_limit(path):
            raise BookError(file_size_error(path))
        suffix = path.suffix.lower()
        if suffix in {".djvu", ".djv"}:
            from .djvu import DjvuDocument, DjvuError

            try:
                document = DjvuDocument(path)
            except DjvuError as exc:
                raise BookError(str(exc)) from exc
            return Book(
                document.title,
                document.author,
                [Chapter(_("Страница {number}").format(number=index + 1), "") for index in range(document.page_count)],
                "DJVU",
                djvu_document=document,
            )
        if suffix == ".pdf":
            from .pdf import PdfDocument, PdfError

            try:
                document = PdfDocument(path)
            except PdfError as exc:
                raise BookError(str(exc)) from exc
            return Book(
                document.title,
                document.author,
                [Chapter(_("Страница {number}").format(number=index + 1), "") for index in range(document.page_count)],
                "PDF",
                document,
            )
        if suffix == ".epub":
            return _epub(path, cancel=cancel)
        if suffix in {".html", ".htm", ".xhtml"}:
            from .markup import load_html
            return load_html(path, cancel=cancel)
        if suffix in {".md", ".markdown"}:
            from .markup import load_markdown
            return load_markdown(path, cancel=cancel)
        if suffix == ".cbz":
            from .cbz import CbzError, load_cbz
            try:
                return load_cbz(path)
            except CbzError as exc:
                raise BookError(str(exc)) from exc
        if suffix == ".zip" and path.name.lower().endswith(".fb2.zip"):
            archive = _Archive(path)
            try:
                names = [name for name in archive.names if name.lower().endswith(".fb2")]
                if len(names) != 1:
                    raise BookError(_("Архив FB2 должен содержать ровно один файл .fb2"))
                return _fb2(archive.read(names[0]), path, cancel=cancel)
            finally:
                archive.close()
        if suffix not in {".fb2", ".txt"}:
            raise BookError(_("Поддерживаются EPUB, FB2, FB2.ZIP, TXT, PDF, DjVu, HTML, Markdown и CBZ"))
        source_path = path.resolve(strict=True)
        with os.fdopen(os.open(source_path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW), "rb") as stream:
            details = os.fstat(stream.fileno())
            if not stat.S_ISREG(details.st_mode):
                raise BookError(_("Указанный путь не является файлом"))
            if details.st_size > MAX_FILE_BYTES:
                raise BookError(file_size_error(path))
            data = stream.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise BookError(_("Книга превышает допустимый размер (64 МиБ)"))
        if suffix == ".fb2":
            return _fb2(data, path, cancel=cancel)
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = data.decode("cp1251")
            except UnicodeDecodeError as exc:
                raise BookError(_("TXT должен быть в кодировке UTF-8 или Windows-1251")) from exc
        if "\x00" in text:
            raise BookError(_("TXT содержит двоичные данные"))
        text = _clean_text(text)
        if not text:
            raise BookError(_("Текстовый файл пуст"))
        return Book(path.stem, "", [Chapter(path.stem, text)], "TXT")
    except BookError:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        raise BookError(_('Не удалось прочитать книгу: {exc}').format(exc=exc)) from exc
