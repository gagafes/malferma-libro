"""Bounded, lazy CBZ pages without extracting archive members to disk.

Only raster PNG, JPEG and optionally WebP reach GdkPixbuf. ZIP directory bounds
are checked before Python allocates ZipInfo objects, image dimensions before
native decoding, and optional PNG/JPEG color metadata is discarded before decoding.
Page indices and rendering follow the PDF/DjVu document contract; CBZ has no
text layer or OCR. The model does not initialize GTK or require a display.
"""

from __future__ import annotations

from contextlib import contextmanager
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import tempfile
import threading
import xml.etree.ElementTree as ET
import zipfile
import zlib

from .covers import CoverData, _jpeg_data, validate_cover
from .i18n import _
from .xmlutil import XMLLimitError, parse_xml


MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_EXPANDED_BYTES = 1024 * 1024 * 1024
MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_IMAGE_DIMENSION = 16384
MAX_IMAGE_PIXELS = 32 * 1024 * 1024
MAX_PAGES = 10_000
MAX_ENTRIES = 20_000
MAX_DIRECTORY_BYTES = 8 * 1024 * 1024
MAX_METADATA_BYTES = 256 * 1024
MAX_COVER_CANDIDATES = 32
MAX_RENDER_DIMENSION = 4096
MAX_RENDER_PIXELS = 12 * 1024 * 1024
MAX_PNG_BYTES = 64 * 1024 * 1024
_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".jpe", ".webp"})
_PNG = b"\x89PNG\r\n\x1a\n"


class CbzError(ValueError):
    """A comic archive or page is unsafe, malformed, or unsupported."""


def _archive_error():
    return _("Не удалось прочитать CBZ: архив повреждён, не поддерживается или превышает допустимые ограничения.")


def _local_file(path):
    try:
        resolved = Path(path).expanduser().resolve(strict=True)
        information = resolved.stat()
        if not stat.S_ISREG(information.st_mode) or not 0 < information.st_size <= MAX_FILE_BYTES:
            raise ValueError("Invalid comic file")
        return resolved, information
    except (OSError, ValueError, RuntimeError) as error:
        raise CbzError(_archive_error()) from error


def _directory_preflight(stream, size, *, max_entries=MAX_ENTRIES,
                         max_directory_bytes=MAX_DIRECTORY_BYTES):
    """Check a conventional single-disk ZIP directory before ZipFile allocation."""
    stream.seek(max(0, size - 65557))
    tail = stream.read(65557)
    position = len(tail)
    while True:
        position = tail.rfind(b"PK\x05\x06", 0, position)
        if position < 0:
            raise ValueError("Missing ZIP directory")
        if position + 22 <= len(tail):
            fields = struct.unpack_from("<4s4H2IH", tail, position)
            if position + 22 + fields[7] == len(tail):
                break
    _, disk, directory_disk, disk_count, count, length, offset, _comment = fields
    end = max(0, size - 65557) + position
    if (disk or directory_disk or disk_count != count or not 1 <= count <= max_entries
            or not 0 < length <= max_directory_bytes or offset + length != end):
        raise ValueError("Unsupported ZIP directory")
    stream.seek(offset)
    directory = stream.read(length)
    if len(directory) != length:
        raise ValueError("Truncated ZIP directory")
    current = entries = 0
    while current < length:
        if current + 46 > length or directory[current:current + 4] != b"PK\x01\x02":
            raise ValueError("Invalid ZIP member")
        name_length, extra_length, comment_length, member_disk = struct.unpack_from("<4H", directory, current + 28)
        following = current + 46 + name_length + extra_length + comment_length
        name = directory[current + 46:current + 46 + name_length]
        if (following > length or member_disk or not 0 < name_length <= 4096
                or b"\x00" in name):
            raise ValueError("Invalid ZIP member name")
        entries += 1
        if entries > max_entries:
            raise ValueError("Too many ZIP members")
        current = following
    if entries != count:
        raise ValueError("ZIP directory count mismatch")
    stream.seek(0)


@contextmanager
def _archive(path):
    try:
        # Nonblocking open lets the same-descriptor check reject a swapped FIFO.
        source_path = Path(path).resolve(strict=True)
        with os.fdopen(os.open(source_path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW), "rb") as stream:
            information = os.fstat(stream.fileno())
            if not stat.S_ISREG(information.st_mode) or not 0 < information.st_size <= MAX_FILE_BYTES:
                raise ValueError("Invalid comic file")
            _directory_preflight(stream, information.st_size)
            with zipfile.ZipFile(stream) as archive:
                yield archive
    except CbzError:
        raise
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, NotImplementedError, EOFError, zlib.error) as error:
        raise CbzError(_archive_error()) from error


def _natural_key(name):
    return tuple((1, int(piece), len(piece)) if piece.isascii() and piece.isdigit() else (0, piece.casefold())
                 for piece in re.split(r"([0-9]+)", name))


def _member_name(name):
    if (not isinstance(name, str) or name.startswith("/") or "\\" in name or "\x00" in name
            or re.match(r"^[A-Za-z]:", name)
            or any(part in {".", ".."} for part in name.split("/"))):
        raise ValueError("Unsafe comic member name")
    return PurePosixPath(name)


def _hidden(path):
    return any(part.startswith(".") or part == "__MACOSX" for part in path.parts)


def _read_member(archive, info, limit):
    if not 0 < info.file_size <= limit or info.flag_bits & 1:
        raise ValueError("Invalid comic member length")
    with archive.open(info) as source:
        data = source.read(limit + 1)
    if len(data) != info.file_size or len(data) > limit:
        raise ValueError("Comic member exceeded its bounds")
    return data


def _metadata(data):
    """ComicInfo is optional; reject declarations before the bounded XML parser."""
    try:
        # Expat otherwise expands internal entity declarations before TreeBuilder
        # can count their text. Removing NULs also catches UTF-16/32 declarations.
        declarations = data.replace(b"\x00", b"").upper()
        if b"<!DOCTYPE" in declarations or b"<!ENTITY" in declarations:
            return "", ""
        root = parse_xml(data, max_nodes=4096, max_depth=32)
        if root.tag.rsplit("}", 1)[-1].casefold() != "comicinfo":
            return "", ""
        fields = {}
        for child in root:
            key = child.tag.rsplit("}", 1)[-1].casefold()
            if key in {"title", "writer"}:
                fields[key] = " ".join("".join(child.itertext()).split())[:1024]
        return fields.get("title", ""), fields.get("writer", "")
    except (ET.ParseError, XMLLimitError, ValueError, LookupError, RecursionError):
        return "", ""


def _dimensions(width, height):
    if (not 0 < width <= MAX_IMAGE_DIMENSION or not 0 < height <= MAX_IMAGE_DIMENSION
            or width * height > MAX_IMAGE_PIXELS):
        raise ValueError("Comic image exceeds pixel limits")
    return width, height


def _png_image(data):
    """Check dimensions/CRC and discard all optional compressed metadata."""
    position, chunks, result, dimensions = 8, 0, [_PNG], None
    has_data = has_palette = False
    decoder = None
    raw_count = next_filter = 0
    while position + 12 <= len(data):
        length = int.from_bytes(data[position:position + 4], "big")
        end = position + 12 + length
        if end > len(data):
            raise ValueError("Truncated PNG chunk")
        kind = data[position + 4:position + 8]
        body = data[position + 8:end - 4]
        chunks += 1
        if (chunks > 20_000 or zlib.crc32(kind + body) & 0xffffffff != int.from_bytes(data[end - 4:end], "big")
                or not all(65 <= value <= 90 or 97 <= value <= 122 for value in kind)):
            raise ValueError("Invalid PNG chunk")
        if chunks == 1 and kind != b"IHDR":
            raise ValueError("Missing PNG image header")
        if kind == b"IHDR":
            if dimensions is not None or length != 13:
                raise ValueError("Invalid PNG image header")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", body)
            depths = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
            if depth not in depths.get(color, ()) or compression or filtering or interlace not in (0, 1):
                raise ValueError("Unsupported PNG image header")
            dimensions = _dimensions(width, height)
            bits = depth * {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
            passes = ((0, 0, 1, 1),) if not interlace else (
                (0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
                (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))
            groups = []
            for x, y, dx, dy in passes:
                columns = max(0, (width - x + dx - 1) // dx)
                rows = max(0, (height - y + dy - 1) // dy)
                if columns and rows:
                    groups.append((rows, (columns * bits + 7) // 8 + 1))
            expected_bytes = sum(count * stride for count, stride in groups)
            remaining_groups = iter(groups)
            remaining_rows, stride = next(remaining_groups)
            decoder = zlib.decompressobj()
        elif kind == b"PLTE":
            if has_palette or not 0 < length <= 768 or length % 3:
                raise ValueError("Invalid PNG palette")
            has_palette = True
        elif kind == b"IDAT":
            has_data = has_data or bool(length)
            pending = body
            while pending:
                previous = len(pending)
                raw = decoder.decompress(pending, 65536)
                pending = decoder.unconsumed_tail
                end_count = raw_count + len(raw)
                if end_count > expected_bytes or decoder.unused_data:
                    raise ValueError("PNG pixel stream exceeded its geometry")
                while next_filter < end_count:
                    if raw[next_filter - raw_count] > 4:
                        raise ValueError("Invalid PNG row filter")
                    next_filter += stride
                    remaining_rows -= 1
                    if remaining_rows == 0:
                        following = next(remaining_groups, None)
                        if following is not None:
                            remaining_rows, stride = following
                raw_count = end_count
                if pending and not raw and len(pending) == previous:
                    raise ValueError("Invalid PNG compressed pixels")
        elif kind == b"IEND":
            if (length or end != len(data) or dimensions is None or not has_data
                    or color == 3 and not has_palette or not decoder.eof or raw_count != expected_bytes):
                raise ValueError("Invalid PNG image end")
            result.append(data[position:end])
            return b"".join(result), "png", dimensions
        elif not kind[0] & 0x20 and kind not in {b"PLTE"}:
            raise ValueError("Unsupported PNG critical chunk")
        if kind in {b"IHDR", b"PLTE", b"IDAT"} or kind == b"tRNS" and length <= 256:
            result.append(data[position:end])
        position = end
    raise ValueError("Incomplete PNG image")


def _jpeg_image(data):
    image = _jpeg_data(data, max_dimension=MAX_IMAGE_DIMENSION, max_pixels=MAX_IMAGE_PIXELS)
    if image is None:
        raise ValueError("Invalid JPEG image")
    return image[0], "jpeg", image[1]


def _webp_size(data):
    if len(data) < 20 or int.from_bytes(data[4:8], "little") + 8 != len(data):
        raise ValueError("Invalid WebP container")
    position, chunks, canvas, frame = 12, 0, None, None
    while position + 8 <= len(data):
        kind = data[position:position + 4]
        length = int.from_bytes(data[position + 4:position + 8], "little")
        end = position + 8 + length
        chunks += 1
        if end > len(data) or chunks > 20_000:
            raise ValueError("Truncated WebP image")
        body = data[position + 8:end]
        if kind == b"VP8X":
            if position != 12 or length != 10 or body[0] & ~0x3c or any(body[1:4]):
                raise ValueError("Unsupported or animated WebP canvas")
            canvas = _dimensions(1 + int.from_bytes(body[4:7], "little"),
                                 1 + int.from_bytes(body[7:10], "little"))
        elif kind in {b"ANIM", b"ANMF"}:
            raise ValueError("Animated WebP is unsupported")
        elif kind in {b"VP8 ", b"VP8L"}:
            if frame is not None:
                raise ValueError("Multiple WebP pixel streams")
            if kind == b"VP8 " and length >= 10 and body[3:6] == b"\x9d\x01\x2a":
                frame = _dimensions(int.from_bytes(body[6:8], "little") & 0x3fff,
                                    int.from_bytes(body[8:10], "little") & 0x3fff)
            elif kind == b"VP8L" and length >= 5 and body[0] == 0x2f:
                bits = int.from_bytes(body[1:5], "little")
                if bits >> 29:
                    raise ValueError("Unsupported WebP version")
                frame = _dimensions(1 + (bits & 0x3fff), 1 + ((bits >> 14) & 0x3fff))
            else:
                raise ValueError("Invalid WebP pixel header")
        position = end + (length & 1)
    if position != len(data) or canvas is None and frame is None or canvas is not None and frame is not None and canvas != frame:
        raise ValueError("Inconsistent WebP geometry")
    return canvas or frame


def _image(data):
    if data.startswith(_PNG):
        return _png_image(data)
    if data.startswith(b"\xff\xd8"):
        return _jpeg_image(data)
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return data, "webp", _webp_size(data)
    raise ValueError("Unsupported comic image")


def _render_size(width, height, scale, fit_width, maximum=MAX_RENDER_DIMENSION,
                 pixels=MAX_RENDER_PIXELS):
    try:
        if isinstance(scale, bool):
            raise ValueError("Boolean scale")
        scale = float(scale)
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError("Invalid scale")
        if fit_width is not None and (type(fit_width) is not int or fit_width < 1):
            raise ValueError("Invalid fit width")
        factor = scale if fit_width is None else fit_width / width * scale
        desired = max(width, height) * factor
    except (TypeError, ValueError, OverflowError) as error:
        if isinstance(error, OverflowError):
            desired = math.inf
        else:
            raise CbzError(_("Недопустимые параметры страницы CBZ.")) from error
    ratio = min(width, height) / max(width, height)
    cap = min(maximum, int(math.sqrt(pixels / ratio)))
    longest = max(1, min(cap, math.ceil(desired) if desired < cap else cap))
    if width >= height:
        return longest, max(1, min(maximum, math.floor(longest * ratio)))
    return max(1, min(maximum, math.floor(longest * ratio))), longest


def _decode(data, kind, dimensions, target):
    loader, closed = None, False
    try:
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf

        loader = GdkPixbuf.PixbufLoader.new_with_type(kind)
        valid = [True]
        def prepared(image_loader, width, height):
            valid[0] = (width, height) == dimensions
            image_loader.set_size(*target if valid[0] else (1, 1))
        loader.connect("size-prepared", prepared)
        loader.write(data)
        loader.close()
        closed = True
        image = loader.get_pixbuf()
        if not valid[0] or image is None or (image.get_width(), image.get_height()) != target:
            raise ValueError("Comic decoder changed image geometry")
        return image
    except Exception as error:
        raise CbzError(_("Не удалось обработать изображение страницы CBZ.")) from error
    finally:
        if loader is not None and not closed:
            try:
                loader.close()
            except Exception:
                pass


class CbzDocument:
    """A fixed-page ZIP comic; metadata is read once and raster pages on demand."""

    def __init__(self, path):
        self.path, details = _local_file(path)
        self._file_size = details.st_size
        self._sizes = {}
        self._lock = threading.RLock()
        self.title, self.author = self.path.stem, ""
        self._members = []
        with _archive(self.path) as archive:
            seen, expanded, metadata = set(), 0, []
            for info in archive.infolist():
                name = _member_name(info.filename)
                if info.filename in seen or info.flag_bits & 1 or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise CbzError(_archive_error())
                seen.add(info.filename)
                expanded += info.file_size
                if expanded > MAX_EXPANDED_BYTES or info.file_size < 0:
                    raise CbzError(_archive_error())
                mode = info.external_attr >> 16
                if mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise CbzError(_archive_error())
                if info.is_dir() or _hidden(name):
                    continue
                if name.suffix.casefold() in _EXTENSIONS:
                    if not 0 < info.file_size <= MAX_IMAGE_BYTES:
                        raise CbzError(_archive_error())
                    self._members.append(info.filename)
                elif name.name.casefold() == "comicinfo.xml" and 0 < info.file_size <= MAX_METADATA_BYTES:
                    metadata.append(info)
            if not self._members:
                raise CbzError(_("В архиве CBZ нет поддерживаемых изображений."))
            if len(self._members) > MAX_PAGES:
                raise CbzError(_archive_error())
            self._members.sort(key=lambda name: (_natural_key(name), name))
            if metadata:
                chosen = min(metadata, key=lambda info: (len(PurePosixPath(info.filename).parts), _natural_key(info.filename)))
                try:
                    title, author = _metadata(_read_member(archive, chosen, MAX_METADATA_BYTES))
                    self.title, self.author = title or self.title, author
                except (ValueError, OSError, zipfile.BadZipFile):
                    pass
        self._members = tuple(self._members)
        self.page_count = len(self._members)

    def with_path(self, path):
        target, information = _local_file(path)
        if information.st_size != self._file_size:
            raise CbzError(_archive_error())
        result = object.__new__(type(self))
        result.path, result._file_size = target, self._file_size
        result.title, result.author, result.page_count = self.title, self.author, self.page_count
        result._members, result._lock = self._members, threading.RLock()
        with self._lock:
            result._sizes = dict(self._sizes)
        return result

    def _check_index(self, index):
        if type(index) is not int or not 0 <= index < self.page_count:
            raise CbzError(_("Недопустимые параметры страницы CBZ."))

    def _page_image(self, index):
        self._check_index(index)
        try:
            with _archive(self.path) as archive:
                data = _read_member(archive, archive.getinfo(self._members[index]), MAX_IMAGE_BYTES)
            image = _image(data)
            with self._lock:
                self._sizes[index] = image[2]
            return image
        except CbzError:
            raise
        except (ValueError, KeyError, OSError, struct.error, zlib.error) as error:
            raise CbzError(_("Не удалось обработать изображение страницы CBZ.")) from error

    def page_size(self, index):
        self._check_index(index)
        with self._lock:
            size = self._sizes.get(index)
        return size if size is not None else self._page_image(index)[2]

    def page_text(self, index):
        self._check_index(index)
        return ""

    def render_page(self, index, output, *, scale=1.0, fit_width=None):
        self._check_index(index)
        data, kind, dimensions = self._page_image(index)
        target_size = _render_size(*dimensions, scale, fit_width)
        image = _decode(data, kind, dimensions, target_size)
        try:
            target = Path(output).expanduser().resolve()
            if target == self.path:
                raise CbzError(_("Нельзя заменить файл книги изображением страницы"))
            with tempfile.TemporaryDirectory(prefix=".cbz-render-", dir=target.parent) as directory:
                rendered = Path(directory) / "page.png"
                image.savev(str(rendered), "png", [], [])
                if not 24 <= rendered.stat().st_size <= MAX_PNG_BYTES:
                    raise ValueError("Invalid rendered comic page")
                rendered.replace(target)
            return target
        except CbzError:
            raise
        except Exception as error:
            raise CbzError(_("Не удалось сохранить изображение страницы CBZ.")) from error


def extract_cover(source):
    """First decodable of at most 32 candidates, scaled and revalidated."""
    try:
        document = source if isinstance(source, CbzDocument) else CbzDocument(source)
        for index in range(min(document.page_count, MAX_COVER_CANDIDATES)):
            try:
                data, kind, dimensions = document._page_image(index)
                target = _render_size(*dimensions, min(1.0, 1024 / max(dimensions)), None,
                                      maximum=1024, pixels=1024 * 1024)
                image = _decode(data, kind, dimensions, target)
                success, pixels = image.save_to_bufferv("png", [], [])
                if success:
                    cover = validate_cover(bytes(pixels), "image/png")
                    if cover is not None:
                        return cover
            except CbzError:
                continue
    except (CbzError, OSError, ValueError):
        pass
    return None


def load_cbz(path):
    """Create the common Book model without extracting text or other pages."""
    from .books import Book, Chapter, NavigationEntry

    document = CbzDocument(path)
    chapters = [Chapter(_("Страница {number}").format(number=index + 1), "", kind="page")
                for index in range(document.page_count)]
    outline = [NavigationEntry(chapter.title, index, kind="page") for index, chapter in enumerate(chapters)]
    return Book(document.title, document.author, chapters, "CBZ", outline=outline,
                cover=extract_cover(document), cbz_document=document)
