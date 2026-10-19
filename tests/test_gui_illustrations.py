"""Native illustration layout, asynchronous lifetime and viewer checks.

SPDX-License-Identifier: GPL-3.0-or-later
"""

import os
from pathlib import Path
import tempfile
from threading import Event
import time
import unittest
from unittest.mock import patch


class IllustrationInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("RUN_GUI_TESTS") != "1":
            raise unittest.SkipTest("Set RUN_GUI_TESTS=1 to exercise native illustrations")
        try:
            import gi
            gi.require_version("Gtk", "4.0")
            gi.require_version("Adw", "1")
            from gi.repository import Adw, GdkPixbuf, Gio, GLib, Gtk
        except (ImportError, ValueError) as error:
            raise unittest.SkipTest(f"Native GTK/libadwaita unavailable: {error}") from error
        if not Gtk.init_check():
            raise unittest.SkipTest("Native GTK requires a graphical display")
        Adw.init()
        cls.GLib, cls.Gtk, cls.GdkPixbuf = GLib, Gtk, GdkPixbuf
        from malferma_libro.app import ReaderApplication, ReaderWindow
        cls.ReaderWindow = ReaderWindow
        cls.application = ReaderApplication()
        cls.application.set_flags(cls.application.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
        cls.application.register(None)

    @classmethod
    def tearDownClass(cls):
        cls.application.quit()

    def setUp(self):
        from malferma_libro.storage import Library
        self.temporary = tempfile.TemporaryDirectory(prefix="malferma-image-ui-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.library = Library(self.root / "library")
        with patch("malferma_libro.app.Library", return_value=self.library):
            self.window = self.ReaderWindow(self.application)
        self.window.present()
        self.pump()
        self.addCleanup(self.close_window)

    def close_window(self):
        self.window.close()
        self.pump(0.05)

    def pump(self, duration=0.15):
        deadline = time.monotonic() + duration
        context = self.GLib.MainContext.default()
        while time.monotonic() < deadline:
            while context.pending():
                context.iteration(False)
            time.sleep(0.005)

    def wait_for(self, condition, duration=4):
        deadline = time.monotonic() + duration
        while not condition() and time.monotonic() < deadline:
            self.pump(0.02)
        self.assertTrue(condition(), "Native illustration operation did not finish")

    def image(self, width=640, height=320):
        from malferma_libro.illustrations import validate_illustration
        pixbuf = self.GdkPixbuf.Pixbuf.new(self.GdkPixbuf.Colorspace.RGB, False, 8, width, height)
        pixbuf.fill(0x90B0D0FF)
        success, data = pixbuf.save_to_bufferv("png", [], [])
        self.assertTrue(success)
        result = validate_illustration(bytes(data))
        self.assertIsNotNone(result)
        return result

    def open_book(self, text, images):
        from malferma_libro.books import Book, Chapter
        book = Book("Illustrated fixture", "", [Chapter("One", text, images=images)], "EPUB")
        path = self.root / "fixture.txt"
        path.write_text(text)
        record = self.library.import_book(path, book)
        self.window.show_book(record, book)
        self.pump()

    def test_inline_anchors_preserve_unicode_text_and_book_positions(self):
        from malferma_libro.illustrations import InlineImage
        text = "А🙂שعé\n\nAfter the picture.\n" * 10
        image = self.image()
        self.open_book(text, [InlineImage(0, image, "Opening picture"), InlineImage(7, image)])
        window = self.window
        self.wait_for(lambda: bool(window._illustration_resident))
        self.assertEqual(window.buffer.get_char_count(), len(text) + 2)
        self.assertEqual(window.buffer.get_text(window.buffer.get_start_iter(),
                                               window.buffer.get_end_iter(), True), text)
        for offset in range(len(text) + 1):
            self.assertEqual(window.reader_text_offset(window.reader_iter_at_offset(offset)), offset)
        self.assertEqual(len(window._illustration_items), 2)
        self.assertTrue(any(item.picture.get_paintable() is not None
                            for item in window._illustration_items))

    def test_inline_image_follows_the_reading_column_after_resize(self):
        from malferma_libro.illustrations import InlineImage
        self.open_book("Before\n\nAfter\n", [InlineImage(8, self.image(1600, 800))])
        window = self.window
        self.wait_for(lambda: bool(window._illustration_resident))
        original = window._illustration_items[0].button.get_child().get_width()
        window.set_default_size(520, 650)
        self.pump(0.4)
        window.update_illustration_layout()
        self.wait_for(lambda: bool(window._illustration_resident))
        item = window._illustration_items[0]
        available = (window.text_view.get_width() - window.text_view.get_left_margin()
                     - window.text_view.get_right_margin())
        self.assertLessEqual(item.button.get_width(), available)
        self.assertLessEqual(item.button.get_child().get_width(), original)
        self.assertAlmostEqual(item.target[0] / item.target[1], 2.0, delta=0.03)

    def test_search_speech_and_saved_progress_use_canonical_text_offsets(self):
        from malferma_libro.illustrations import InlineImage
        from malferma_libro.search import BookMatch, SearchReport
        from malferma_libro.storage import Library

        text = "А🙂שعé before.\n\nFind the needle after several illustrations.\n"
        start = text.index("needle")
        end = start + len("needle")
        image = self.image(80, 40)
        self.open_book(text, [InlineImage(offset, image) for offset in (0, start, start, end)])
        window = self.window
        match = BookMatch(0, start, end, "One", text)
        window._book_search_query = "needle"
        window._book_search_report = SearchReport((match,), scanned_chapters=1)
        window._show_book_search_match(match)
        bounds = window.buffer.get_selection_bounds()
        self.assertEqual(len(bounds), 2)
        begin, finish = bounds
        self.assertEqual(window.buffer.get_text(begin, finish, True), "needle")
        self.assertEqual((window.reader_text_offset(begin), window.reader_text_offset(finish)),
                         (start, end))

        def tagged_text(tag):
            iterator = window.buffer.get_start_iter()
            characters = []
            while not iterator.is_end():
                if iterator.has_tag(tag):
                    characters.append(iterator.get_char())
                iterator.forward_char()
            return "".join(characters)

        self.assertEqual(tagged_text(window.search_tag), "needle")
        window._speech_book = (window.record["id"], window.chapter_index)
        window.speech_range(start, end)
        self.assertEqual(tagged_text(window.speech_tag), "needle")
        self.assertEqual(window._speech_offset, start)
        self.assertEqual(window._reading_progress_index.total_chars, len(text))
        window.save_progress()
        saved = Library(self.library.root).find(window.record["id"])
        self.assertEqual(saved["offset"], start)

    def test_click_opens_native_viewer_with_zoom_fit_and_close(self):
        from malferma_libro.illustrations import InlineImage
        self.open_book("Before\n\nAfter\n", [InlineImage(8, self.image(1600, 800))])
        window = self.window
        window._illustration_items[0].button.emit("clicked")
        self.wait_for(lambda: window._illustration_viewer_state["picture"].get_paintable() is not None)
        viewer = window._illustration_viewer
        self.assertIs(viewer.get_transient_for(), window)
        self.assertTrue(viewer.get_modal())
        state = window._illustration_viewer_state
        initial = state["zoom"]
        window._zoom_illustration(1.25)
        self.assertAlmostEqual(state["zoom"], initial * 1.25)
        self.assertFalse(state["fit"])
        window._fit_illustration()
        self.assertTrue(state["fit"])
        viewer.close()
        self.pump()
        self.assertIsNone(window._illustration_viewer)
        self.assertIsNone(window._illustration_viewer_state)

    def test_chapter_change_discards_a_late_background_decode(self):
        from malferma_libro.illustrations import InlineImage, decode_illustration
        entered, release = Event(), Event()

        def delayed(*args):
            entered.set()
            release.wait(4)
            return decode_illustration(*args)

        self.addCleanup(release.set)
        with patch("malferma_libro.illustration_ui.decode_illustration", side_effect=delayed):
            self.open_book("Before\n\nAfter\n", [InlineImage(8, self.image())])
            self.wait_for(entered.is_set)
            self.window.set_reader_text("New chapter without images")
            self.window.set_chapter_illustrations([])
            release.set()
            self.wait_for(lambda: not self.window._illustration_running)
        self.assertEqual(self.window._illustration_items, [])
        self.assertEqual(self.window._illustration_resident, {})
        self.assertEqual(self.window.buffer.get_char_count(), len("New chapter without images"))

    def test_scrolling_keeps_the_queue_and_texture_memory_bounded(self):
        from malferma_libro.illustrations import InlineImage
        image = self.image(1600, 1200)
        self.open_book("x\n\n" * 40, [InlineImage(index * 3, image) for index in range(40)])
        window = self.window
        self.wait_for(lambda: bool(window._illustration_resident))
        first = set(window._illustration_resident)
        adjustment = window.reader_scroll.get_vadjustment()
        adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
        self.pump(0.5)
        self.wait_for(lambda: bool(set(window._illustration_resident) - first))
        self.assertLessEqual(len(window._illustration_running), window._ILLUSTRATION_WORKERS)
        self.assertLessEqual(len(window._illustration_resident), window._ILLUSTRATION_RESIDENT_LIMIT)
        self.assertLessEqual(sum(window._illustration_resident.values()),
                             window._ILLUSTRATION_MEMORY_PIXELS)
        self.assertTrue(any(item.picture.get_paintable() is None
                            for item in window._illustration_items[:3]))

    def test_unreadable_illustration_does_not_break_the_book(self):
        from malferma_libro.illustrations import ImageData, InlineImage
        text = "A readable book despite a damaged optional picture."
        self.open_book(text, [InlineImage(0, ImageData(b"bad", "png", 1, 1))])
        self.wait_for(lambda: self.window._illustration_items[0].failed)
        self.assertEqual(self.window.buffer.get_text(self.window.buffer.get_start_iter(),
                                                    self.window.buffer.get_end_iter(), True), text)
        self.assertIsNone(self.window._illustration_items[0].picture.get_paintable())


if __name__ == "__main__":
    unittest.main()
