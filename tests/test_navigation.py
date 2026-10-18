"""Behavioral navigation tests without importing GTK or opening a display.

SPDX-License-Identifier: GPL-3.0-or-later
"""

from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from malferma_libro.book_pagination import PageSpan, reference_page_range
from malferma_libro.books import Book, Chapter
from malferma_libro.immersive import HeaderContext, HeaderVisibility
from malferma_libro.keyboard_navigation import navigation_for, scroll_target
from malferma_libro.keyboard_ui import KeyboardNavigationMixin
from malferma_libro.reading_state import ReadingProgressIndex


class KeyboardCalculationTests(unittest.TestCase):
    def test_arrow_directions_and_keypad_aliases(self):
        for key, action in (("Left", "turn-previous"), ("Right", "turn-next"), ("KP_Left", "turn-previous"), ("KP_Right", "turn-next"), ("Prior", "page-up"), ("Next", "page-down"), ("Up", "line-up"), ("Down", "line-down")):
            with self.subTest(key=key):
                self.assertEqual(navigation_for(key), action)

    def test_modified_native_input_is_preserved(self):
        for modifiers in ({"shift"}, {"alt"}, {"super"}, {"control"}, {"control", "shift"}):
            with self.subTest(modifiers=modifiers):
                self.assertIsNone(navigation_for("Right", modifiers))
        self.assertIsNone(navigation_for("KP_6"))
        self.assertEqual(navigation_for("Home", {"control"}), "book-start")
        self.assertEqual(navigation_for("End", {"control"}), "book-end")

    def test_page_movement_keeps_ten_percent_overlap(self):
        self.assertEqual(scroll_target("page-down", 100, 0, 2000, 500, 40), 550)
        self.assertEqual(scroll_target("page-up", 550, 0, 2000, 500, 40), 100)

    def test_scroll_clamps_to_viewport_bounds(self):
        self.assertEqual(scroll_target("page-down", 1400, 0, 2000, 500, 40), 1500)
        self.assertEqual(scroll_target("line-up", 10, 0, 2000, 500, 40), 0)
        self.assertEqual(scroll_target("end", 0, 10, 100, 200, 40), 10)

    def test_invalid_transient_geometry_does_not_produce_nan(self):
        self.assertEqual(scroll_target("page-down", float("nan"), 0, 1000, 0, -1), 40)
        self.assertEqual(scroll_target("end", 4, 0, float("inf"), 200, 40), 0)
        with self.assertRaises(ValueError):
            scroll_target("unknown", 0, 0, 1000, 100, 40)


class WholeBookPaginationTests(unittest.TestCase):
    def text_index(self, *lengths):
        return ReadingProgressIndex.from_book(Book("Book", "", [Chapter(str(i), "а" * size) for i, size in enumerate(lengths)], "TXT"))

    def test_reference_pages_continue_across_chapter_boundaries(self):
        index = self.text_index(900, 900, 1800)
        self.assertEqual(reference_page_range(index, 0, 0, 900), PageSpan(1, 1, 2))
        self.assertEqual(reference_page_range(index, 1, 0, 900), PageSpan(1, 1, 2))
        self.assertEqual(reference_page_range(index, 2, 0, 1800), PageSpan(2, 2, 2))

    def test_visible_range_end_is_exclusive(self):
        index = self.text_index(4000)
        self.assertEqual(reference_page_range(index, 0, 1700, 1800), PageSpan(1, 1, 3))
        self.assertEqual(reference_page_range(index, 0, 1700, 1801), PageSpan(1, 2, 3))

    def test_eof_empty_ranges_and_invalid_offsets_are_clamped(self):
        index = self.text_index(3600)
        self.assertEqual(reference_page_range(index, 0, 3600), PageSpan(2, 2, 2))
        self.assertEqual(reference_page_range(index, 99, 999999), PageSpan(2, 2, 2))
        self.assertEqual(reference_page_range(index, -1, -1), PageSpan(1, 1, 2))
        self.assertEqual(reference_page_range(index, 0, 1900, 1500), PageSpan(2, 2, 2))
        self.assertEqual(reference_page_range(self.text_index(), 0, 0), PageSpan(1, 1, 1))

    def test_progress_counts_unicode_characters_not_encoded_bytes(self):
        book = Book("Unicode", "", [Chapter("a", "🙂אа"), Chapter("b", "é")], "TXT")
        index = ReadingProgressIndex.from_book(book)
        self.assertEqual(index.total_chars, 4)
        self.assertEqual(index.percent(1, 0), 75)
        self.assertEqual(index.percent(1, 1), 100)

    def test_fixed_layout_keeps_physical_page_numbers(self):
        book = Book("Scans", "", [Chapter("1", ""), Chapter("2", ""), Chapter("3", "")], "PDF", pdf_document=object())
        index = ReadingProgressIndex.from_book(book)
        self.assertEqual(reference_page_range(index, 1, 99000), PageSpan(2, 2, 3))
        self.assertEqual(index.percent(1, 50000), 50)


class Adjustment:
    """Minimal Gtk.Adjustment protocol; navigation under test is production code."""
    def __init__(self, value=0, upper=2000, page_size=500):
        self.value, self.upper, self.page_size = value, upper, page_size

    def get_value(self):
        return self.value

    def get_lower(self):
        return 0

    def get_upper(self):
        return self.upper

    def get_page_size(self):
        return self.page_size

    def get_step_increment(self):
        return 40

    def set_value(self, value):
        self.value = value


class ReaderHarness(KeyboardNavigationMixin):
    def __init__(self, *, paged=False, value=0, chapter=0):
        self.book = Book("Book", "", [Chapter("First", "а" * 4000), Chapter("Last", "б" * 7000)], "TXT")
        self.paged, self.chapter_index = paged, chapter
        self._closing = self._restoring = False
        self._document_ready = True
        self.focus_allowed = True
        self.adjustment = Adjustment(value)
        self.reader_scroll = SimpleNamespace(get_vadjustment=lambda: self.adjustment)
        self.moves, self.restores, self.positions = [], [], []
        self.saves = self.manual_scrolls = 0
        self.document_position = SimpleNamespace(user_input=lambda geometry, offset: self.positions.append((geometry, offset)))

    def is_paged(self):
        return self.paged

    def reading_navigation_has_focus(self):
        return self.focus_allowed

    def manual_scroll(self):
        self.manual_scrolls += 1

    def display_chapter(self, index, offset):
        self.moves.append((index, offset))

    def queue_progress_save(self):
        self.saves += 1

    def restore_position(self, offset):
        self.restores.append(offset)

    def document_geometry(self):
        return "geometry"

    def visible_offset(self):
        return 12345


class ReadingNavigationTests(unittest.TestCase):
    def test_text_right_and_left_scroll_one_viewport(self):
        reader = ReaderHarness(value=100)
        self.assertTrue(reader.handle_reader_navigation("Right", ()))
        self.assertEqual(reader.adjustment.value, 550)
        self.assertTrue(reader.handle_reader_navigation("Left", ()))
        self.assertEqual(reader.adjustment.value, 100)
        self.assertEqual(reader.moves, [])

    def test_text_right_at_end_opens_next_chapter_at_top(self):
        reader = ReaderHarness(value=1500)
        reader.handle_reader_navigation("Right", ())
        self.assertEqual(reader.moves, [(1, 0)])
        self.assertEqual(reader.saves, 1)

    def test_text_left_at_start_opens_previous_chapter_at_end(self):
        reader = ReaderHarness(chapter=1)
        reader.handle_reader_navigation("Left", ())
        self.assertEqual(reader.moves, [(0, 4000)])

    def test_fixed_layout_left_and_right_turn_pages_at_any_zoom_position(self):
        for chapter, key, target in ((0, "Right", 1), (1, "Left", 0)):
            with self.subTest(key=key):
                reader = ReaderHarness(paged=True, chapter=chapter, value=800)
                reader.handle_reader_navigation(key, ())
                self.assertEqual(reader.moves, [(target, 0)])
                self.assertEqual(reader.adjustment.value, 800)

    def test_document_boundary_does_not_wrap_to_other_end(self):
        for chapter, key in ((0, "Left"), (1, "Right")):
            reader = ReaderHarness(paged=True, chapter=chapter)
            self.assertTrue(reader.handle_reader_navigation(key, ()))
            self.assertEqual(reader.moves, [])
            self.assertEqual(reader.saves, 0)

    def test_restoring_and_loading_cannot_be_overwritten_by_held_keys(self):
        reader = ReaderHarness()
        reader._restoring = True
        reader.handle_reader_navigation("Right", ())
        self.assertEqual((reader.moves, reader.saves, reader.adjustment.value), ([], 0, 0))
        reader = ReaderHarness(paged=True)
        reader._document_ready = False
        reader.handle_reader_navigation("Down", ())
        self.assertEqual((reader.moves, reader.saves, reader.adjustment.value), ([], 0, 0))

    def test_focus_and_modified_keys_keep_native_behavior(self):
        reader = ReaderHarness()
        reader.focus_allowed = False
        self.assertFalse(reader.handle_reader_navigation("Right", ()))
        reader.focus_allowed = True
        self.assertFalse(reader.handle_reader_navigation("Right", {"shift"}))
        self.assertEqual(reader.manual_scrolls, 0)

    def test_book_end_reaches_actual_last_text_offset(self):
        reader = ReaderHarness()
        reader.handle_reader_navigation("End", {"control"})
        self.assertEqual(reader.moves, [(1, 7000)])
        self.assertEqual(reader.saves, 1)

    def test_down_in_document_updates_position_after_scroll(self):
        reader = ReaderHarness(paged=True)
        reader.handle_reader_navigation("Down", ())
        self.assertEqual(reader.adjustment.value, 40)
        self.assertEqual(reader.positions, [("geometry", 12345)])


class FocusGuardTests(unittest.TestCase):
    def reader(self):
        return SimpleNamespace(_closing=False, book=object(), stack=SimpleNamespace(get_visible_child_name=lambda: "reader"), _immersive_visible_dialog=lambda: False, get_focus=lambda: None)

    def test_reading_without_explicit_focus_accepts_keys(self):
        self.assertTrue(KeyboardNavigationMixin.reading_navigation_has_focus(self.reader()))

    def test_chooser_or_open_popover_prevents_navigation(self):
        for attribute, value in (("_accessibility_popup_tick", 42), ("_native_chooser", object()), ("_portal_chooser", SimpleNamespace(active=True)), ("search_popover", SimpleNamespace(get_visible=lambda: True))):
            reader = self.reader()
            setattr(reader, attribute, value)
            with self.subTest(attribute=attribute):
                self.assertFalse(KeyboardNavigationMixin.reading_navigation_has_focus(reader))

    def test_search_entry_and_toolbar_focus_preserve_their_own_keys(self):
        reader = self.reader()
        reader.reader_scroll = object()
        focus = SimpleNamespace(get_root=lambda: reader, get_parent=lambda: None, is_ancestor=lambda _widget: False)
        reader.get_focus = lambda: focus
        with patch("malferma_libro.keyboard_ui._gtk", return_value=SimpleNamespace(Popover=type("Popover", (), {}))):
            self.assertFalse(KeyboardNavigationMixin.reading_navigation_has_focus(reader))


class ImmersivePolicyTests(unittest.TestCase):
    def test_regular_window_and_high_contrast_keep_header_visible(self):
        policy = HeaderVisibility()
        active = HeaderContext(fullscreen=True, reading=True, has_book=True)
        for context in (HeaderContext(), replace(active, accessibility=True), replace(active, enabled=False)):
            with self.subTest(context=context):
                self.assertTrue(policy.sync(context, 0))
                self.assertTrue(policy.sync(context, 100))

    def test_idle_fullscreen_header_hides_and_keyboard_reveals_it(self):
        policy = HeaderVisibility(delay=2)
        context = HeaderContext(fullscreen=True, reading=True, has_book=True)
        self.assertTrue(policy.sync(context, 0))
        self.assertFalse(policy.sync(context, 2.1))
        self.assertTrue(policy.keyboard(context, 3))
        self.assertFalse(policy.sync(context, 5.1))

    def test_open_menu_protects_header_and_resets_idle_delay(self):
        policy = HeaderVisibility(delay=2)
        active = HeaderContext(fullscreen=True, reading=True, has_book=True)
        policy.sync(active, 0)
        self.assertTrue(policy.sync(replace(active, popup=True), 10))
        self.assertTrue(policy.sync(active, 11))
        self.assertTrue(policy.sync(active, 12.9))
        self.assertFalse(policy.sync(active, 13.1))


if __name__ == "__main__":
    unittest.main()
