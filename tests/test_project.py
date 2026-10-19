"""Recovery checks for the public CLI, documents and user data location."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from malferma_libro import __version__
from malferma_libro.__main__ import CliError, parse_arguments
from malferma_libro.helptext import license_text, manual_text
from malferma_libro.paths import user_data_directory


ROOT = Path(__file__).resolve().parents[1]


class CommandLineTests(unittest.TestCase):
    def test_public_version_needs_no_graphical_session(self):
        result = subprocess.run(
            [sys.executable, "-m", "malferma_libro", "--version"],
            env={**os.environ, "DISPLAY": "", "WAYLAND_DISPLAY": ""},
            capture_output=True, text=True, check=True,
        )
        self.assertEqual(result.stdout, "Malferma Libro 0.1.1\n")
        self.assertEqual(result.stderr, "")
        self.assertEqual(__version__, "0.1.1")

    def test_dash_filename_after_separator_is_a_book(self):
        options = parse_arguments(["--", "-book.txt", "--version"])
        self.assertIsNone(options.information)
        self.assertEqual(options.files, ("-book.txt", "--version"))

    def test_unknown_options_and_conflicting_information_fail(self):
        for arguments in (["--unknown"], ["--manual=xx"], ["--license", "--version"]):
            with self.subTest(arguments=arguments), self.assertRaises(CliError):
                parse_arguments(arguments)

    def test_four_bundled_manuals_match_the_editable_sources(self):
        for language in ("ru", "en", "de", "uk"):
            path = ROOT / ("MANUAL.md" if language == "ru" else f"docs/MANUAL.{language}.md")
            with self.subTest(language=language):
                self.assertEqual(manual_text(language), path.read_text(encoding="utf-8"))

    def test_bundled_license_is_the_complete_gpl_text(self):
        self.assertEqual(license_text(), (ROOT / "LICENSE").read_text(encoding="utf-8"))
        self.assertIn("GNU GENERAL PUBLIC LICENSE", license_text())
        self.assertIn("29 June 2007", license_text())


class DataDirectoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        environment = patch.dict(os.environ, {"XDG_DATA_HOME": str(self.base)})
        environment.start()
        self.addCleanup(environment.stop)

    def test_fresh_install_uses_new_name_without_creating_a_folder(self):
        self.assertEqual(user_data_directory(), self.base / "malferma-libro")
        self.assertEqual(list(self.base.iterdir()), [])

    def test_existing_legacy_library_is_reused_without_moving_books(self):
        legacy = self.base / "otkrytaya-kniga"
        legacy.mkdir()
        book = legacy / "book.txt"
        book.write_text("Книга", encoding="utf-8")
        self.assertEqual(user_data_directory(), legacy)
        self.assertEqual(book.read_text(encoding="utf-8"), "Книга")

    def test_current_library_wins_when_both_folders_exist(self):
        (self.base / "otkrytaya-kniga").mkdir()
        current = self.base / "malferma-libro"
        current.mkdir()
        self.assertEqual(user_data_directory(), current)

    def test_existing_library_under_the_corrected_spelling_is_not_lost(self):
        previous = self.base / "malferna-libro"
        previous.mkdir()
        (self.base / "otkrytaya-kniga").mkdir()
        self.assertEqual(user_data_directory(), previous)
        current = self.base / "malferma-libro"
        current.mkdir()
        self.assertEqual(user_data_directory(), current)

    def test_relative_xdg_path_does_not_write_into_the_working_directory(self):
        with patch.dict(os.environ, {"XDG_DATA_HOME": "relative"}), \
                patch.object(Path, "home", return_value=self.base):
            self.assertEqual(user_data_directory(), self.base / ".local/share/malferma-libro")


if __name__ == "__main__":
    unittest.main()
