"""Bounded inline raster images and offsets independent of GTK text anchors.

Book text remains the canonical source for search, bookmarks, page numbers and
speech. Each displayed child anchor adds one character to the GTK buffer only;
TextImageOffsets translates these positions without changing the book text.

SPDX-License-Identifier: GPL-3.0-or-later
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from typing import Iterable
import zlib

from .cbz import CbzError, _decode, _image, _render_size


MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 32 * 1024 * 1024
MAX_IMAGES = 512
MAX_IMAGE_REFERENCES = 2048


@dataclass(frozen=True)
class ImageData:
    data: bytes
    kind: str
    width: int
    height: int


@dataclass(frozen=True)
class InlineImage:
    offset: int
    image: ImageData
    alt: str = ""


def validate_illustration(data: bytes) -> ImageData | None:
    """Preflight raster geometry and discard PNG metadata/JPEG ICC, offline.

    The shared CBZ reader checks compressed PNG row lengths and rejects images
    exceeding 16,384 pixels per side or 32 megapixels before native decoding.
    SVG, animations and external resources never reach an image loader here.
    """
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_IMAGE_BYTES:
        return None
    try:
        sanitized, kind, (width, height) = _image(data)
        return ImageData(sanitized, kind, width, height)
    except (ValueError, OverflowError, zlib.error):
        return None


def decode_illustration(image: ImageData, width: int, height: int):
    """Decode inside a display box, with no upscaling or GTK initialization.

    GdkPixbuf is imported by the shared decoder only when needed. Rendered
    rasters remain within 4,096 pixels per side and 12 megapixels. Malformed or
    unsupported images simply leave the surrounding readable text available.
    """
    if (not isinstance(image, ImageData) or type(width) is not int or type(height) is not int
            or width < 1 or height < 1):
        return None
    # ImageData is public, so do not trust hand-constructed or stale metadata.
    if validate_illustration(image.data) != image:
        return None
    try:
        factor = min(1.0, width / image.width, height / image.height)
        target = _render_size(image.width, image.height, factor, None)
        # Roundoff in the shared aspect-ratio calculation must not exceed the
        # requested box or enlarge a tiny image by one pixel.
        target = (min(target[0], width, image.width), min(target[1], height, image.height))
        return _decode(image.data, image.kind, (image.width, image.height), target)
    except (CbzError, ValueError, OverflowError):
        return None


def _clamp_offset(offset, maximum):
    try:
        return min(maximum, max(0, int(offset)))
    except (TypeError, ValueError, OverflowError):
        return 0


class TextImageOffsets:
    """Map canonical Unicode text positions to a buffer with child anchors.

    Multiple illustrations may share a boundary, including offset zero or the
    end of the text. Sorting preserves this multiplicity. Invalid image offsets
    are ignored; text and buffer positions are clamped to their respective ends.
    """

    __slots__ = ("text_length", "image_offsets", "buffer_length", "_anchor_offsets")

    def __init__(self, text_length: int, offsets: Iterable[int]):
        if type(text_length) is not int or text_length < 0:
            raise ValueError("Text length must be a nonnegative integer")
        self.text_length = text_length
        self.image_offsets = tuple(sorted(offset for offset in offsets
                                          if type(offset) is int and 0 <= offset <= text_length))
        self._anchor_offsets = tuple(offset + index for index, offset in enumerate(self.image_offsets))
        self.buffer_length = text_length + len(self.image_offsets)

    def to_buffer(self, offset: int, after_images: bool = False) -> int:
        offset = _clamp_offset(offset, self.text_length)
        count = bisect_right(self.image_offsets, offset) if after_images else bisect_left(self.image_offsets, offset)
        return offset + count

    def to_text(self, buffer_offset: int) -> int:
        offset = _clamp_offset(buffer_offset, self.buffer_length)
        return offset - bisect_left(self._anchor_offsets, offset)
