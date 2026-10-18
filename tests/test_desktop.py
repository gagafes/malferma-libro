"""Desktop integration that can be checked without a graphical session."""

from pathlib import Path
import unittest
from unittest.mock import patch

from malferma_libro.desktop import file_uri_to_path, request_path, response_paths
from malferma_libro.desktop_settings import (
    DesktopAppearance, portal_dark_preference, theme_dark_preference,
    uses_gnome_desktop_settings,
)
from malferma_libro.shortcuts import (
    BindingError, find_conflict, normalize_custom_shortcuts, shortcut_for,
    validate_binding,
)


class FileSelectionTests(unittest.TestCase):
    def test_unicode_and_literal_percent_are_decoded_only_once(self):
        self.assertEqual(file_uri_to_path("file:///tmp/%D0%9B%D0%B5%D1%81%D1%8F%20%D0%A3.txt"),
                         Path("/tmp/Леся У.txt"))
        self.assertEqual(file_uri_to_path("file://localhost/tmp/100%2520.txt"), Path("/tmp/100%20.txt"))

    def test_nonlocal_and_malformed_uris_are_not_imported(self):
        for uri in ("file://server/book.txt", "https://example.org/book.txt",
                    "file:///tmp/a%00.txt", "file:///tmp/a%GG.txt", "file:///tmp/a#note",
                    "file:///tmp/a?query=1", "file:relative.txt", "file:///tmp/a\n.txt", None):
            with self.subTest(uri=uri):
                self.assertIsNone(file_uri_to_path(uri))

    def test_cancelled_selection_is_not_reopened_or_imported(self):
        self.assertEqual(response_paths(1, {"uris": ["file:///tmp/book.txt"]}), [])
        self.assertEqual(response_paths(True, {"uris": ["file:///tmp/book.txt"]}), [])
        self.assertEqual(response_paths(0, {"uris": "file:///tmp/book.txt"}), [])

    def test_selection_deduplicates_local_books(self):
        self.assertEqual(response_paths(0, {"uris": ["file:///tmp/book.txt",
                         "file://localhost/tmp/book.txt", "https://example.org/book.txt"]}),
                         [Path("/tmp/book.txt")])

    def test_request_path_cannot_escape_dbus_object_path(self):
        self.assertEqual(request_path(":1.42", "book_123"),
                         "/org/freedesktop/portal/desktop/request/1_42/book_123")
        for sender, token in ((":1.2", "../request"), ("1/2", "book"), (":1.2", "")):
            with self.subTest(sender=sender, token=token), self.assertRaises(ValueError):
                request_path(sender, token)


class DesktopAppearanceTests(unittest.TestCase):
    def test_portal_no_preference_and_boolean_do_not_force_a_theme(self):
        self.assertIsNone(portal_dark_preference(0))
        self.assertIsNone(portal_dark_preference(True))
        self.assertIsNone(portal_dark_preference(3))
        self.assertIs(portal_dark_preference(((1,),)), True)
        self.assertIs(portal_dark_preference((2,)), False)

    def test_desktop_specific_preferences_are_not_taken_from_another_session(self):
        for session in ("KDE", "XFCE", "X-Cinnamon", None):
            with self.subTest(session=session):
                self.assertFalse(uses_gnome_desktop_settings(session))
        self.assertTrue(uses_gnome_desktop_settings("ubuntu:GNOME"))

    def test_internal_adwaita_theme_does_not_overwrite_desktop_preference(self):
        self.assertIsNone(theme_dark_preference("Adwaita-empty"))
        self.assertTrue(theme_dark_preference("Adwaita-dark"))
        self.assertTrue(theme_dark_preference("HighContrastInverse"))
        self.assertFalse(theme_dark_preference("Adwaita"))

    def test_fallback_notifies_once_and_disconnects_on_close(self):
        class Settings:
            values = {"gtk-theme-name": "Adwaita-dark", "gtk-application-prefer-dark-theme": False}

            def __init__(self):
                self.handlers = {}

            def get_property(self, name):
                return self.values[name]

            def connect(self, name, callback):
                identifier = len(self.handlers) + 1
                self.handlers[identifier] = callback
                return identifier

            def disconnect(self, identifier):
                del self.handlers[identifier]

        settings, changed = Settings(), []
        with patch("malferma_libro.desktop_settings._load_gio", side_effect=ImportError):
            appearance = DesktopAppearance(settings, changed.append)
        self.assertTrue(appearance.dark)
        settings.values = {"gtk-theme-name": "Adwaita", "gtk-application-prefer-dark-theme": False}
        appearance._gtk_changed()
        appearance._gtk_changed()
        self.assertEqual(changed, [False])
        appearance.close()
        appearance.close()
        self.assertEqual(settings.handlers, {})


class CustomShortcutTests(unittest.TestCase):
    def test_plain_typing_and_system_copy_are_preserved(self):
        for binding in ({"key": "a", "modifiers": []},
                        {"key": "c", "modifiers": ["control"]},
                        {"key": "F4", "modifiers": ["alt"]}):
            with self.subTest(binding=binding), self.assertRaises(BindingError):
                validate_binding(binding, action="open")

    def test_custom_shortcut_conflict_includes_cyrillic_alias(self):
        self.assertEqual(find_conflict("open", {"key": "Cyrillic_a", "modifiers": ["control"]}),
                         "search")

    def test_custom_profile_can_swap_two_actions_and_disable_narration(self):
        profile = {"open": {"key": "f", "modifiers": ["control"]},
                   "search": {"key": "o", "modifiers": ["control"]}, "speech": None}
        self.assertEqual(normalize_custom_shortcuts(profile), profile)
        settings = {"shortcut_mode": "custom", "custom_shortcuts": profile}
        self.assertEqual(shortcut_for("f", {"control"}, settings=settings), "open")
        self.assertEqual(shortcut_for("Cyrillic_shcha", {"control"}, settings=settings), "search")
        self.assertIsNone(shortcut_for("space", (), reading=True, has_book=True,
                                      reading_focus=True, settings=settings))


if __name__ == "__main__":
    unittest.main()
