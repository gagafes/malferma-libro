"""Recovery checks for the public CLI, documents and user data location."""

import configparser
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

from malferma_libro import APP_ID, __version__
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


class ApplicationIdentityTests(unittest.TestCase):
    def test_desktop_metadata_and_icons_match_the_runtime_identity(self):
        desktop = configparser.ConfigParser(interpolation=None)
        desktop.read(ROOT / f"data/applications/{APP_ID}.desktop", encoding="utf-8")
        self.assertEqual(desktop["Desktop Entry"]["Icon"], APP_ID)
        self.assertEqual(desktop["Desktop Entry"]["StartupWMClass"], APP_ID)
        metadata = ElementTree.parse(ROOT / f"data/metainfo/{APP_ID}.metainfo.xml")
        self.assertEqual(metadata.findtext("id"), APP_ID)
        self.assertEqual(metadata.findtext("launchable"), f"{APP_ID}.desktop")
        for size in (16, 22, 24, 32, 48, 64, 96, 128, 256, 512):
            with self.subTest(size=size):
                self.assertTrue((ROOT / f"data/icons/hicolor/{size}x{size}/apps/{APP_ID}.png").is_file())
        self.assertTrue((ROOT / f"data/icons/hicolor/scalable/apps/{APP_ID}.svg").is_file())
        for extension in ("png", "svg"):
            with self.subTest(extension=extension):
                self.assertTrue((ROOT / f"src/malferma_libro/assets/branding/{APP_ID}.{extension}").is_file())

    def test_installed_checks_use_the_declared_identity(self):
        checker = runpy.run_path(str(ROOT / "packaging/check_installed.py"))
        self.assertEqual(checker["installed_application_id"](SimpleNamespace(APP_ID=APP_ID)), APP_ID)

    def test_installed_checks_read_previous_package_metadata_without_running_it(self):
        checker = runpy.run_path(str(ROOT / "packaging/check_installed.py"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "app.py").write_text(
                'raise RuntimeError("Do not start the installed application")\n'
                'APP_ID = "io.example.PreviousReader"\n', encoding="utf-8")
            module = SimpleNamespace(__file__=str(root / "__init__.py"))
            self.assertEqual(checker["installed_application_id"](module), "io.example.PreviousReader")


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

    def test_existing_library_under_previous_spelling_is_reused_without_moving_books(self):
        legacy = self.base / "malferna-libro"
        legacy.mkdir()
        book = legacy / "book.txt"
        book.write_text("Книга", encoding="utf-8")
        self.assertEqual(user_data_directory(), legacy)
        self.assertEqual(book.read_text(encoding="utf-8"), "Книга")

    def test_current_library_wins_when_both_folders_exist(self):
        (self.base / "malferna-libro").mkdir()
        current = self.base / "malferma-libro"
        current.mkdir()
        self.assertEqual(user_data_directory(), current)

    def test_unrecognized_data_folder_is_not_reused_or_changed(self):
        previous = self.base / "previous-reader"
        previous.mkdir()
        book = previous / "book.txt"
        book.write_text("Книга", encoding="utf-8")
        current = self.base / "malferma-libro"
        self.assertEqual(user_data_directory(), current)
        self.assertFalse(current.exists())
        self.assertEqual(book.read_text(encoding="utf-8"), "Книга")

    def test_relative_xdg_path_does_not_write_into_the_working_directory(self):
        with patch.dict(os.environ, {"XDG_DATA_HOME": "relative"}), \
                patch.object(Path, "home", return_value=self.base):
            self.assertEqual(user_data_directory(), self.base / ".local/share/malferma-libro")


if __name__ == "__main__":
    unittest.main()
