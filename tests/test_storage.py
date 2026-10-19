"""Library persistence and recovery use temporary, isolated user libraries.

SPDX-License-Identifier: GPL-3.0-or-later
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import stat
import tempfile
from threading import Barrier, Event
import unittest
from unittest.mock import patch

from malferma_libro.books import BookError, load_book
from malferma_libro.importing import import_books
from malferma_libro.storage import DEFAULT_SETTINGS, Library, LibraryError, _PublishedWriteError
from malferma_libro.tasks import OperationToken, TaskCancelled


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.library = Library(self.root / "library")
        self.source = self.root / "Надія.txt"
        self.source.write_text("Гетьте, думи, ви хмари осінні!", encoding="utf-8")

    def import_book(self):
        return self.library.import_book(self.source)

    def test_import_is_an_independent_managed_snapshot(self):
        record = self.import_book()
        managed = Path(record["path"])
        self.assertEqual(managed.parent, self.library.books_dir)
        self.assertEqual(managed.read_bytes(), self.source.read_bytes())
        self.source.write_text("Changed after import", encoding="utf-8")
        self.assertIn("Гетьте, думи", load_book(managed).chapters[0].text)
        reopened = Library(self.library.root)
        self.assertEqual(reopened.find(record["id"])["title"], "Надія")
        self.assertEqual(len(list(self.library.books_dir.iterdir())), 1)

    def test_duplicate_content_has_one_record_and_managed_copy(self):
        first = self.import_book()
        renamed = self.root / "different.txt"
        renamed.write_bytes(self.source.read_bytes())
        duplicate = self.library.import_book(renamed)
        self.assertIs(first, duplicate)
        self.assertEqual(len(self.library.books), 1)
        self.assertEqual(len(list(self.library.books_dir.iterdir())), 1)

    def test_concurrent_duplicate_imports_commit_exactly_one_record(self):
        ready = Barrier(2)
        original_load = load_book

        def synchronized_load(path):
            book = original_load(path)
            ready.wait(timeout=5)
            return book

        with patch("malferma_libro.books.load_book", side_effect=synchronized_load), \
                ThreadPoolExecutor(max_workers=2) as workers:
            futures = [workers.submit(self.library.import_book_with_content, self.source) for _ in range(2)]
            first, second = [future.result(timeout=5)[0] for future in futures]
        self.assertIs(first, second)
        self.assertEqual(len(Library(self.library.root).books), 1)
        self.assertEqual(len(list(self.library.books_dir.iterdir())), 1)

    def test_import_does_not_restore_preferences_changed_while_parsing(self):
        parsing, resume = Event(), Event()
        original_load = load_book

        def wait_during_load(path):
            book = original_load(path)
            parsing.set()
            if not resume.wait(timeout=5):
                raise TimeoutError("The test did not release the import worker")
            return book

        with patch("malferma_libro.books.load_book", side_effect=wait_during_load), \
                ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(self.library.import_book_with_content, self.source)
            try:
                self.assertTrue(parsing.wait(timeout=5))
                self.library.update_settings({"font_size": 48})
            finally:
                resume.set()
            future.result(timeout=5)
        self.assertEqual(self.library.settings["font_size"], 48)
        self.assertEqual(Library(self.library.root).settings["font_size"], 48)

    def test_reimport_repairs_missing_managed_copy(self):
        record = self.import_book()
        Path(record["path"]).unlink()
        repaired = self.import_book()
        self.assertEqual(record["id"], repaired["id"])
        self.assertEqual(Path(repaired["path"]).read_bytes(), self.source.read_bytes())

    def test_failed_parse_leaves_no_import_directory_or_record(self):
        self.source.write_bytes(b"binary\x00data")
        with self.assertRaises(BookError):
            self.import_book()
        self.assertEqual(self.library.books, [])
        self.assertEqual(list(self.library.books_dir.iterdir()), [])

    def test_import_rejects_a_file_swapped_for_a_fifo_before_open(self):
        original_open = os.open

        def swapped_open(path, flags, *args, **kwargs):
            if Path(path) == self.source:
                self.assertTrue(flags & os.O_NONBLOCK)
                self.source.unlink()
                os.mkfifo(self.source)
            return original_open(path, flags, *args, **kwargs)

        with patch("malferma_libro.storage.os.open", side_effect=swapped_open):
            with self.assertRaises(ValueError):
                self.import_book()
        self.assertEqual(self.library.books, [])
        self.assertEqual(list(self.library.books_dir.iterdir()), [])

    def test_import_rejects_a_new_final_symlink_without_reading_its_target(self):
        target = self.root / "unselected.txt"
        target.write_text("Unselected private text", encoding="utf-8")
        original_open = os.open

        def swapped_open(path, flags, *args, **kwargs):
            if Path(path) == self.source:
                self.source.unlink()
                self.source.symlink_to(target)
            return original_open(path, flags, *args, **kwargs)

        with patch("malferma_libro.storage.os.open", side_effect=swapped_open):
            with self.assertRaises(OSError):
                self.import_book()
        self.assertEqual(target.read_text(encoding="utf-8"), "Unselected private text")
        self.assertEqual(self.library.books, [])
        self.assertEqual(list(self.library.books_dir.iterdir()), [])

    def test_an_intentionally_selected_symlink_to_a_regular_book_still_imports(self):
        selected = self.root / "selected.txt"
        selected.symlink_to(self.source)
        record = self.library.import_book(selected)
        self.assertEqual(Path(record["path"]).read_bytes(), self.source.read_bytes())

    def test_import_checks_the_size_of_the_opened_snapshot(self):
        self.source.write_text("small", encoding="utf-8")
        original_open = os.open

        def grown_open(path, flags, *args, **kwargs):
            if Path(path) == self.source:
                self.source.write_bytes(b"too large")
            return original_open(path, flags, *args, **kwargs)

        with patch("malferma_libro.books.file_size_limit", return_value=8), \
                patch("malferma_libro.storage.os.open", side_effect=grown_open):
            with self.assertRaises(ValueError):
                self.import_book()
        self.assertEqual(self.library.books, [])
        self.assertEqual(list(self.library.books_dir.iterdir()), [])

    def test_cancelled_import_has_no_side_effects(self):
        token = OperationToken()
        token.cancel()
        with self.assertRaises(TaskCancelled):
            self.library.import_book_with_content(self.source, cancel=token)
        self.assertEqual(list(self.library.books_dir.iterdir()), [])
        self.assertEqual(self.library.books, [])

    def test_boolean_cancellation_probe_stops_import_before_copying(self):
        with self.assertRaises(TaskCancelled):
            self.library.import_book_with_content(self.source, cancel=lambda: True)
        self.assertEqual(list(self.library.books_dir.iterdir()), [])
        self.assertEqual(self.library.books, [])

    def test_book_directory_is_durable_before_metadata_is_published(self):
        synced_directories = []
        original_fsync = os.fsync

        def fsync(descriptor):
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                synced_directories.append(Path(os.readlink(f"/proc/self/fd/{descriptor}")))
            return original_fsync(descriptor)

        with patch("malferma_libro.storage.os.fsync", side_effect=fsync):
            self.import_book()
        self.assertIn(self.library.books_dir, synced_directories)
        self.assertLess(synced_directories.index(self.library.books_dir),
                        synced_directories.index(self.library.root))

    def test_book_directory_sync_failure_keeps_copy_without_publishing_record(self):
        original_fsync = os.fsync

        def fsync(descriptor):
            if (stat.S_ISDIR(os.fstat(descriptor).st_mode)
                    and Path(os.readlink(f"/proc/self/fd/{descriptor}")) == self.library.books_dir):
                raise OSError("Book directory could not be synced")
            return original_fsync(descriptor)

        with patch("malferma_libro.storage.os.fsync", side_effect=fsync):
            with self.assertRaises(OSError):
                self.import_book()
        self.assertEqual(self.library.books, [])
        self.assertFalse(self.library.path.exists())
        managed = list(self.library.books_dir.iterdir())
        self.assertEqual(len(managed), 1)
        self.assertEqual(managed[0].read_bytes(), self.source.read_bytes())
        # Retrying recovers the retained managed copy instead of losing data.
        self.assertTrue(Path(self.import_book()["path"]).is_file())

    def test_batch_keeps_successful_book_and_reports_bad_input(self):
        bad = self.root / "bad.epub"
        bad.write_bytes(b"invalid")
        token = OperationToken()
        imported, errors = import_books(self.library, [self.source, bad, self.source], token)
        self.assertEqual([duplicate for _record, _book, duplicate in imported], [False, True])
        self.assertEqual(errors[0][0], bad)
        self.assertIsInstance(errors[0][1], BookError)
        self.assertEqual(len(self.library.books), 1)
        self.assertEqual(token.progress_value, (3, 3))

    def test_position_and_bookmarks_survive_reopening(self):
        record = self.import_book()
        self.library.mark_opened(record["id"])
        self.library.update_reading_progress(record["id"], 2, 31, 64.5)
        self.library.add_bookmark(record["id"], 2, 31, " Надія ", note=" важливо ", page=4)
        restored = Library(self.library.root)
        book = restored.find(record["id"])
        self.assertEqual((book["chapter"], book["offset"], book["progress_percent"]), (2, 31, 64.5))
        self.assertEqual(book["bookmarks"], [{"chapter": 2, "offset": 31, "label": "Надія", "note": "важливо", "page": 4}])
        self.assertEqual(restored.last_opened_book()["id"], record["id"])

    def test_bookmark_same_position_is_updated_and_removable(self):
        record = self.import_book()
        self.library.add_bookmark(record["id"], 0, 3, "First")
        self.library.add_bookmark(record["id"], 0, 3, "Revised", note="Comment")
        self.assertEqual(len(record["bookmarks"]), 1)
        self.library.edit_bookmark(record["id"], 0, "")
        self.assertNotIn("note", record["bookmarks"][0])
        self.library.remove_bookmark(record["id"], 0)
        self.assertEqual(Library(self.library.root).books[0]["bookmarks"], [])
        self.assertTrue(Path(record["path"]).is_file())

    def test_invalid_positions_and_nonfinite_progress_are_rejected(self):
        record = self.import_book()
        for position in (-1, True, 1.5, "3"):
            with self.subTest(position=position), self.assertRaises(ValueError):
                self.library.update_progress(record["id"], position, 0)
        for percent in (float("nan"), float("inf"), True):
            with self.subTest(percent=percent), self.assertRaises(ValueError):
                self.library.update_reading_progress(record["id"], 0, 0, percent)
        self.assertEqual((record["chapter"], record["offset"]), (0, 0))

    def test_finishing_position_does_not_override_user_status(self):
        record = self.import_book()
        self.library.mark_opened(record["id"])
        self.library.update_reading_progress(record["id"], 0, 1000, 100)
        self.assertEqual(record["reading_status"], "reading")
        self.library.set_reading_status(record["id"], "finished")
        self.assertEqual(Library(self.library.root).books[0]["reading_status"], "finished")

    def test_prepublication_save_failure_rolls_back_live_position(self):
        record = self.import_book()
        with patch.object(self.library, "save", side_effect=OSError("Disk full")):
            with self.assertRaises(OSError):
                self.library.update_reading_progress(record["id"], 2, 90, 80)
        self.assertEqual((record["chapter"], record["offset"], record["progress_percent"]), (0, 0, 0.0))
        self.assertEqual(Library(self.library.root).books[0]["offset"], 0)

    def test_prepublication_settings_failure_rolls_back_without_replacing_dict(self):
        settings = self.library.settings
        with patch.object(self.library, "save", side_effect=OSError("Disk full")):
            with self.assertRaises(OSError):
                self.library.update_settings({"font_size": 34})
        self.assertIs(settings, self.library.settings)
        self.assertEqual(settings["font_size"], DEFAULT_SETTINGS["font_size"])

    def test_postpublication_sync_failure_keeps_live_settings_aligned_with_disk(self):
        from malferma_libro.storage import _atomic_write

        self.library.save()
        settings = self.library.settings

        def write_then_fail(path, data):
            _atomic_write(path, data)
            if path == self.library.path:
                raise _PublishedWriteError(OSError("Directory sync failed after publication"))

        with patch("malferma_libro.storage._atomic_write", side_effect=write_then_fail):
            with self.assertRaises(OSError):
                self.library.update_settings({"font_size": 34})
        self.assertIs(self.library.settings, settings)
        self.assertEqual(settings["font_size"], 34)
        self.assertEqual(Library(self.library.root).settings["font_size"], 34)

    def test_optional_preferences_are_safely_normalized(self):
        self.library.update_settings({"font_size": 10000, "brightness": float("nan"), "speech_rate": True, "icon_theme": "elementary", "reader_width": -100, "line_spacing": float("inf")})
        self.assertEqual(self.library.settings["font_size"], 96)
        self.assertEqual(self.library.settings["brightness"], 1.0)
        self.assertEqual(self.library.settings["speech_rate"], DEFAULT_SETTINGS["speech_rate"])
        self.assertEqual(self.library.settings["icon_theme"], "system")
        self.assertEqual(self.library.settings["reader_width"], 480)
        self.assertEqual(self.library.settings["line_spacing"], DEFAULT_SETTINGS["line_spacing"])

    def test_corrupt_primary_recovers_backup_and_preserves_damaged_bytes(self):
        self.import_book()
        self.library.update_settings({"font_size": 24})
        damaged = b'{"interrupted":'
        self.library.path.write_bytes(damaged)
        recovered = Library(self.library.root)
        self.assertEqual(len(recovered.books), 1)
        self.assertTrue(recovered.warnings)
        preserved = list(self.library.root.glob("library.json.corrupt-*"))
        self.assertEqual(len(preserved), 1)
        self.assertEqual(preserved[0].read_bytes(), damaged)
        self.assertTrue(Path(recovered.books[0]["path"]).is_file())
        recovered.save()
        self.assertEqual(len(Library(self.library.root).books), 1)

    def test_missing_primary_recovers_valid_backup(self):
        self.import_book()
        self.library.save()
        self.library.path.unlink()
        recovered = Library(self.library.root)
        self.assertEqual(len(recovered.books), 1)
        self.assertTrue(recovered.warnings)

    def test_excessively_nested_json_recovers_backup_without_crashing(self):
        self.import_book()
        self.library.save()
        damaged = b"[" * 20000 + b"]" * 20000
        self.library.path.write_bytes(damaged)
        recovered = Library(self.library.root)
        self.assertEqual(len(recovered.books), 1)
        self.assertTrue(recovered.warnings)
        preserved = list(self.library.root.glob("library.json.corrupt-*"))
        self.assertEqual(preserved[0].read_bytes(), damaged)
        recovered.save()
        self.assertEqual(len(Library(self.library.root).books), 1)

    def test_newer_schema_is_not_replaced_with_older_backup(self):
        self.import_book()
        self.library.save()
        document = json.loads(self.library.path.read_text(encoding="utf-8"))
        document["schema_version"] = 999
        self.library.path.write_text(json.dumps(document), encoding="utf-8")
        before = self.library.path.read_bytes()
        with self.assertRaises(LibraryError):
            Library(self.library.root)
        self.assertEqual(self.library.path.read_bytes(), before)

    def test_newer_schema_replacement_is_not_overwritten_by_running_instance(self):
        self.import_book()
        self.library.save()
        document = json.loads(self.library.path.read_text(encoding="utf-8"))
        document["schema_version"] = 999
        self.library.path.write_text(json.dumps(document), encoding="utf-8")
        primary = self.library.path.read_bytes()
        backup = self.library.backup_path.read_bytes()
        with self.assertRaises(LibraryError):
            self.library.update_settings({"font_size": 34})
        self.assertEqual(self.library.settings["font_size"], DEFAULT_SETTINGS["font_size"])
        self.assertEqual(self.library.path.read_bytes(), primary)
        self.assertEqual(self.library.backup_path.read_bytes(), backup)

    def test_catalog_validation_duplicate_protection_and_deletion(self):
        self.library.add_catalog(" Calibre ", "http://127.0.0.1:8080/opds")
        with self.assertRaises(ValueError):
            self.library.add_catalog("Duplicate", "http://127.0.0.1:8080/opds")
        for address in ("file:///etc/passwd", "https://user:password@example.org/opds", "https://example.org:99999/opds"):
            with self.subTest(address=address), self.assertRaises(ValueError):
                self.library.add_catalog("Unsafe", address)
        self.assertEqual(Library(self.library.root).catalogs[0]["name"], "Calibre")
        self.library.remove_catalog(0)
        self.assertEqual(Library(self.library.root).catalogs, [])


if __name__ == "__main__":
    unittest.main()
