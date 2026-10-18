"""Bounded local HTML/XHTML and CommonMark reading without a web engine.

HTML is parsed as inert text: scripts, styles and embedded documents are not
executed or fetched. CommonMark uses markdown-it-py with raw HTML disabled;
the generated markup goes through the same inert text reader. No parser
extension or external resource loader is enabled.
"""

from __future__ import annotations

import codecs
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
import re
import unicodedata
import uuid

from .books import (
    Book, BookError, Chapter, NavigationEntry, MAX_FILE_BYTES, MAX_TEXT_CHARS,
    MAX_XML_DEPTH, MAX_XML_NODES, _TextHTML, _clean_positions, _semantic_kind,
    _title_kind, _SAFE_DOCTYPE,
)
from .i18n import _


MAX_HEADINGS = 10000
MAX_METADATA_CHARS = 4096
_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})
_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_AUTOCLOSE = frozenset({"p", "li", "dt", "dd", "tr", "td", "th", "option"})
_DECLARATION = re.compile(r"<!--|<!\[CDATA\[|<!\s*(?P<kind>ENTITY|DOCTYPE)\b", re.I)
_SAFE_TEXT_DOCTYPE = re.compile(_SAFE_DOCTYPE.pattern.decode("ascii"), re.I)
_ENCODING = re.compile(br"<\?xml[^>]{0,256}?encoding\s*=\s*['\"]([^'\"]{1,40})", re.I)
_TEXT_ENCODINGS = frozenset({"utf-8", "utf-16", "utf-16-le", "utf-16-be", "utf-32", "utf-32-le", "utf-32-be", "cp1251", "cp1252", "iso8859-1", "koi8-r"})


def _too_complex():
    raise BookError(_("Файл разметки слишком сложный."))


class _CharsetHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.charset = ""

    def handle_starttag(self, tag, attrs):
        if tag != "meta" or self.charset:
            return
        attributes = dict(attrs)
        self.charset = attributes.get("charset") or ""
        if not self.charset and (attributes.get("http-equiv") or "").casefold() == "content-type":
            match = re.search(r"charset\s*=\s*['\"]?\s*([A-Za-z0-9_-]{1,40})", attributes.get("content") or "", re.I)
            if match:
                self.charset = match[1]


def _read(path: Path) -> bytes:
    try:
        if not path.is_file():
            raise OSError("Not a regular file")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise BookError(_("Книга превышает допустимый размер (64 МиБ)"))
        with path.open("rb") as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise BookError(_("Книга превышает допустимый размер (64 МиБ)"))
        return data
    except OSError as error:
        raise BookError(_("Не удалось прочитать книгу: {exc}").format(exc=error)) from error


def _decode(data: bytes, label: str, *, html: bool) -> str:
    try:
        if data.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
            text = data.decode("utf-32")
        elif data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            text = data.decode("utf-16")
        elif data.startswith(codecs.BOM_UTF8):
            text = data.decode("utf-8-sig")
        elif data.startswith(b"<\0"):
            text = data.decode("utf-16-le")
        elif data.startswith(b"\0<"):
            text = data.decode("utf-16-be")
        else:
            declared = ""
            if html:
                xml = _ENCODING.match(data.lstrip()[:1024])
                if xml:
                    declared = xml[1].decode("ascii")
                else:
                    sniffer = _CharsetHTML()
                    sniffer.feed(data[:8192].decode("ascii", errors="ignore"))
                    declared = sniffer.charset
            if declared:
                encoding = codecs.lookup(declared).name
                if encoding not in _TEXT_ENCODINGS:
                    raise LookupError("Not a supported text encoding")
                text = data.decode(encoding)
            else:
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    text = data.decode("cp1251")
    except (UnicodeError, LookupError, AssertionError, ValueError) as error:
        raise BookError(_("{label}: не удалось прочитать текст.").format(label=label)) from error
    if "\0" in text:
        raise BookError(_("Файл разметки содержит двоичные данные."))
    if len(text) > MAX_TEXT_CHARS:
        raise BookError(_("Текст книги превышает допустимый размер"))
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _check_declarations(text: str, label: str) -> None:
    position = 0
    while declaration := _DECLARATION.search(text, position):
        kind = declaration.group("kind")
        if kind is None:
            closing = "-->" if declaration.group() == "<!--" else "]]>"
            end = text.find(closing, declaration.end())
            if end < 0:
                return
            position = end + len(closing)
            continue
        if kind.upper() == "ENTITY" or (safe := _SAFE_TEXT_DOCTYPE.match(text, declaration.start())) is None:
            raise BookError(_("{label}: объявления DTD и сущностей XML запрещены").format(label=label))
        position = safe.end()


def _clean_protected(text: str, positions: dict[object, int], spans: list[tuple[int, int]]):
    """Normalize prose while retaining preformatted text and its exact anchors."""
    if not spans:
        return _clean_positions(text, positions)
    for _attempt in range(8):
        prefix = "\ufdd0" + uuid.uuid4().hex + ":"
        if prefix not in text:
            break
    else:
        _too_complex()
    ordered = sorted(positions.items(), key=lambda item: item[1])
    mapped, inside, parts, markers = {}, {}, [], []
    cursor = length = index = 0
    for number, (start, end) in enumerate(spans):
        if end <= start:
            continue
        while index < len(ordered) and ordered[index][1] < start:
            key, offset = ordered[index]
            mapped[key] = length + offset - cursor
            index += 1
        before = text[cursor:start]
        parts.append(before)
        length += len(before)
        marker = prefix + str(number) + "\ufdd1"
        while index < len(ordered) and ordered[index][1] < end:
            key, offset = ordered[index]
            mapped[key] = length
            inside[key] = (number, offset - start)
            index += 1
        parts.append(marker)
        markers.append((number, marker, text[start:end]))
        length += len(marker)
        cursor = end
    while index < len(ordered):
        key, offset = ordered[index]
        mapped[key] = length + offset - cursor
        index += 1
    parts.append(text[cursor:])
    cleaned, mapped = _clean_positions("".join(parts), mapped)
    ordered = sorted(mapped.items(), key=lambda item: item[1])
    parts, result = [], {}
    cursor = length = index = 0
    for number, marker, content in markers:
        start = cleaned.find(marker, cursor)
        if start < 0:
            _too_complex()
        end = start + len(marker)
        while index < len(ordered) and ordered[index][1] < start:
            key, offset = ordered[index]
            result[key] = length + offset - cursor
            index += 1
        before = cleaned[cursor:start]
        parts.append(before)
        length += len(before)
        while index < len(ordered) and ordered[index][1] < end:
            key = ordered[index][0]
            relative = inside[key][1] if key in inside and inside[key][0] == number else 0
            result[key] = length + relative
            index += 1
        parts.append(content)
        length += len(content)
        cursor = end
    while index < len(ordered):
        key, offset = ordered[index]
        result[key] = length + offset - cursor
        index += 1
    parts.append(cleaned[cursor:])
    return "".join(parts), result


@dataclass
class _Heading:
    title: str
    position: object
    level: int
    kind: str


class _MarkupHTML(_TextHTML):
    _hidden = _TextHTML._hidden | {"iframe", "object", "canvas"}

    def __init__(self):
        super().__init__()
        self.nodes = 0
        self.nesting: list[str] = []
        self.suppressed: list[str] = []
        self.headings: list[_Heading] = []
        self.positions: dict[object, int] = {}
        self.capture = None
        self.pre_start = None
        self.pre_spans = []
        self.title_parts = []
        self.in_title = False
        self.authors = []
        self.slug_counts = {}

    def _append(self, value):
        super()._append(value)
        if self.length > MAX_TEXT_CHARS:
            raise BookError(_("Текст книги превышает допустимый размер"))

    def _finish_heading(self):
        if self.capture is None:
            return
        tag, position, parts, kind, anchor = self.capture
        title = " ".join("".join(parts).split())[:MAX_METADATA_CHARS]
        if title:
            if len(self.headings) >= MAX_HEADINGS:
                _too_complex()
            self.headings.append(_Heading(title, position, int(tag[1]) - 1, kind or _title_kind(title) or "chapter"))
            if not anchor:
                slug = re.sub(r"[^\w\s-]", "", unicodedata.normalize("NFKC", title).casefold())
                slug = re.sub(r"\s+", "-", slug).strip("-") or "section"
                base, number = slug, self.slug_counts.get(slug, 1)
                while slug in self.anchors:
                    number += 1
                    slug = base + "-" + str(number)
                self.slug_counts[base] = number
                self.anchors[slug] = self.positions[position]
                self.anchor_kinds[slug] = kind
        self.capture = None

    def handle_starttag(self, tag, attrs):
        # HTML permits an omitted head wrapper and an omitted </head> before
        # body content. Finish metadata without unhiding script/template data.
        if tag == "title" and "head" not in self.nesting and "body" not in self.nesting and not self.hidden and not self.main_text:
            self.handle_starttag("head", [])
        head_content = {"html", "head", "base", "link", "meta", "title", "style", "script", "noscript", "template"}
        if self.hidden == ["head"] and tag not in head_content:
            if self.in_title:
                self.handle_endtag("title")
            self.handle_endtag("head")
        if self.nesting and ((tag in _AUTOCLOSE and self.nesting[-1] == tag)
                             or (tag in _HEADING_TAGS and self.nesting[-1] in _HEADING_TAGS)):
            self.handle_endtag(self.nesting[-1])
        self.nodes += 1
        if self.nodes > MAX_XML_NODES:
            _too_complex()
        if tag not in _VOID:
            self.nesting.append(tag)
            if len(self.nesting) > MAX_XML_DEPTH:
                _too_complex()
        attributes = dict(attrs)
        if tag == "title" and "head" in self.nesting:
            self.in_title = True
        if tag == "meta":
            name = (attributes.get("name") or attributes.get("property") or "").casefold()
            author = attributes.get("content") or ""
            if name in {"author", "dc.creator", "dcterms.creator", "article:author"} and author.strip():
                value = " ".join(author.split())[:MAX_METADATA_CHARS]
                if value not in self.authors and len(self.authors) < 32:
                    self.authors.append(value)
        if self.suppressed:
            if tag not in _VOID:
                self.suppressed.append(tag)
            return
        style = (attributes.get("style") or "").replace(" ", "").casefold()
        if "hidden" in attributes or (attributes.get("aria-hidden") or "").casefold() == "true" or "display:none" in style or "visibility:hidden" in style:
            if tag not in _VOID:
                self.suppressed.append(tag)
            return
        was_hidden = bool(self.hidden)
        if tag in _HEADING_TAGS and not was_hidden:
            self._finish_heading()
        super().handle_starttag(tag, attrs)
        if self.hidden:
            return
        if tag == "pre" and self.pre_depth == 1:
            self.pre_start = self.length
        if tag in _HEADING_TAGS:
            position = ("heading", self.nodes)
            self.positions[position] = self.length
            kind = self.elements[-1][1] if self.elements else ""
            self.capture = (tag, position, [], kind, attributes.get("id"))
        if tag == "img" and attributes.get("alt"):
            self.handle_data(attributes["alt"])

    def handle_endtag(self, tag):
        if self.suppressed:
            if tag in self.suppressed:
                index = len(self.suppressed) - 1 - self.suppressed[::-1].index(tag)
                del self.suppressed[index:]
        else:
            if self.capture is not None and self.capture[0] == tag:
                self._finish_heading()
            if tag == "pre" and self.pre_depth == 1 and self.pre_start is not None:
                self.pre_spans.append((self.pre_start, self.length))
                self.pre_start = None
            super().handle_endtag(tag)
        if tag == "title":
            self.in_title = False
        if tag in self.nesting:
            index = len(self.nesting) - 1 - self.nesting[::-1].index(tag)
            del self.nesting[index:]

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data)
        if self.suppressed:
            return
        if self.capture is not None and not self.hidden:
            self.capture[2].append(data)
        super().handle_data(data)

    def finish(self):
        self._finish_heading()
        if self.pre_start is not None:
            self.pre_spans.append((self.pre_start, self.length))
        positions = self.positions | self.anchors
        return _clean_protected("".join(self.parts), positions, self.pre_spans)


def _book_from_html(text: str, path: Path, format_name: str) -> Book:
    _check_declarations(text, path.name)
    parser = _MarkupHTML()
    try:
        parser.feed(text)
        parser.close()
        rendered, positions = parser.finish()
    except BookError:
        raise
    except (ValueError, RecursionError, AssertionError) as error:
        raise BookError(_("{label}: не удалось прочитать текст.").format(label=path.name)) from error
    if not rendered.strip():
        raise BookError(_("Файл не содержит доступного текста."))
    title = " ".join("".join(parser.title_parts).split())[:MAX_METADATA_CHARS]
    title = title or (parser.headings[0].title if parser.headings else path.stem)
    chapter_title = parser.headings[0].title if parser.headings else title
    kind = parser.root_kind or ("notes" if parser.note_text and not parser.main_text else "chapter")
    anchors = {key: offset for key, offset in positions.items() if isinstance(key, str)}
    chapter = Chapter(chapter_title, rendered, kind=kind, anchors=anchors)
    outline = [NavigationEntry(heading.title, 0, positions[heading.position], heading.level, heading.kind)
               for heading in parser.headings]
    if not outline:
        outline = [NavigationEntry(chapter_title, 0, kind=kind)]
    return Book(title, ", ".join(parser.authors), [chapter], format_name, outline=outline)


def load_html(path: Path | str) -> Book:
    """Load HTML/HTM/XHTML as text; no web engine or external resource access."""
    path = Path(path)
    return _book_from_html(_decode(_read(path), path.name, html=True), path, "HTML")


def load_markdown(path: Path | str) -> Book:
    """Read standard CommonMark, with raw HTML disabled and no extensions."""
    path = Path(path)
    text = _decode(_read(path), path.name, html=False)
    escaped_size = len(text) + 4 * text.count("&") + 3 * (text.count("<") + text.count(">")) + 5 * text.count('"')
    if escaped_size > MAX_TEXT_CHARS:
        raise BookError(_("Текст книги превышает допустимый размер"))
    if text.count("\n") > MAX_XML_NODES:
        _too_complex()
    try:
        from markdown_it import MarkdownIt
    except ImportError as error:
        raise BookError(_("Для чтения Markdown установите пакет python3-markdown-it.")) from error
    parser = MarkdownIt("commonmark", {"html": False, "maxNesting": MAX_XML_DEPTH})
    # Each parser instance has its own token sink and budget. Enforce it at
    # append time, including inline/image subparsers, before an adversarial
    # single paragraph can materialize millions of tokens or delimiter records.
    remaining = [MAX_XML_NODES]

    class BudgetTokens(list):
        def append(self, token):
            if remaining[0] <= 0:
                _too_complex()
            remaining[0] -= 1
            super().append(token)

        def extend(self, tokens):
            for token in tokens:
                self.append(token)

    block_parse, inline_parse = parser.block.parse, parser.inline.parse

    def bounded_block(source, markdown, environment, out_tokens):
        bounded = BudgetTokens()
        result = block_parse(source, markdown, environment, bounded)
        out_tokens.extend(bounded)
        return out_tokens if result is not None else None

    def bounded_inline(source, markdown, environment, out_tokens):
        bounded = BudgetTokens()
        inline_parse(source, markdown, environment, bounded)
        out_tokens.extend(bounded)
        return out_tokens

    parser.block.parse, parser.inline.parse = bounded_block, bounded_inline
    try:
        tokens = parser.parse(text)
        rendered = parser.renderer.render(tokens, parser.options, {})
    except (RecursionError, ValueError) as error:
        if isinstance(error, BookError):
            raise
        raise BookError(_("{label}: не удалось прочитать текст.").format(label=path.name)) from error
    if len(rendered) > MAX_TEXT_CHARS:
        raise BookError(_("Текст книги превышает допустимый размер"))
    return _book_from_html(rendered, path, "Markdown")
