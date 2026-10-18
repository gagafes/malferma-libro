"""Shared, offline help and legal text for the CLI and the GTK interface."""

from __future__ import annotations

from importlib.resources import files

from . import APP_NAME, __version__
from .i18n import resolve_language


MANUAL_LANGUAGES = ("ru", "en", "de", "uk")


def _document(name: str) -> str:
    return files(__package__).joinpath("assets", "docs", name).read_text(encoding="utf-8")


def manual_language(language: str = "system") -> str:
    """Resolve manual language from the CLI environment or an interface code.

    The interface has more translations than the complete manual. A locale
    without its own manual gets English, without consulting GUI preferences.
    """
    resolved = resolve_language(language)
    return resolved if resolved in MANUAL_LANGUAGES else "en"


def manual_text(language: str = "system") -> str:
    """Read a complete bundled manual without opening a browser or GUI."""
    code = manual_language(language)
    return _document("MANUAL.md" if code == "ru" else f"MANUAL.{code}.md")


def license_text() -> str:
    """Return the unabridged GNU GPL v3 text distributed with the code."""
    return _document("LICENSE")


def short_help(language: str = "system") -> str:
    """Return the full small CLI reference in RU, EN, DE or UK."""
    language = manual_language(language)
    if language == "ru":
        return f"""{APP_NAME} {__version__} — читалка EPUB, FB2, TXT, HTML/XHTML, Markdown, PDF, DjVu и CBZ

Использование: malferma-libro [ПАРАМЕТРЫ] [--] [ФАЙЛ ...]

  -h, --help       Краткая справка без запуска графического интерфейса
      --manual     Полное руководство на языке окружения (иначе английский)
      --manual=КОД Язык руководства: ru, en, de или uk
      --license    Полный текст GNU GPL v3 в терминале
      --version    Название и версия программы
      --           Все последующие аргументы считаются именами файлов

Примеры:
  malferma-libro "Книга с пробелами.epub" "Другая книга.fb2"
  malferma-libro -- -книга.txt
  malferma-libro --manual
  malferma-libro --manual=ru

Руководство также доступно в меню приложения, по умолчанию по F1,
и в man malferma-libro.
"""
    if language == "de":
        return f"""{APP_NAME} {__version__} — Leseprogramm für EPUB, FB2, TXT, HTML/XHTML, Markdown, PDF, DjVu und CBZ

Verwendung: malferma-libro [OPTIONEN] [--] [DATEI ...]

  -h, --help       Diese Hilfe ohne grafische Oberfläche anzeigen
      --manual     Vollständiges Handbuch gemäß Sprachumgebung (sonst Englisch)
      --manual=CODE Sprache des Handbuchs: ru, en, de oder uk
      --license    Vollständigen Text der GNU GPL v3 im Terminal ausgeben
      --version    Namen und Version der Anwendung ausgeben
      --           Alle folgenden Argumente als Dateinamen behandeln

Beispiele:
  malferma-libro "Buch mit Leerzeichen.epub" "Другая книга.fb2"
  malferma-libro -- -buch.txt
  malferma-libro --manual
  malferma-libro --manual=de

Das Handbuch ist auch im Anwendungsmenü, standardmäßig mit F1
und mit man malferma-libro verfügbar.
"""
    if language == "uk":
        return f"""{APP_NAME} {__version__} — читалка EPUB, FB2, TXT, HTML/XHTML, Markdown, PDF, DjVu і CBZ

Використання: malferma-libro [ПАРАМЕТРИ] [--] [ФАЙЛ ...]

  -h, --help       Коротка довідка без запуску графічного інтерфейсу
      --manual     Повний посібник мовою оточення (інакше англійською)
      --manual=КОД Мова посібника: ru, en, de або uk
      --license    Повний текст GNU GPL v3 у терміналі
      --version    Назва та версія програми
      --           Усі наступні аргументи вважаються назвами файлів

Приклади:
  malferma-libro "Книга з пробілами.epub" "Інша книга.fb2"
  malferma-libro -- -книга.txt
  malferma-libro --manual
  malferma-libro --manual=uk

Посібник також доступний у меню програми, типово за клавішею F1,
і в man malferma-libro.
"""
    return f"""{APP_NAME} {__version__} — EPUB, FB2, TXT, HTML/XHTML, Markdown, PDF, DjVu and CBZ reader

Usage: malferma-libro [OPTIONS] [--] [FILE ...]

  -h, --help       Show this help without starting the graphical interface
      --manual     Print the full manual for the locale (English fallback)
      --manual=CODE Manual language: ru, en, de or uk
      --license    Print the full GNU GPL v3 license text in the terminal
      --version    Print application name and version
      --           Treat all following arguments as filenames

Examples:
  malferma-libro "Book with spaces.epub" "Другая книга.fb2"
  malferma-libro -- -book.txt
  malferma-libro --manual
  malferma-libro --manual=en

The manual is also available in the application menu, with F1 by default,
and in man malferma-libro.
"""
