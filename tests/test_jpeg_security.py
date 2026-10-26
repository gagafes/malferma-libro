"""Optional JPEG profiles never cross a native decoder boundary.

SPDX-License-Identifier: GPL-3.0-or-later
"""

from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from malferma_libro.cbz import _image
from malferma_libro.covers import CoverCache, CoverData, _jpeg_data, load_thumbnail, validate_cover
from malferma_libro.illustrations import ImageData, decode_illustration, validate_illustration
from test_book_images import JPEG


def app2(payload=b"ICC_PROFILE\0\x01\x01benign test profile"):
    return b"\xff\xe2" + struct.pack(">H", len(payload) + 2) + payload


class JPEGSecurityTests(unittest.TestCase):
    def test_profiles_before_and_after_frame_and_between_scans_are_removed(self):
        frame = JPEG.index(b"\xff\xc0")
        after_frame = frame + 2 + int.from_bytes(JPEG[frame + 2:frame + 4], "big")
        scan = JPEG.index(b"\xff\xda")
        for position in (2, after_frame, scan, len(JPEG) - 2):
            for metadata in (app2(), app2(b"") * 3, app2(b"not an ICC profile")):
                data = JPEG[:position] + metadata + JPEG[position:]
                with self.subTest(position=position, metadata_size=len(metadata)):
                    self.assertEqual(validate_cover(data).data, JPEG)
                    self.assertEqual(_image(data), (JPEG, "jpeg", (2, 3)))
                    self.assertEqual(validate_illustration(data).data, JPEG)
        # A subsequent SOS must also be traversed, not treated as opaque tail.
        multiple = JPEG[:-2] + JPEG[scan:]
        tagged = JPEG[:-2] + app2() + JPEG[scan:-2] + app2() + JPEG[-2:]
        self.assertEqual(_jpeg_data(tagged), (multiple, (2, 3)))

    def test_entropy_stuffing_restart_markers_and_plain_jpeg_are_preserved(self):
        self.assertIs(_jpeg_data(JPEG)[0], JPEG)
        entropy = b"\x13\xff\x00\xe2\x42\xff\xd0\x01"
        plain = JPEG[:-2] + entropy + JPEG[-2:]
        tagged = JPEG[:-2] + entropy + app2() + JPEG[-2:]
        self.assertEqual(_jpeg_data(tagged)[0], plain)

    def test_truncated_or_invalid_segments_and_missing_scan_are_rejected(self):
        bad_segments = (b"\xff\xe2\0\x01", b"\xff\xe2\xff\xfftiny", b"\xff\xe2\0")
        for segment in bad_segments:
            with self.subTest(segment=segment):
                data = JPEG[:2] + segment + JPEG[2:]
                self.assertIsNone(validate_cover(data))
                self.assertIsNone(validate_illustration(data))
        for data in (JPEG[:-2], JPEG + b"trailing", JPEG[:JPEG.index(b"\xff\xda")] + b"\xff\xd9"):
            self.assertIsNone(validate_cover(data))
            self.assertIsNone(validate_illustration(data))
        self.assertIsNone(_jpeg_data(JPEG, max_dimension=2))
        self.assertIsNone(_jpeg_data(JPEG, max_pixels=5))

    def test_cache_and_thumbnail_revalidate_public_cover_data(self):
        cover = CoverData(JPEG[:2] + app2() + JPEG[2:], "image/jpeg")
        with tempfile.TemporaryDirectory() as directory:
            cache = CoverCache(Path(directory))
            path = cache.store("book", cover)
            self.assertEqual(path.read_bytes(), JPEG)
            self.assertEqual(cache.load("book").data, JPEG)
        pixbuf = Mock()
        pixbuf.get_width.return_value, pixbuf.get_height.return_value = 2, 3
        loader = Mock()
        loader.get_pixbuf.return_value = pixbuf
        factory = Mock(return_value=loader)
        gi = SimpleNamespace(require_version=Mock())
        repository = SimpleNamespace(GdkPixbuf=SimpleNamespace(
            PixbufLoader=SimpleNamespace(new_with_type=factory)))
        with patch.dict("sys.modules", {"gi": gi, "gi.repository": repository}):
            self.assertIs(load_thumbnail(cover), pixbuf)
        self.assertEqual(loader.write.call_args.args[0], JPEG)

    def test_forged_illustration_cannot_bypass_profile_removal(self):
        data = JPEG[:2] + app2() + JPEG[2:]
        with patch("malferma_libro.illustrations._decode") as decoder:
            self.assertIsNone(decode_illustration(ImageData(data, "jpeg", 2, 3), 20, 30))
            decoder.assert_not_called()
            image = validate_illustration(data)
            decode_illustration(image, 20, 30)
            self.assertEqual(decoder.call_args.args[0], JPEG)

    def test_native_pixels_match_after_profile_removal(self):
        try:
            import gi
            gi.require_version("GdkPixbuf", "2.0")
            from gi.repository import GdkPixbuf
        except (ImportError, ValueError):
            self.skipTest("GdkPixbuf is unavailable")
        tagged = JPEG[:2] + app2() + JPEG[2:]
        # Only sanitized data reaches the real loader; the marker is benign.
        plain = load_thumbnail(CoverData(JPEG, "image/jpeg"))
        cleaned = load_thumbnail(CoverData(tagged, "image/jpeg"))
        self.assertIsNotNone(plain)
        self.assertIsNotNone(cleaned)
        self.assertEqual(bytes(plain.get_pixels()), bytes(cleaned.get_pixels()))
