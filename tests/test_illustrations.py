"""Raster limits and canonical text positions around inline GTK anchors.

SPDX-License-Identifier: GPL-3.0-or-later
"""

from dataclasses import FrozenInstanceError
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch
import zlib

from malferma_libro.illustrations import (
    ImageData, InlineImage, MAX_IMAGE_BYTES, TextImageOffsets,
    decode_illustration, validate_illustration,
)


def png_chunk(kind, data):
    return (struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff))


def png(width=8, height=4, *, metadata=b"", compressed=None):
    pixels = (b"\0" + b"\x90\xb0\xd0" * width) * height
    return (b"\x89PNG\r\n\x1a\n"
            + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + metadata + png_chunk(b"IDAT", zlib.compress(pixels) if compressed is None else compressed)
            + png_chunk(b"IEND", b""))


def jpeg_header(width, height):
    # Header-only JPEG suffices to exercise preflight/target limits. Tests patch
    # the native loader; the real decoder also rejects its missing pixel stream.
    return (b"\xff\xd8\xff\xc0\x00\x11"
            + struct.pack(">BHHB", 8, height, width, 3)
            + b"\x01\x11\0\x02\x11\0\x03\x11\0\xff\xd9")


class TextImageOffsetTests(unittest.TestCase):
    def test_unicode_positions_and_repeated_boundaries_keep_canonical_offsets(self):
        text = "А🙂שعé"
        positions = TextImageOffsets(len(text), [5, 2, 0, 2])
        self.assertEqual(positions.image_offsets, (0, 2, 2, 5))
        self.assertEqual(positions.text_length, 5)
        self.assertEqual(positions.buffer_length, 9)
        self.assertEqual([positions.to_buffer(offset) for offset in range(6)], [0, 2, 3, 6, 7, 8])
        self.assertEqual([positions.to_buffer(offset, after_images=True) for offset in range(6)], [1, 2, 5, 6, 7, 9])
        self.assertEqual([positions.to_text(offset) for offset in range(10)], [0, 0, 1, 2, 2, 2, 3, 4, 5, 5])

    def test_empty_text_and_image_only_chapters(self):
        empty = TextImageOffsets(0, [])
        self.assertEqual((empty.to_buffer(100), empty.to_text(100)), (0, 0))
        images = TextImageOffsets(0, [0, 0, 0])
        self.assertEqual(images.to_buffer(0), 0)
        self.assertEqual(images.to_buffer(0, after_images=True), 3)
        self.assertEqual([images.to_text(offset) for offset in range(5)], [0] * 5)

    def test_inverse_mapping_for_every_text_boundary(self):
        for offsets in ([], [0], [8], [1, 1, 2, 5, 8, 8], [0] * 5 + list(range(9))):
            with self.subTest(offsets=offsets):
                positions = TextImageOffsets(8, iter(offsets))
                for offset in range(9):
                    self.assertEqual(positions.to_text(positions.to_buffer(offset)), offset)
                    self.assertEqual(positions.to_text(positions.to_buffer(offset, after_images=True)), offset)
                text_positions = [positions.to_text(offset) for offset in range(positions.buffer_length + 1)]
                self.assertEqual(text_positions, sorted(text_positions))
                self.assertEqual(set(text_positions), set(range(9)))

    def test_clamps_and_ignores_invalid_image_offsets(self):
        positions = TextImageOffsets(3, [-1, 4, 1, True, "1", None, 1.0])
        self.assertEqual(positions.image_offsets, (1,))
        self.assertEqual((positions.to_buffer(-10), positions.to_buffer(10**30)), (0, 4))
        self.assertEqual((positions.to_text(-10), positions.to_text(10**30)), (0, 3))
        for length in (-1, True, 1.5):
            with self.subTest(length=length), self.assertRaises(ValueError):
                TextImageOffsets(length, [])


class IllustrationTests(unittest.TestCase):
    def test_validation_retains_raster_dimensions_and_immutable_data(self):
        image = validate_illustration(png())
        self.assertIsInstance(image, ImageData)
        self.assertEqual((image.kind, image.width, image.height), ("png", 8, 4))
        reference = InlineImage(2, image, "Надія — illustration")
        with self.assertRaises(FrozenInstanceError):
            reference.offset = 3
        with self.assertRaises(FrozenInstanceError):
            image.width = 9

    def test_png_sanitization_discards_compressed_and_text_metadata(self):
        optional = (png_chunk(b"zTXt", b"private\0\0" + zlib.compress(b"metadata" * 1000))
                    + png_chunk(b"tEXt", b"Comment\0private information"))
        image = validate_illustration(png(metadata=optional))
        self.assertEqual(image.data, png())
        self.assertNotIn(b"private", image.data)
        self.assertNotIn(b"zTXt", image.data)

    def test_invalid_crc_truncation_and_compressed_pixels_are_rejected(self):
        invalid_crc = bytearray(png())
        invalid_crc[30] ^= 1
        for data in (bytes(invalid_crc), png()[:-1], png(compressed=b"not zlib"),
                     png(compressed=zlib.compress(b"\0\0"))):
            with self.subTest(data=data[:35]):
                self.assertIsNone(validate_illustration(data))

    def test_size_limits_and_nonraster_formats_are_rejected_before_decode(self):
        for data in (b"", None, bytearray(png()), b"x" * (MAX_IMAGE_BYTES + 1),
                     b'<svg xmlns="http://www.w3.org/2000/svg"/>', b"GIF89a", b"RIFFbadWEBP"):
            with self.subTest(kind=type(data), size=len(data) if data is not None else 0):
                self.assertIsNone(validate_illustration(data))
        for dimensions in ((0, 1), (16385, 1), (8192, 8192)):
            with self.subTest(dimensions=dimensions):
                self.assertIsNone(validate_illustration(jpeg_header(*dimensions)))

    def test_decode_contains_image_without_upscaling_and_caps_native_allocations(self):
        marker = object()
        for dimensions, box in (((8, 4), (100, 100)), ((100, 50), (20, 5)),
                                ((5000, 5000), (5000, 5000)), ((16384, 2), (100000, 100000))):
            image = validate_illustration(jpeg_header(*dimensions))
            with self.subTest(dimensions=dimensions, box=box), patch(
                    "malferma_libro.illustrations._decode", return_value=marker) as decoder:
                self.assertIs(decode_illustration(image, *box), marker)
                target = decoder.call_args.args[3]
                self.assertLessEqual(target[0], min(box[0], dimensions[0], 4096))
                self.assertLessEqual(target[1], min(box[1], dimensions[1], 4096))
                self.assertLessEqual(target[0] * target[1], 12 * 1024 * 1024)
                self.assertGreater(min(target), 0)

    def test_decode_refuses_forged_metadata_and_invalid_box_before_native_loader(self):
        image = validate_illustration(png())
        with patch("malferma_libro.illustrations._decode") as decoder:
            for box in ((0, 10), (10, -1), (True, 10), (10.0, 10)):
                self.assertIsNone(decode_illustration(image, *box))
            self.assertIsNone(decode_illustration(ImageData(image.data, "svg", 8, 4), 10, 10))
            self.assertIsNone(decode_illustration(ImageData(image.data, "png", 8000, 4000), 10, 10))
            decoder.assert_not_called()

    def test_model_import_does_not_import_gtk_or_gi(self):
        code = """import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == 'gi' or name.startswith('gi.'):
        raise AssertionError('Pure illustration model must not import GI')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from malferma_libro.illustrations import validate_illustration, TextImageOffsets
assert TextImageOffsets(1, [0]).to_buffer(1) == 2
"""
        subprocess.run([sys.executable, "-B", "-c", code], check=True, capture_output=True)

    def test_native_decode_needs_no_display_and_preserves_requested_box(self):
        try:
            import gi
            gi.require_version("GdkPixbuf", "2.0")
            from gi.repository import GdkPixbuf
        except (ImportError, ValueError):
            self.skipTest("GdkPixbuf is unavailable; native illustration decoding was not tested")
        image = validate_illustration(png(40, 80))
        rendered = decode_illustration(image, 20, 20)
        self.assertIsInstance(rendered, GdkPixbuf.Pixbuf)
        self.assertEqual((rendered.get_width(), rendered.get_height()), (10, 20))
        original = decode_illustration(image, 1000, 1000)
        self.assertEqual((original.get_width(), original.get_height()), (40, 80))


if __name__ == "__main__":
    unittest.main()
