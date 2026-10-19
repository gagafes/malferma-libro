# SPDX-License-Identifier: GPL-3.0-or-later
"""Catalog recovery and the reader's public runtime translation behavior."""
from __future__ import annotations

import gettext
import gc
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import weakref

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from malferma_libro import i18n
from malferma_libro import live_i18n
from malferma_libro.helptext import manual_language, short_help

SPEC = importlib.util.spec_from_file_location("reader_translation_build", ROOT / "packaging" / "translations.py")
translations = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = translations
SPEC.loader.exec_module(translations)


def header(language="en", plurals="nplurals=2; plural=(n != 1);"):
    return translations.Entry("", {0: (
        "Project-Id-Version: Malferma Libro 0.1.1\n"
        f"Language: {language}\n"
        "MIME-Version: 1.0\nContent-Type: text/plain; charset=UTF-8\n"
        "Content-Transfer-Encoding: 8bit\n"
        f"Plural-Forms: {plurals}\n"
    )})


class CatalogTests(unittest.TestCase):
    def tearDown(self):
        i18n.configure_language("ru")

    def test_editable_catalogs_cover_source_and_match_runtime(self):
        expected = set(translations.source_messages())
        template = translations.read_po(ROOT / "po" / "malferma-libro.pot")
        self.assertEqual({entry.key for entry in template}, expected | {""})
        self.assertEqual({path.stem for path in (ROOT / "po").glob("*.po")},
                         set(i18n.SUPPORTED_LANGUAGES) - {"ru"})
        for language in i18n.SUPPORTED_LANGUAGES:
            with self.subTest(language=language):
                self.assertEqual(i18n.configure_language(language), language)
                self.assertTrue(i18n._("Сетевые библиотеки"))
                if language == "ru":
                    self.assertEqual(i18n._("Сетевые библиотеки"), "Сетевые библиотеки")
                    continue
                entries = translations.read_po(ROOT / "po" / f"{language}.po")
                compiled = translations.validate(entries, language, expected)
                mo = i18n.LOCALE_DIR / language / "LC_MESSAGES" / "malferma-libro.mo"
                self.assertEqual(mo.read_bytes(), compiled)
                self.assertNotEqual(i18n._("Сетевые библиотеки"), "Сетевые библиотеки")

    def test_standard_po_multiline_context_and_plural_round_trip(self):
        fixture = '''msgid ""
msgstr "Project-Id-Version: Malferma Libro 0.1.1\\n"
"Language: en\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\\n"

msgctxt "verb"
msgid "Открыть"
msgstr "Open"

msgid "книга"
msgid_plural "книги"
msgstr[0] "book"
msgstr[1] "books"

msgid "строка\\nс \\"кавычками\\""
msgstr "line\\nwith \\"quotes\\""
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "en.po"
            path.write_text(fixture, encoding="utf-8")
            entries = translations.read_po(path)
            data = translations.validate(entries, "en", {"verb\x04Открыть", "книга", 'строка\nс "кавычками"'})
            catalog = gettext.GNUTranslations(io.BytesIO(data))
            self.assertEqual(catalog.pgettext("verb", "Открыть"), "Open")
            self.assertEqual(catalog.ngettext("книга", "книги", 1), "book")
            self.assertEqual(catalog.ngettext("книга", "книги", 2), "books")
            self.assertEqual(catalog.gettext('строка\nс "кавычками"'), 'line\nwith "quotes"')
            translations.write_po(path, entries, {})
            self.assertEqual(translations.compile_mo(translations.read_po(path)), data)

    def test_bad_translation_cannot_drop_interpolation_fields(self):
        entries = [header(), translations.Entry("Страница {page} из {pages}", {0: "Page {page}"})]
        with self.assertRaisesRegex(ValueError, "format fields differ"):
            translations.validate(entries, "en", {"Страница {page} из {pages}"})

    def test_bad_plural_expression_cannot_select_missing_forms(self):
        with self.assertRaisesRegex(ValueError, "plural expression out of range"):
            translations.validate([header(plurals="nplurals=2; plural=9;")], "en", set())

    def test_bad_plural_arithmetic_is_reported_as_a_catalog_error(self):
        with self.assertRaisesRegex(ValueError, "invalid plural expression"):
            translations.validate([header(plurals="nplurals=2; plural=(n / (n - 1));")], "en", set())

    def test_check_rejects_a_missing_runtime_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, po = root / "src", root / "po"
            source.mkdir()
            po.mkdir()
            (source / "i18n.py").write_text('LANGUAGE_CHOICES = (("ru", "Русский"), ("en", "English"))\n', encoding="utf-8")
            translations.write_po(po / "en.po", [header()], {})
            translations.write_po(po / "malferma-libro.pot", [header()], {})
            argv = ["translations.py", "--check", "--output-dir", str(root / "locale")]
            errors = io.StringIO()
            with patch.object(translations, "SOURCE", source), \
                    patch.object(translations, "PO_DIR", po), \
                    patch.object(translations, "source_messages", return_value={}), \
                    patch.object(sys, "argv", argv), patch.object(sys, "stderr", errors), \
                    self.assertRaises(SystemExit) as failure:
                translations.main()
            self.assertEqual(failure.exception.code, 1)
            self.assertIn("compiled MO is missing", errors.getvalue())

    def test_live_language_selection_and_rtl_aliases(self):
        translate = i18n._
        i18n.configure_language("de-DE")
        german = translate("Сетевые библиотеки")
        i18n.configure_language("uk-UA")
        ukrainian = translate("Сетевые библиотеки")
        self.assertNotEqual(german, ukrainian)
        for language in ("ar", "he_IL", "fa-IR", "yi"):
            self.assertTrue(i18n.is_rtl_language(language))
        self.assertFalse(i18n.is_rtl_language("uk-UA"))
        self.assertEqual(i18n.resolve_language("system", {"LC_ALL": "eo.UTF-8"}), "eo")

    def test_locale_precedence_aliases_and_script_subtags(self):
        for value, expected in (("sr-Latn-RS", "sr_Latn"), ("sr_RS.UTF-8@latin", "sr_Latn"),
                                ("sr-Cyrl-RS-u-nu-latn", "sr"), ("iw_IL", "he"),
                                ("ji", "yi"), ("no_NO", "nb"), ("C.UTF-8", "en")):
            with self.subTest(locale=value):
                self.assertEqual(i18n.resolve_language(value), expected)
        self.assertEqual(i18n.resolve_language("system", {"LANGUAGE": "xx:uk:de", "LC_ALL": "en"}), "uk")
        self.assertEqual(i18n.resolve_language("system", {"LC_ALL": "zz", "LANG": "uk"}), "en")
        self.assertEqual(i18n.resolve_language("system", {"LC_MESSAGES": "de_DE.UTF-8", "LANG": "uk"}), "de")

    def test_offline_help_uses_available_manual_languages(self):
        for language in ("ru", "en", "de", "uk"):
            with self.subTest(language=language):
                self.assertEqual(manual_language(language), language)
                self.assertIn(f"--manual={language}", short_help(language))
                self.assertIn("0.1.1", short_help(language))
        self.assertEqual(manual_language("ar"), "en")
        self.assertEqual(short_help("he"), short_help("en"))


class TranslationBindingTests(unittest.TestCase):
    class Target:
        def __init__(self):
            self.properties = {}

        def set_property(self, name, value):
            self.properties[name] = value

        def set_xalign(self, value):
            self.properties["xalign"] = value

    def tearDown(self):
        i18n.configure_language("ru")

    def test_live_formatted_labels_preserve_unicode_user_values(self):
        bindings = live_i18n.TranslationBindings()
        target = self.Target()
        title = "שלום — Україна — ŭ — e\u0301 — 👩🏽\u200d💻"
        i18n.configure_language("en")
        value = live_i18n.localized("Обложка книги «{title}»").format(title=title)
        bindings.bind(target, label=value)
        self.assertIn(title, target.properties["label"])
        before = target.properties["label"]
        i18n.configure_language("ar")
        bindings.refresh(rtl=True)
        self.assertNotEqual(target.properties["label"], before)
        self.assertIn(title, target.properties["label"])

    def test_replacing_localized_text_with_book_text_clears_its_binding(self):
        bindings = live_i18n.TranslationBindings()
        target = self.Target()
        bindings.bind(target, label=live_i18n.localized("Настройки"))
        bindings.bind(target, label="Настройки")
        i18n.configure_language("de")
        bindings.refresh()
        self.assertEqual(target.properties["label"], "Настройки")

    def test_sequences_refresh_only_marked_messages_and_keep_direction(self):
        bindings = live_i18n.TranslationBindings()
        target = self.Target()
        bindings.bind_sequence(target, "items", [live_i18n.localized("Настройки"), "Настройки"],
                               lambda item, values: item.set_property("items", values))
        bindings.leading_label(target)
        i18n.configure_language("he")
        bindings.refresh(rtl=True)
        self.assertEqual(target.properties["items"], (i18n._("Настройки"), "Настройки"))
        self.assertEqual(target.properties["xalign"], 1)
        i18n.configure_language("uk")
        bindings.refresh(rtl=False)
        self.assertEqual(target.properties["items"], (i18n._("Настройки"), "Настройки"))
        self.assertEqual(target.properties["xalign"], 0)

    def test_bindings_do_not_retain_removed_rows(self):
        bindings = live_i18n.TranslationBindings()
        target = self.Target()
        reference = weakref.ref(target)
        bindings.bind(target, label=live_i18n.localized("Настройки"))
        bindings.leading_label(target)
        del target
        gc.collect()
        self.assertIsNone(reference())
        bindings.refresh()


if __name__ == "__main__":
    unittest.main()
