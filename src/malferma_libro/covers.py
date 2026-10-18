"""Best-effort embedded covers, bounded image data and an atomic local cache.

No network access or GTK initialization takes place in this module. Untrusted
SVG and other executable/vector cover formats are deliberately not decoded.
Thumbnail decoding is available separately through a lazy GdkPixbuf import.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import posixpath
import re
import struct
import tempfile
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import zlib


MAX_COVER_BYTES = 4 * 1024 * 1024
MAX_COVER_DIMENSION = 4096
MAX_COVER_PIXELS = 4 * 1024 * 1024
MAX_COVER_XML_BYTES = 1024 * 1024
_PNG = b"\x89PNG\r\n\x1a\n"
_XML_BASE = "{http://www.w3.org/XML/1998/namespace}base"
_XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
_JPEG_SOF = frozenset({0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                       0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF})


@dataclass(frozen=True)
class CoverData:
    data: bytes
    mime_type: str


def _dimensions(width, height):
    return (0 < width <= MAX_COVER_DIMENSION and 0 < height <= MAX_COVER_DIMENSION
            and width * height <= MAX_COVER_PIXELS)


def _png_rows(width, height, depth, color, interlace):
    bits = depth * {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
    passes = ((0, 0, 1, 1),) if not interlace else (
        (0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
        (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2),
    )
    rows = []
    for x, y, dx, dy in passes:
        columns = max(0, (width - x + dx - 1) // dx)
        count = max(0, (height - y + dy - 1) // dy)
        if columns and count:
            rows.append((count, (columns * bits + 7) // 8 + 1))
    return rows


def _png_data(data):
    if not data.startswith(_PNG):
        return None
    position, chunks, output, dimensions = 8, 0, [_PNG], None
    has_data = has_palette = False
    decoder = None
    raw_count = next_filter = 0
    while position + 12 <= len(data):
        chunks += 1
        if chunks > 10_000:
            return None
        length = int.from_bytes(data[position:position + 4], "big")
        end = position + length + 12
        if end > len(data):
            return None
        kind = data[position + 4:position + 8]
        body = data[position + 8:position + 8 + length]
        crc = int.from_bytes(data[end - 4:end], "big")
        if (len(kind) != 4 or not all(65 <= value <= 90 or 97 <= value <= 122 for value in kind)
                or zlib.crc32(kind + body) & 0xFFFFFFFF != crc):
            return None
        if chunks == 1 and kind != b"IHDR":
            return None
        if kind == b"IHDR":
            if dimensions is not None or length != 13:
                return None
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", body)
            valid_depths = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
            if (not _dimensions(width, height) or depth not in valid_depths.get(color, ())
                    or compression != 0 or filtering != 0 or interlace not in (0, 1)):
                return None
            dimensions = width, height
            groups = _png_rows(width, height, depth, color, interlace)
            expected_bytes = sum(count * stride for count, stride in groups)
            remaining_groups = iter(groups)
            remaining_rows, stride = next(remaining_groups)
            decoder = zlib.decompressobj()
        elif kind == b"PLTE":
            if has_palette or not 0 < length <= 768 or length % 3:
                return None
            has_palette = True
        elif kind == b"IDAT":
            has_data = has_data or length > 0
            try:
                raw = decoder.decompress(body, expected_bytes - raw_count + 1)
            except zlib.error:
                return None
            end_count = raw_count + len(raw)
            if end_count > expected_bytes or decoder.unused_data:
                return None
            while next_filter < end_count:
                if raw[next_filter - raw_count] > 4:
                    return None
                next_filter += stride
                remaining_rows -= 1
                if remaining_rows == 0:
                    following = next(remaining_groups, None)
                    if following is not None:
                        remaining_rows, stride = following
            raw_count = end_count
        elif kind == b"IEND":
            if (length or not has_data or end != len(data) or (color == 3 and not has_palette)
                    or not decoder.eof or raw_count != expected_bytes):
                return None
            output.append(data[position:end])
            return b"".join(output), dimensions
        elif not kind[0] & 0x20:
            return None
        # Do not pass compressed text, ICC or other optional metadata to the
        # decoder. Cover thumbnails need pixels and transparency, not metadata
        # that could independently expand far beyond the bounded image size.
        if kind in {b"IHDR", b"PLTE", b"IDAT"} or (kind == b"tRNS" and length <= 256):
            output.append(data[position:end])
        position = end
    return None


def _jpeg_dimensions(data):
    if not data.startswith(b"\xff\xd8"):
        return None
    position, dimensions, entropy, saw_scan = 2, None, False, False
    while position < len(data):
        if data[position] != 0xFF:
            if not entropy:
                return None
            position = data.find(b"\xff", position)
            if position < 0:
                return None
        while position < len(data) and data[position] == 0xFF:
            position += 1
        if position >= len(data):
            return None
        marker = data[position]
        position += 1
        if marker == 0:
            if not entropy:
                return None
            continue
        if marker in range(0xD0, 0xD8) or marker == 0x01:
            continue
        if marker == 0xD9:
            return dimensions if dimensions and saw_scan and position == len(data) else None
        if marker == 0xD8 or position + 2 > len(data):
            return None
        length = int.from_bytes(data[position:position + 2], "big")
        if length < 2 or position + length > len(data):
            return None
        if marker in _JPEG_SOF:
            if length < 8 or dimensions is not None:
                return None
            precision, height, width, components = struct.unpack(">BHHB", data[position + 2:position + 8])
            if (precision != 8 or components not in (1, 3, 4) or length != 8 + components * 3
                    or not _dimensions(width, height)):
                return None
            dimensions = width, height
        if marker == 0xDA:
            if dimensions is None or length < 6:
                return None
            saw_scan = True
            entropy = True
        else:
            entropy = False
        position += length
    return None


def validate_cover(data: bytes, mime_type: str | None = None) -> CoverData | None:
    """Accept bounded PNG/JPEG bytes, deriving their MIME from actual content.

    A server's MIME is only a hint, never permission to decode another format.
    Structural validation precedes decoding; malformed pixel streams are also
    rejected by ``load_thumbnail``. PNG metadata is removed before caching.
    """
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_COVER_BYTES:
        return None
    png = _png_data(data)
    if png is not None:
        return CoverData(png[0], "image/png")
    if _jpeg_dimensions(data) is not None:
        return CoverData(data, "image/jpeg")
    return None


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _resolve(base, href):
    url = urlsplit(href)
    if url.scheme or url.netloc:
        raise ValueError("External cover reference")
    path = unquote(url.path, errors="strict")
    if "\\" in path or "\x00" in path or path.startswith("/"):
        raise ValueError("Invalid archive reference")
    if not path:
        return base
    directory = base if base.endswith("/") else posixpath.dirname(base)
    result = posixpath.normpath(posixpath.join(directory, path))
    if result == ".." or result.startswith(("../", "/")):
        raise ValueError("Archive reference escapes its root")
    if result == ".":
        return ""
    return result + ("/" if path.endswith("/") or path in {".", ".."} else "")


def _walk_bases(node, base):
    try:
        if node.get(_XML_BASE):
            base = _resolve(base, node.get(_XML_BASE))
    except (UnicodeError, ValueError):
        return
    yield node, base
    for child in node:
        yield from _walk_bases(child, base)


def _archive_read(archive, name, limit):
    if name.endswith("/"):
        return None
    try:
        native = getattr(archive, "zip", archive)
        if hasattr(native, "getinfo") and hasattr(native, "open"):
            entry = native.getinfo(name)
            if not 0 < entry.file_size <= limit or entry.flag_bits & 1:
                return None
            with native.open(entry) as stream:
                data = stream.read(limit + 1)
        else:
            data = archive.read(name)
        return data if 0 < len(data) <= limit else None
    except Exception:
        return None


def _archive_cover(archive, path):
    data = _archive_read(archive, path, MAX_COVER_BYTES)
    return validate_cover(data) if data is not None else None


def epub_cover(archive, package_root: ET.Element, opf_dir: str) -> CoverData | None:
    """Read EPUB 3/2 cover references without parsing the book's chapters."""
    try:
        base = opf_dir.rstrip("/") + "/" if opf_dir else ""
        nodes = tuple(_walk_bases(package_root, base))
        manifest = {node.get("id"): (node, node_base) for node, node_base in nodes
                    if _local(node.tag) == "item" and node.get("id")}
        candidates = [(node, node_base) for node, node_base in manifest.values()
                      if "cover-image" in node.get("properties", "").split()]
        for node, _node_base in nodes:
            if (_local(node.tag) == "meta" and node.get("name", "").lower() == "cover"
                    and node.get("content") in manifest):
                candidates.append(manifest[node.get("content")])
        visited = set()
        for node, node_base in candidates:
            try:
                path = _resolve(node_base, node.get("href", ""))
            except (UnicodeError, ValueError):
                continue
            if path not in visited:
                visited.add(path)
                cover = _archive_cover(archive, path)
                if cover is not None:
                    return cover
        from .books import _xml

        for node, node_base in nodes:
            if _local(node.tag) != "reference" or "cover" not in node.get("type", "").split():
                continue
            try:
                path = _resolve(node_base, node.get("href", ""))
                cover = _archive_cover(archive, path)
                if cover is not None:
                    return cover
                data = _archive_read(archive, path, MAX_COVER_XML_BYTES)
                if data is None:
                    continue
                root = _xml(data, path, allow_doctype=True)
                for image, image_base in _walk_bases(root, path):
                    if _local(image.tag) != "img" or not image.get("src"):
                        continue
                    try:
                        cover = _archive_cover(archive, _resolve(image_base, image.get("src")))
                    except (UnicodeError, ValueError):
                        continue
                    if cover is not None:
                        return cover
            except Exception:
                continue
    except Exception:
        pass
    return None


def fb2_cover(root: ET.Element) -> CoverData | None:
    """Decode only the title-info coverpage's embedded base64 image binary."""
    try:
        description = next((node for node in root if _local(node.tag) == "description"), None)
        if description is None:
            return None
        info = next((node for node in description if _local(node.tag) == "title-info"), None)
        if info is None:
            return None
        page = next((node for node in info if _local(node.tag) == "coverpage"), None)
        if page is None:
            return None
        for image in page.iter():
            if _local(image.tag) != "image":
                continue
            href = image.get(_XLINK_HREF) or image.get("href", "")
            if not href.startswith("#") or len(href) < 2:
                continue
            identifier = unquote(href[1:], errors="strict")
            binaries = [node for node in root if _local(node.tag) == "binary" and node.get("id") == identifier]
            if len(binaries) != 1:
                continue
            binary = binaries[0]
            maximum = ((MAX_COVER_BYTES + 2) // 3) * 4
            parts, count = [], 0
            for part in binary.itertext():
                if len(part) > maximum * 2:
                    break
                part = re.sub(r"\s+", "", part)
                count += len(part)
                if count > maximum:
                    break
                parts.append(part)
            else:
                data = base64.b64decode("".join(parts).encode("ascii"), validate=True)
                cover = validate_cover(data, binary.get("content-type"))
                if cover is not None:
                    return cover
    except Exception:
        pass
    return None


def extract_cover(path: Path | str) -> CoverData | None:
    """Read only local cover metadata for a legacy library item, best effort."""
    archive = None
    try:
        from .books import _Archive, _reference, _xml, MAX_FILE_BYTES, file_size_limit

        path = Path(path)
        if not path.is_file() or not 0 < path.stat().st_size <= file_size_limit(path):
            return None
        suffix = path.suffix.lower()
        if suffix == ".cbz":
            from .cbz import extract_cover as cbz_cover
            return cbz_cover(path)
        if suffix == ".epub":
            archive = _Archive(path)
            container_data = _archive_read(archive, "META-INF/container.xml", MAX_COVER_XML_BYTES)
            if container_data is None:
                return None
            container = _xml(container_data, "container.xml")
            rootfile = next((node for node in container.iter() if _local(node.tag) == "rootfile"), None)
            if rootfile is None or not rootfile.get("full-path"):
                return None
            package_path = _reference("", rootfile.get("full-path"))
            data = _archive_read(archive, package_path, MAX_COVER_XML_BYTES)
            if data is not None:
                return epub_cover(archive, _xml(data, package_path), posixpath.dirname(package_path))
        elif suffix == ".fb2":
            with path.open("rb") as stream:
                data = stream.read(MAX_FILE_BYTES + 1)
            if len(data) <= MAX_FILE_BYTES:
                return fb2_cover(_xml(data, path.name))
        elif path.name.lower().endswith(".fb2.zip"):
            archive = _Archive(path)
            names = [name for name in archive.names if name.lower().endswith(".fb2")]
            if len(names) == 1:
                return fb2_cover(_xml(archive.read(names[0]), names[0]))
    except Exception:
        return None
    finally:
        if archive is not None:
            try:
                archive.close()
            except Exception:
                pass
    return None


class CoverCache:
    """Disposable private cache; failures never change the book library."""

    def __init__(self, directory: Path | str):
        self.directory = Path(directory)

    def path_for(self, book_id: str) -> Path:
        if not isinstance(book_id, str) or not book_id:
            raise ValueError("Cover cache keys must be nonempty strings")
        return self.directory / (hashlib.sha256(book_id.encode("utf-8")).hexdigest() + ".cover")

    def load(self, book_id: str) -> CoverData | None:
        try:
            with self.path_for(book_id).open("rb") as stream:
                data = stream.read(MAX_COVER_BYTES + 1)
            return validate_cover(data)
        except (OSError, ValueError, UnicodeError):
            return None

    def store(self, book_id: str, cover: CoverData) -> Path | None:
        temporary = None
        try:
            cover = validate_cover(cover.data, cover.mime_type)
            if cover is None:
                return None
            path = self.path_for(book_id)
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tempfile.NamedTemporaryFile(dir=self.directory, prefix=".cover-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(cover.data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            temporary = None
            return path
        except (OSError, ValueError, AttributeError, UnicodeError):
            return None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass


def load_thumbnail(cover: CoverData, width: int = 160, height: int = 240):
    """Decode a validated cover off the GUI thread, scaled before allocation."""
    loader, closed = None, False
    try:
        if type(width) is not int or type(height) is not int or not 1 <= width <= 1024 or not 1 <= height <= 1024:
            return None
        cover = validate_cover(cover.data, cover.mime_type)
        if cover is None:
            return None
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf

        loader = GdkPixbuf.PixbufLoader.new_with_type("png" if cover.mime_type == "image/png" else "jpeg")
        def prepared(image_loader, source_width, source_height):
            scale = min(width / source_width, height / source_height, 1.0)
            image_loader.set_size(max(1, math.floor(source_width * scale)),
                                  max(1, math.floor(source_height * scale)))
        loader.connect("size-prepared", prepared)
        loader.write(cover.data)
        loader.close()
        closed = True
        pixbuf = loader.get_pixbuf()
        if pixbuf is not None and pixbuf.get_width() <= width and pixbuf.get_height() <= height:
            return pixbuf
    except Exception:
        return None
    finally:
        if loader is not None and not closed:
            try:
                loader.close()
            except Exception:
                pass
    return None
