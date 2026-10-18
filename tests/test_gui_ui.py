"""Native UI checks; run with RUN_GUI_TESTS=1 under a graphical display.

These exercise real GTK widgets and allocations rather than matching source
text. An unavailable GTK runtime/display is reported as a skip.
"""

import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch


def descendants(widget):
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from descendants(child)
        child = child.get_next_sibling()


def widget_geometry(widget, relative_to):
    """Expose native allocation details when a layout assertion fails in CI."""
    valid, bounds = widget.compute_bounds(relative_to)
    return {
        "visible": widget.get_visible(), "mapped": widget.get_mapped(),
        "size": (widget.get_width(), widget.get_height()),
        "bounds": (bounds.get_x(), bounds.get_y(), bounds.get_width(), bounds.get_height())
                  if valid else None,
    }


def direct_children(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        child = child.get_next_sibling()


def widget_measure(widget, orientation):
    minimum, natural, _minimum_baseline, _natural_baseline = widget.measure(orientation, -1)
    details = {"type": type(widget).__name__, "minimum": minimum, "natural": natural}
    for attribute in ("get_text", "get_label"):
        getter = getattr(widget, attribute, None)
        if getter is not None:
            details[attribute.removeprefix("get_")] = getter()
            break
    return details


class ReaderInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("RUN_GUI_TESTS") != "1":
            raise unittest.SkipTest("Set RUN_GUI_TESTS=1 to exercise the native GTK interface")
        try:
            import gi
            gi.require_version("Gtk", "4.0")
            gi.require_version("Adw", "1")
            from gi.repository import Adw, Gdk, GLib, Gtk, Pango
        except (ImportError, ValueError) as error:
            raise unittest.SkipTest(f"Native GTK/libadwaita unavailable: {error}") from error
        if not Gtk.init_check():
            raise unittest.SkipTest("Native GTK requires a graphical display")
        Adw.init()
        cls.Gdk, cls.GLib, cls.Gtk, cls.Pango = Gdk, GLib, Gtk, Pango
        from malferma_libro.app import ReaderApplication, ReaderWindow
        cls.ReaderWindow = ReaderWindow
        cls.application = ReaderApplication()
        cls.application.register(None)

    @classmethod
    def tearDownClass(cls):
        cls.application.quit()

    def setUp(self):
        from malferma_libro.storage import Library
        self.temporary = tempfile.TemporaryDirectory(prefix="malferma-ui-test-")
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

    def open_text_book(self):
        from malferma_libro.books import Book, Chapter
        book = Book("Interface fixture", "", [Chapter("One", "Reading text. " * 100)], "TXT")
        path = self.root / "fixture.txt"
        path.write_text(book.chapters[0].text)
        record = self.library.import_book(path, book)
        self.window.show_book(record, book)
        self.pump()

    def test_text_size_has_one_group_in_accessibility_menu(self):
        window = self.window
        buttons = (window.text_size_decrease, window.text_size_reset, window.text_size_increase)
        for control in buttons:
            self.assertIs(control.get_parent(), window.text_size_actions)
            self.assertTrue(control.is_ancestor(window.accessibility_content))
        # A MenuButton's popover remains in the header's widget ancestry even
        # though it is displayed in a separate surface. Check its actual owner.
        self.assertTrue(window.text_size_actions.is_ancestor(window.accessibility_popover))
        for obsolete in ("text_size_menu_button", "compact_text_size_buttons", "accessibility_text_increase"):
            self.assertFalse(hasattr(window, obsolete))
        self.open_text_book()
        self.assertEqual(window.font_size.get_value_as_int(), 20)
        window.text_size_increase.emit("clicked")
        self.assertEqual(window.font_size.get_value_as_int(), 22)
        window.text_size_reset.emit("clicked")
        self.assertEqual(window.font_size.get_value_as_int(), 20)
        self.assertFalse(window.text_size_reset.get_sensitive())
        window.font_size.set_value(96)
        self.assertFalse(window.text_size_increase.get_sensitive())

    def test_toc_is_the_single_chapter_list_and_tools_are_document_only(self):
        self.open_text_book()
        self.assertFalse(hasattr(self.window, "chapter_dropdown"))
        self.assertFalse(hasattr(self.window, "compact_previous_button"))
        self.assertTrue(self.window.previous_button.get_visible())
        self.assertTrue(self.window.next_button.get_visible())
        self.assertFalse(self.window.reader_tools_button.get_visible())
        self.assertIsNotNone(self.window.toc.get_first_child())

    def test_accessibility_does_not_repeat_the_settings_button(self):
        from malferma_libro.live_i18n import localized
        settings = str(localized("Настройки"))
        buttons = [widget for widget in descendants(self.window.accessibility_content)
                   if isinstance(widget, self.Gtk.Button) and widget.get_label() == settings]
        self.assertEqual(buttons, [])
        self.assertIsNotNone(self.window.lookup_action("preferences"))

    def test_interface_font_is_larger_without_changing_book_font(self):
        self.open_text_book()
        # An unattached label has the native system font and no window rule.
        # Compare visible plain labels; Adwaita gives headings a separate size.
        baseline = self.Gtk.Label(label="System font")
        baseline_font = baseline.get_pango_context().get_font_description()
        interface_font = self.window.reading_progress.get_pango_context().get_font_description()
        original, actual = baseline_font.get_size(), interface_font.get_size()
        font_details = {
            "baseline": baseline_font.to_string(), "interface": interface_font.to_string(),
            "gtk-font-name": self.Gtk.Settings.get_default().get_property("gtk-font-name"),
        }
        self.assertAlmostEqual(actual / original, 1.15, delta=0.04, msg=font_details)
        self.window.accessibility_popover.popup()
        self.pump()
        menu_font = self.window.speech_status.get_pango_context().get_font_description()
        menu_size = menu_font.get_size()
        self.assertAlmostEqual(menu_size / actual, 1.0, delta=0.04,
                               msg={**font_details, "menu": menu_font.to_string()})
        self.assertEqual(self.window.font_size.get_value_as_int(), 20)
        self.window.preferences_window.present()
        self.pump()
        preference_font = self.window.interface_language_selector.get_pango_context().get_font_description()
        preference_size = preference_font.get_size()
        self.assertAlmostEqual(preference_size / actual, 1.0, delta=0.04,
                               msg={**font_details, "preferences": preference_font.to_string()})

    def test_scrollbar_has_its_own_space_in_ltr_and_rtl(self):
        window = self.window
        window.set_default_size(560, 420)
        self.open_text_book()
        for language in ("en", "he"):
            with self.subTest(language=language):
                window.apply_interface_language(language)
                window.accessibility_popover.popup()
                self.pump()
                scroll = window.accessibility_scroll
                self.assertFalse(scroll.get_overlay_scrolling())
                bar = scroll.get_vscrollbar()
                self.assertGreater(bar.get_width(), 0)
                content_ok, content_bounds = window.accessibility_content.compute_bounds(scroll)
                bar_ok, bar_bounds = bar.compute_bounds(scroll)
                self.assertTrue(content_ok and bar_ok)
                geometry = {name: widget_geometry(widget, scroll) for name, widget in (
                    ("content", window.accessibility_content), ("viewport", scroll.get_child()),
                    ("scrollbar", bar), ("scroller", scroll),
                )}
                horizontal = self.Gtk.Orientation.HORIZONTAL
                geometry.update({
                    "min_content_width": scroll.get_min_content_width(),
                    "max_content_width": scroll.get_max_content_width(),
                    "scroll_size_request": scroll.get_size_request(),
                    "popover": widget_geometry(window.accessibility_popover, window),
                    "window": widget_geometry(window, window),
                    "content_measure": widget_measure(window.accessibility_content, horizontal),
                    "rows": [
                        {**widget_measure(row, horizontal),
                         "children": [widget_measure(child, horizontal) for child in direct_children(row)]}
                        for row in direct_children(window.accessibility_content)
                    ],
                })
                self.assertTrue(
                    content_bounds.get_x() + content_bounds.get_width() <= bar_bounds.get_x() + 1
                    or bar_bounds.get_x() + bar_bounds.get_width() <= content_bounds.get_x() + 1,
                    msg={"language": language, **geometry},
                )
                self.assertLessEqual(scroll.get_height(), window.get_height() - 80)
                window.accessibility_popover.popdown()

    def test_toolbar_stays_within_a_narrow_window(self):
        self.open_text_book()
        self.window.set_default_size(560, 420)
        self.pump()
        self.assertLessEqual(self.window.get_width(), 560)
        header_width = self.window.header.get_width()
        for control in (self.window.open_button, self.window.toc_button,
                        self.window.previous_button, self.window.next_button,
                        self.window.search_button, self.window.bookmarks_button,
                        self.window.day_night_button, self.window.fullscreen_button,
                        self.window.accessibility_button, self.window.main_menu_button):
            mapped, bounds = control.compute_bounds(self.window.header)
            self.assertTrue(mapped)
            self.assertGreaterEqual(bounds.get_x(), -1)
            self.assertLessEqual(bounds.get_x() + bounds.get_width(), header_width + 1)

    def test_accessibility_menu_fits_resized_window_and_observes_only_while_mapped(self):
        window = self.window
        window.set_default_size(900, 820)
        # GTK closes an existing popup while its native window is resized.
        # Finish the initial resize before testing the popup's own observer.
        self.pump()
        window.accessibility_popover.popup()
        self.pump()
        self.assertTrue(window.accessibility_popover.get_visible())
        self.assertTrue(window.accessibility_popover.get_mapped())
        self.assertIsNotNone(window._accessibility_resize_tick, msg={
            "popover": widget_geometry(window.accessibility_popover, window),
            "button": widget_geometry(window.accessibility_button, window),
            "window": widget_geometry(window, window),
            "allocation": window._accessibility_allocation,
        })
        self.assertEqual(window._accessibility_allocation, (window.get_width(), window.get_height()))
        window.set_default_size(560, 420)
        self.pump()
        if not window.accessibility_popover.get_mapped():
            # Native GTK may close a popup while resizing its parent window.
            # Its observer must stop, and reopening must use the new allocation.
            self.assertIsNone(window._accessibility_resize_tick)
            window.accessibility_popover.popup()
            self.pump()
        self.assertTrue(window.accessibility_popover.get_visible())
        self.assertTrue(window.accessibility_popover.get_mapped())
        self.assertIsNotNone(window._accessibility_resize_tick)
        self.assertEqual(window._accessibility_allocation, (window.get_width(), window.get_height()))
        self.assertEqual(window.accessibility_scroll.get_max_content_height(),
                         max(120, min(560, window.get_height() - 96)))
        window.accessibility_popover.popdown()
        self.pump()
        self.assertIsNone(window._accessibility_resize_tick)

    def test_escape_closes_library_and_operation_menus_without_focus(self):
        window = self.window
        # Both menus can still be visible while keyboard focus belongs to the
        # toolbar button. Escape must close them before the fullscreen action.
        window.operation_button.set_visible(True)
        window.operation_button.set_sensitive(True)
        for popover in (window.library_controls.get_popover(), window.operation_popover):
            with self.subTest(popover=popover):
                popover.popup()
                self.pump()
                self.assertTrue(popover.get_visible())
                window.set_focus(None)
                self.assertTrue(window.on_key(None, self.Gdk.KEY_Escape, 0, self.Gdk.ModifierType(0)))
                self.pump()
                self.assertFalse(popover.get_visible())


if __name__ == "__main__":
    unittest.main()
