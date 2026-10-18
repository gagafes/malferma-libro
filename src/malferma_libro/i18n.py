"""Small, process-local gettext interface shared by the GUI and its workers.

Russian strings are the source catalog.  Importing a reader module alone does
not change its messages; the application selects its language at startup and
can replace the active catalog while its existing windows remain open.
"""

from __future__ import annotations

import gettext
import os
from pathlib import Path
from typing import Mapping


# Endonyms stay readable when the surrounding interface uses another language.
# Keep the original choices first so stored UI indices and keyboard habits do
# not change as languages are added; only codes are persisted to settings.
LANGUAGE_CHOICES = (
    ("ru", "Русский"),
    ("en", "English"),
    ("eo", "Esperanto"),
    ("uk", "Українська"),
    ("ar", "العربية"),
    ("he", "עברית"),
    ("de", "Deutsch"),
    ("kk", "Қазақша"),
    ("fa", "فارسی"),
    ("lt", "Lietuvių"),
    ("lv", "Latviešu"),
    ("et", "Eesti"),
    ("es", "Español"),
    ("fr", "Français"),
    ("it", "Italiano"),
    ("pt", "Português"),
    ("ro", "Română"),
    ("ca", "Català"),
    ("nl", "Nederlands"),
    ("sv", "Svenska"),
    ("da", "Dansk"),
    ("nb", "Norsk bokmål"),
    ("nn", "Norsk nynorsk"),
    ("is", "Íslenska"),
    ("tr", "Türkçe"),
    ("az", "Azərbaycanca"),
    ("uz", "Oʻzbekcha"),
    ("ky", "Кыргызча"),
    ("tt", "Татарча"),
    ("tk", "Türkmençe"),
    ("am", "አማርኛ"),
    ("mt", "Malti"),
    ("yi", "ייִדיש"),
    ("be", "Беларуская"),
    ("pl", "Polski"),
    ("cs", "Čeština"),
    ("sk", "Slovenčina"),
    ("sl", "Slovenščina"),
    ("hr", "Hrvatski"),
    ("bs", "Bosanski"),
    ("sr", "Српски"),
    ("sr_Latn", "Srpski (latinica)"),
    ("mk", "Македонски"),
    ("bg", "Български"),
    ("eu", "Euskara"),
    ("sq", "Shqip"),
    ("hsb", "Hornjoserbšćina"),
    ("dsb", "Dolnoserbšćina"),
    ("rue", "Русиньскый"),
)
SUPPORTED_LANGUAGES = tuple(code for code, _name in LANGUAGE_CHOICES)
INTERFACE_LANGUAGE_CODES = ("system", *SUPPORTED_LANGUAGES)
# Narration is deliberately narrower than interface/book language support.
SPEECH_LANGUAGE_CHOICES = (
    ("ru", "Русский"),
    ("uk", "Українська"),
    ("en", "English"),
    ("de", "Deutsch"),
    ("fr", "Français"),
    ("es", "Español"),
    ("it", "Italiano"),
    ("pt", "Português"),
)
SPEECH_LANGUAGE_CODES = ("auto", *(code for code, _name in SPEECH_LANGUAGE_CHOICES))
RTL_LANGUAGES = frozenset({"ar", "he", "fa", "yi"})
DOMAIN = "malferma-libro"
LOCALE_DIR = Path(__file__).resolve().parent / "locale"

_translator: gettext.NullTranslations = gettext.NullTranslations()


def _language_code(value: str) -> str | None:
    """Accept POSIX locale names and common BCP 47 language tags."""
    name = value.strip().lower().replace("-", "_")
    locale_name, _separator, modifier = name.partition("@")
    parts = locale_name.split(".", 1)[0].split("_")
    base = parts[0]
    base = {"iw": "he", "ji": "yi", "no": "nb", "mo": "ro"}.get(base, base)
    # A BCP 47 script follows the language. A later "latn" can instead be a
    # numbering system (sr-Cyrl-RS-u-nu-latn) or private-use content.
    if base == "sr" and (parts[1:2] == ["latn"] or modifier in {"latin", "latn"}):
        return "sr_Latn"
    if base in {"c", "posix"}:
        return "en"
    return base if base in SUPPORTED_LANGUAGES else None


def is_rtl_language(language: str) -> bool:
    """Return the interface direction without inspecting book contents."""
    return _language_code(language) in RTL_LANGUAGES


def resolve_language(choice: str = "system", environ: Mapping[str, str] | None = None) -> str:
    """Resolve a preference without changing the process locale or environment.

    LANGUAGE is a colon-separated preference list, followed by the effective
    LC_ALL / LC_MESSAGES / LANG locale. Unsupported languages fall back to
    English; Russian remains an explicit, fully supported source language.
    """
    if choice != "system":
        return _language_code(choice) or "en"
    environment = os.environ if environ is None else environ
    for candidate in environment.get("LANGUAGE", "").split(":"):
        if language := _language_code(candidate):
            return language
    for key in ("LC_ALL", "LC_MESSAGES", "LANG"):
        if value := environment.get(key, "").strip():
            # A defined higher-priority locale overrides every lower one even
            # when we do not provide its translation.
            return _language_code(value) or "en"
    return "en"


def configure_language(choice: str = "system", environ: Mapping[str, str] | None = None) -> str:
    """Load the selected bundled catalog and atomically replace the translator."""
    global _translator
    language = resolve_language(choice, environ)
    if language == "ru":
        translator = gettext.NullTranslations()
    else:
        translator = gettext.translation(
            DOMAIN, localedir=LOCALE_DIR, languages=[language], fallback=True,
        )
    _translator = translator
    return language


def _(message: str) -> str:
    """Translate at call time, including when imported before app startup."""
    return _translator.gettext(message)


def N_(message: str) -> str:
    """Mark a stored source message for translation when it is displayed."""
    return message


def ngettext(singular: str, plural: str, number: int) -> str:
    return _translator.ngettext(singular, plural, number)
