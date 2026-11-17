"""Regression coverage for passwords passed to native Poppler helpers."""

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from malferma_libro.pdf import PdfDocument, PdfError


class PdfPasswordSecurityTests(unittest.TestCase):
    def test_oversized_password_never_reaches_native_helper(self):
        for password in ("a" * 128, "я" * 64, "🔒" * 32):
            with self.subTest(bytes=len(password.encode("utf-8"))):
                with patch("malferma_libro.pdf._local_file",
                           return_value=(Path("book.pdf"), SimpleNamespace(st_size=100))):
                    with patch.object(PdfDocument, "_info") as info:
                        with self.assertRaises(PdfError):
                            PdfDocument("book.pdf", password=password)
                        info.assert_not_called()

    def test_passwords_within_byte_limit_are_preserved(self):
        for password in (None, "", "a" * 127, "я" * 63 + "a"):
            with self.subTest(password=password):
                with patch("malferma_libro.pdf._local_file",
                           return_value=(Path("book.pdf"), SimpleNamespace(st_size=100))):
                    with patch.object(PdfDocument, "_info",
                                      return_value="Pages: 1\nPage size: 100 x 200 pts"):
                        document = PdfDocument("book.pdf", password=password)
                        self.assertEqual(document._password_arguments(),
                                         [] if password is None else ["-upw", password])


if __name__ == "__main__":
    unittest.main()
