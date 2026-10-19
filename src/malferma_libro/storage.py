"""Local book library with managed copies and atomic, recoverable metadata."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import threading
import unicodedata
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from .i18n import _, N_, INTERFACE_LANGUAGE_CODES, LANGUAGE_CHOICES, SPEECH_LANGUAGE_CODES
from .shortcuts import normalize_custom_shortcuts
from .tasks import check_cancel

if TYPE_CHECKING:
    from .books import Book


SCHEMA_VERSION = 1
FONT_SIZE_MIN, FONT_SIZE_MAX = 12, 96
READER_WIDTH_MIN, READER_WIDTH_MAX = 480, 2400
LINE_SPACING_MIN, LINE_SPACING_MAX = 1.0, 2.0
DEFAULT_SETTINGS = {
    "font_size": 20,
    "theme": "system",
    "interface_theme": "system",
    "interface_language": "system",
    "icon_theme": "system",
    "reader_width": 760,
    "font_family": "notoserif",
    "brightness": 1.0,
    "high_contrast": False,
    "bold_text": False,
    "line_spacing": 1.2,
    "mouse_gestures": True,
    "reopen_last_book": False,
    "auto_hide_header": True,
    "speech_rate": 180,
    "speech_language": "auto",
    "speech_voice": "auto",
    "shortcut_mode": "default",
    "custom_shortcuts": {},
}


def _normalize_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Fill optional settings without discarding books from older libraries."""
    settings = DEFAULT_SETTINGS | settings
    if type(settings["font_size"]) is not int or settings["font_size"] <= 0:
        raise LibraryError(_("Некорректный размер шрифта."))
    settings["font_size"] = max(FONT_SIZE_MIN, min(FONT_SIZE_MAX, settings["font_size"]))
    for key, allowed in (
        ("theme", {"system", "light", "sepia", "dark"}),
        ("interface_theme", {"system", "light", "dark"}),
        ("interface_language", INTERFACE_LANGUAGE_CODES),
        # Old elementary preferences migrate to the desktop's native icons.
        ("icon_theme", {"system"}),
        ("font_family", {"system", "notoserif", "notosans", "liberationserif"}),
        ("speech_language", SPEECH_LANGUAGE_CODES),
        ("shortcut_mode", {"default", "custom"}),
    ):
        if not isinstance(settings[key], str) or settings[key] not in allowed:
            settings[key] = DEFAULT_SETTINGS[key]
    width = settings["reader_width"]
    settings["reader_width"] = max(READER_WIDTH_MIN, min(READER_WIDTH_MAX, width)) if type(width) is int else DEFAULT_SETTINGS["reader_width"]
    for key in ("high_contrast", "bold_text", "mouse_gestures", "reopen_last_book", "auto_hide_header"):
        if type(settings[key]) is not bool:
            settings[key] = DEFAULT_SETTINGS[key]
    line_spacing = settings["line_spacing"]
    try:
        valid_line_spacing = type(line_spacing) in (int, float) and math.isfinite(line_spacing)
    except OverflowError:
        valid_line_spacing = False
    settings["line_spacing"] = (
        max(LINE_SPACING_MIN, min(LINE_SPACING_MAX, line_spacing))
        if valid_line_spacing else DEFAULT_SETTINGS["line_spacing"]
    )
    brightness = settings["brightness"]
    # JSON permits nonfinite numbers in Python, but the UI must never receive
    # NaN/Infinity, booleans, or coercions of arbitrary strings.
    try:
        valid_brightness = type(brightness) in (int, float) and math.isfinite(brightness)
    except OverflowError:
        valid_brightness = False
    settings["brightness"] = max(0.3, min(1.0, brightness)) if valid_brightness else DEFAULT_SETTINGS["brightness"]
    rate = settings["speech_rate"]
    settings["speech_rate"] = max(80, min(450, rate)) if type(rate) is int else DEFAULT_SETTINGS["speech_rate"]
    voice = settings["speech_voice"]
    if not isinstance(voice, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", voice):
        settings["speech_voice"] = "auto"
    settings["custom_shortcuts"] = normalize_custom_shortcuts(settings["custom_shortcuts"])
    return settings


class LibraryError(ValueError):
    """A library cannot safely be loaded or updated."""


class _NewerSchema(LibraryError):
    pass


class _PublishedWriteError(OSError):
    """A replacement succeeded, but syncing its directory failed."""

    def __init__(self, error: OSError):
        super().__init__(*error.args)
        self.filename = error.filename
        self.filename2 = error.filename2


class _CommittedSaveError(_PublishedWriteError):
    """The primary already contains the changed in-memory library."""


def _position(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(_("Положение в книге должно быть целым неотрицательным числом."))
    return value


READING_STATUSES = frozenset({"unread", "reading", "finished"})


def _percent(value: Any) -> float:
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(_("Некорректные сведения о книге."))
    return max(0.0, min(100.0, float(value)))


def _timestamp(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def _book_metadata(book: dict[str, Any]) -> dict[str, Any]:
    """Normalize optional additions without invalidating an older library."""
    result = dict(book)
    default_status = "reading" if book["chapter"] or book["offset"] else "unread"
    status = book.get("reading_status")
    result["reading_status"] = status if isinstance(status, str) and status in READING_STATUSES else default_status
    opened = book.get("last_opened_at", "")
    result["last_opened_at"] = opened if _timestamp(opened) is not None else ""
    try:
        result["progress_percent"] = _percent(book.get("progress_percent", 0.0))
    except ValueError:
        result["progress_percent"] = 0.0
    return result


def _catalog_url(value: str) -> str:
    value = value.strip()
    if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(_("Укажите полный адрес OPDS-каталога: https://example.org/opds."))
    try:
        parsed = urlsplit(value)
        # Accessing port also validates malformed ports, even when none is needed.
        parsed.port
        valid = (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not any(char.isspace() for char in parsed.netloc)
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(_("Адрес каталога должен начинаться с http:// или https:// и не содержать пароль."))
    return value


def _validate_document(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LibraryError(_("Некорректный файл библиотеки."))
    version = value.get("schema_version")
    if isinstance(version, int) and not isinstance(version, bool) and version > SCHEMA_VERSION:
        raise _NewerSchema(_("Библиотека создана более новой версией программы. Обновите приложение."))
    if type(version) is not int or version != SCHEMA_VERSION:
        raise LibraryError(_("Неизвестная версия файла библиотеки."))
    if not isinstance(value.get("books"), list):
        raise LibraryError(_("Некорректный список книг."))
    seen = set()
    books = []
    for book in value["books"]:
        if not isinstance(book, dict):
            raise LibraryError(_("Некорректная запись книги."))
        book_id = book.get("id")
        if not isinstance(book_id, str) or not re.fullmatch(r"[0-9a-f]{64}", book_id) or book_id in seen:
            raise LibraryError(_("Некорректный идентификатор книги."))
        seen.add(book_id)
        if not all(isinstance(book.get(key), str) for key in ("title", "author", "format", "path", "added_at")):
            raise LibraryError(_("Некорректные сведения о книге."))
        if not Path(book["path"]).is_absolute():
            raise LibraryError(_("Некорректный путь к книге."))
        _position(book.get("chapter"))
        _position(book.get("offset"))
        if not isinstance(book.get("bookmarks"), list):
            raise LibraryError(_("Некорректный список закладок."))
        bookmarks = []
        for bookmark in book["bookmarks"]:
            if not isinstance(bookmark, dict) or not isinstance(bookmark.get("label"), str):
                raise LibraryError(_("Некорректная закладка."))
            _position(bookmark.get("chapter"))
            _position(bookmark.get("offset"))
            bookmark = dict(bookmark)
            if "note" in bookmark and not isinstance(bookmark["note"], str):
                bookmark["note"] = ""
            if "page" in bookmark and (type(bookmark["page"]) is not int or bookmark["page"] < 1):
                bookmark.pop("page")
            bookmarks.append(bookmark)
        book = _book_metadata(book)
        book["bookmarks"] = bookmarks
        books.append(book)
    settings = value.get("settings")
    if not isinstance(settings, dict):
        raise LibraryError(_("Некорректные настройки библиотеки."))
    settings = _normalize_settings(settings)
    if not isinstance(value.get("catalogs"), list):
        raise LibraryError(_("Некорректный список каталогов."))
    for catalog in value["catalogs"]:
        if not isinstance(catalog, dict) or not all(isinstance(catalog.get(key), str) for key in ("name", "url")):
            raise LibraryError(_("Некорректный каталог."))
        _catalog_url(catalog["url"])
    last_book_id = value.get("last_book_id")
    if not isinstance(last_book_id, str) or last_book_id not in seen:
        last_book_id = None
    return value | {"settings": settings, "books": books, "last_book_id": last_book_id}


def _read_document(
    path: Path, warnings: list[tuple[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except RecursionError as error:
        raise LibraryError(_("Некорректный файл библиотеки.")) from error
    document = _validate_document(raw)
    previous_language = raw["settings"].get("speech_language")
    names = dict(LANGUAGE_CHOICES)
    if (warnings is not None and isinstance(previous_language, str)
            and previous_language in names and previous_language not in SPEECH_LANGUAGE_CODES):
        warnings.append((
            N_("Язык озвучки «{language}» больше не поддерживается. Выбрано автоматическое определение языка."),
            {"language": names[previous_language]},
        ))
    return document


def _managed_suffix(record: dict[str, Any], fallback: str) -> str:
    path = Path(record["path"])
    suffix = ".fb2.zip" if path.name.lower().endswith(".fb2.zip") else path.suffix.lower()
    supported = {
        "EPUB": (".epub",), "FB2": (".fb2", ".fb2.zip"), "TXT": (".txt",),
        "PDF": (".pdf",), "DJVU": (".djvu", ".djv"),
        "HTML": (".html", ".htm", ".xhtml"), "MARKDOWN": (".md", ".markdown"), "CBZ": (".cbz",),
    }.get(record["format"].upper())
    if supported is not None:
        return suffix if suffix in supported else supported[0]
    return suffix or fallback


def _sync_directory(path: Path) -> None:
    """Persist published names before metadata can refer to their files."""
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write(path: Path, data: bytes) -> None:
    temp_path = None
    published = False
    try:
        with tempfile.NamedTemporaryFile(prefix=f".{path.name}-", dir=path.parent, delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        published = True
        temp_path = None
        # Also persist the directory entry after replacement on Linux.
        _sync_directory(path.parent)
    except OSError as error:
        if published:
            raise _PublishedWriteError(error) from error
        raise
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


class Library:
    """A single-process library. Public records are edited by the GUI thread.

    Mutating methods serialize their writes, including imports performed by a
    worker. A second application process must not write the same library.
    """

    def __init__(self, root: Path | None = None):
        if root is None:
            from .paths import user_data_directory

            root = user_data_directory()
        self.root = Path(root).expanduser().resolve()
        self.books_dir = self.root / "books"
        self.downloads_dir = self.root / "downloads"
        self.path = self.root / "library.json"
        self.backup_path = self.root / "library.json.bak"
        self._lock = threading.RLock()
        self._validated_primary: bytes | None = None
        self._warnings: list[tuple[str, dict[str, Any]]] = []
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.books_dir.mkdir(exist_ok=True, mode=0o700)
        self.downloads_dir.mkdir(exist_ok=True, mode=0o700)
        self._data: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "books": [],
            "settings": _normalize_settings({}),
            "catalogs": [],
        }
        if not self.path.exists() and self.backup_path.exists():
            # A missing primary is recoverable too: do not silently start an
            # empty library while a saved book list and positions still exist.
            try:
                self._data = _read_document(self.backup_path, self._warnings)
            except _NewerSchema:
                raise
            except (ValueError, UnicodeError):
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                preserved = self.root / f"library.json.corrupt-{stamp}"
                shutil.copy2(self.backup_path, preserved)
                self._warnings.append((N_("Файл библиотеки повреждён. Исходный файл сохранён: {preserved}"), {"preserved": preserved}))
                self._warnings.append((N_("Создана пустая библиотека. Файлы книг сохранены в папке books; их можно импортировать снова."), {}))
            else:
                self._warnings.append((N_("Список книг и настройки восстановлены из последней резервной копии."), {}))
        elif self.path.exists():
            try:
                self._data = _read_document(self.path, self._warnings)
            except _NewerSchema:
                raise
            except (ValueError, UnicodeError):
                # Leave the original in place until the next successful save;
                # preserve a separate copy even if recovery is unavailable.
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                preserved = self.root / f"library.json.corrupt-{stamp}"
                shutil.copy2(self.path, preserved)
                self._warnings.append((N_("Файл библиотеки повреждён. Исходный файл сохранён: {preserved}"), {"preserved": preserved}))
                try:
                    self._data = _read_document(self.backup_path, self._warnings)
                except _NewerSchema:
                    raise
                except (ValueError, UnicodeError, FileNotFoundError):
                    self._warnings.append((N_("Создана пустая библиотека. Файлы книг сохранены в папке books; их можно импортировать снова."), {}))
                else:
                    self._warnings.append((N_("Список книг и настройки восстановлены из последней резервной копии."), {}))

    @property
    def warnings(self) -> list[str]:
        # The saved interface language is applied after library recovery.
        return [_(message).format(**values) for message, values in self._warnings]

    @property
    def warning(self) -> str | None:
        warnings = self.warnings
        return "\n".join(warnings) if warnings else None

    @property
    def books(self) -> list[dict[str, Any]]:
        return self._data["books"]

    @property
    def settings(self) -> dict[str, Any]:
        return self._data["settings"]

    @property
    def catalogs(self) -> list[dict[str, str]]:
        return self._data["catalogs"]

    def save(self) -> None:
        with self._lock:
            # Persist normalized optional values as well as keeping the live
            # settings dictionary safe for subsequent UI updates.
            document = _validate_document(self._data)
            self.settings.update(document["settings"])
            self._data["last_book_id"] = document["last_book_id"]
            for book, normalized in zip(self.books, document["books"]):
                # Public records and bookmarks are held by open GUI controls.
                # Normalize their optional fields without replacing identities.
                for key in ("reading_status", "last_opened_at", "progress_percent"):
                    book[key] = normalized[key]
                for bookmark, normalized_mark in zip(book["bookmarks"], normalized["bookmarks"]):
                    if "note" in normalized_mark:
                        bookmark["note"] = normalized_mark["note"]
                    if "page" not in normalized_mark:
                        bookmark.pop("page", None)
            serialized = (json.dumps(self._data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            # Never replace a known-good backup with damaged metadata.
            try:
                previous = self.path.read_bytes()
                # Bytes published by this instance have already passed the
                # same validation. Reparse external replacements/corruption,
                # but avoid a second whole-library JSON decode on each save.
                if previous != self._validated_primary:
                    _validate_document(json.loads(previous))
            except _NewerSchema:
                # Another version may have replaced the primary since this
                # instance opened it. Never downgrade that document on save.
                raise
            except (ValueError, UnicodeError, RecursionError, FileNotFoundError):
                pass
            else:
                _atomic_write(self.backup_path, previous)
            try:
                _atomic_write(self.path, serialized)
            except _PublishedWriteError as error:
                self._validated_primary = serialized
                # Keep live records aligned with the primary after publication.
                # A caller must still see the durability error, but rolling its
                # mutation back would make a later save erase committed data.
                raise _CommittedSaveError(error) from error
            self._validated_primary = serialized

    def update_settings(self, changes: dict[str, Any]) -> None:
        """Normalize and save one preference change under the metadata lock.

        GUI callbacks must use this method instead of editing ``settings``
        before ``save``: an import worker could otherwise replace a freshly
        selected value with its older normalization snapshot. Failures before
        publication restore the previous values without replacing the public
        dictionary. A post-publication durability error keeps committed values.
        """
        with self._lock:
            previous = dict(self.settings)
            normalized = _normalize_settings(previous | changes)
            # Widget notifications also fire when a preference is unchanged.
            # Avoid serializing/fsyncing the whole library for those events.
            if normalized == previous:
                return
            self.settings.clear()
            self.settings.update(normalized)
            try:
                self.save()
            except _CommittedSaveError:
                raise
            except Exception:
                self.settings.clear()
                self.settings.update(previous)
                raise

    def find(self, book_id: str) -> dict[str, Any] | None:
        with self._lock:
            return next((book for book in self.books if book["id"] == book_id), None)

    def filtered_books(
        self, query: str = "", status: str = "all", sort: str = "recent",
    ) -> list[dict[str, Any]]:
        """Return records in a deterministic order without mutating the library."""
        if status != "all" and status not in READING_STATUSES:
            raise ValueError(_("Некорректные сведения о книге."))
        if sort not in {"recent", "author", "title"}:
            raise ValueError(_("Некорректные сведения о книге."))

        def text(value: str) -> str:
            return unicodedata.normalize("NFC", value).casefold()

        needle = text(query.strip())
        with self._lock:
            books = [book for book in self.books
                     if (status == "all" or book.get("reading_status", "unread") == status)
                     and (not needle or any(needle in text(book[key]) for key in ("title", "author", "format")))]

            def key(book: dict[str, Any]) -> tuple[Any, ...]:
                title, author = text(book["title"]), text(book["author"])
                if sort == "author":
                    return author, title, book["id"]
                if sort == "title":
                    return title, author, book["id"]
                opened, added = _timestamp(book.get("last_opened_at")), _timestamp(book["added_at"])
                # An actually opened book precedes never-opened imports,
                # including pre-epoch dates or malformed legacy added_at.
                return (opened is None, -(opened if opened is not None else 0.0),
                        added is None, -(added if added is not None else 0.0), title, author, book["id"])

            return sorted(books, key=key)

    def last_opened_book(self) -> dict[str, Any] | None:
        with self._lock:
            last = self.find(self._data.get("last_book_id"))
            if last is not None:
                return last
            return next((book for book in self.filtered_books()
                         if _timestamp(book.get("last_opened_at")) is not None), None)

    def mark_opened(self, book_id: str) -> None:
        """Remember a successful opening; imports alone never replace it."""
        with self._lock:
            book = self._require_book(book_id)
            previous = dict(book)
            had_last = "last_book_id" in self._data
            previous_last = self._data.get("last_book_id")
            book["last_opened_at"] = datetime.now(timezone.utc).isoformat()
            if book.get("reading_status", "unread") == "unread":
                book["reading_status"] = "reading"
            self._data["last_book_id"] = book_id
            try:
                self.save()
            except _CommittedSaveError:
                raise
            except Exception:
                book.clear()
                book.update(previous)
                if had_last:
                    self._data["last_book_id"] = previous_last
                else:
                    self._data.pop("last_book_id", None)
                raise

    def set_reading_status(self, book_id: str, status: str) -> None:
        if not isinstance(status, str) or status not in READING_STATUSES:
            raise ValueError(_("Некорректные сведения о книге."))
        with self._lock:
            book = self._require_book(book_id)
            previous = book.get("reading_status", "unread")
            if previous == status:
                return
            book["reading_status"] = status
            try:
                self.save()
            except _CommittedSaveError:
                raise
            except Exception:
                book["reading_status"] = previous
                raise

    def import_book(self, path: Path, book: Book | None = None) -> dict[str, Any]:
        """Import a snapshot, optionally trusting metadata supplied by a caller."""
        record, content = self._import_book(path, book)
        self._cache_book_cover(record, content)
        return record

    def import_book_with_content(self, path: Path, *, cancel: Any = None) -> tuple[dict[str, Any], Book]:
        """Return a managed record and content parsed from the same snapshot.

        Copying and parsing run without the metadata lock. GUI imports should
        use this method instead of parsing the original, which could change
        between reading its metadata and copying its bytes.
        """
        record, book = self._import_book(path, cancel=cancel)
        if book.format.casefold() != record["format"].casefold():
            # Content hashes intentionally ignore filenames. A duplicate may
            # arrive with another supported suffix (e.g. FB2 XML as TXT), but
            # its chapter indices must match the format saved in the library.
            # Parse the managed copy outside the metadata lock in that case.
            from .books import load_book

            book = (load_book(record["path"], cancel=cancel) if cancel is not None
                    else load_book(record["path"]))
        if book.pdf_document is not None:
            book.pdf_document = book.pdf_document.with_path(record["path"])
        if book.djvu_document is not None:
            book.djvu_document = book.djvu_document.with_path(record["path"])
        if book.cbz_document is not None:
            book.cbz_document = book.cbz_document.with_path(record["path"])
        self._cache_book_cover(record, book)
        return record, book

    def _cache_book_cover(self, record: dict[str, Any], book: Book) -> None:
        """A disposable cover cache must never undo a committed book import."""
        cover = getattr(book, "cover", None)
        if cover is None:
            return
        from .covers import CoverCache

        try:
            CoverCache(self.root / "covers").store(record["id"], cover)
        except OSError:
            # The managed book and its metadata are already durable. A full
            # disk or unwritable image cache simply leaves a placeholder.
            pass

    def _import_book(self, path: Path, book: Book | None = None, *, cancel: Any = None) -> tuple[dict[str, Any], Book]:
        from .books import file_size_limit, file_size_error, load_book

        check_cancel(cancel)
        source = Path(path).expanduser().resolve(strict=True)
        if not source.is_file():
            raise ValueError(_("Выберите файл книги."))
        limit = file_size_limit(source)
        if source.stat().st_size > limit:
            raise ValueError(file_size_error(source))
        suffix = ".fb2.zip" if source.name.lower().endswith(".fb2.zip") else source.suffix.lower()
        staging = None
        temporary = None
        try:
            digest = hashlib.sha256()
            # Preserve the original basename while parsing: TXT files and
            # books without metadata use it as their displayed title.
            staging = Path(tempfile.mkdtemp(dir=self.books_dir, prefix=".import-"))
            temporary = staging / source.name
            copied = 0
            # Validate the opened object, not only the earlier pathname: a
            # download/sync process can replace a selected file before this
            # worker opens it. Nonblocking open avoids hanging on a swapped
            # FIFO; refusing a new final symlink preserves the resolved choice.
            descriptor = os.open(source, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as incoming, temporary.open("xb") as output:
                details = os.fstat(incoming.fileno())
                if not stat.S_ISREG(details.st_mode):
                    raise ValueError(_("Выберите файл книги."))
                if details.st_size > limit:
                    raise ValueError(file_size_error(source))
                while chunk := incoming.read(min(1024 * 1024, limit - copied + 1)):
                    check_cancel(cancel)
                    copied += len(chunk)
                    # Enforce the budget during copying as well: a regular file
                    # can grow after the initial size check, even with metadata
                    # already supplied by a caller.
                    if copied > limit:
                        raise ValueError(file_size_error(source))
                    digest.update(chunk)
                    output.write(chunk)
                check_cancel(cancel)
                output.flush()
                os.fsync(output.fileno())
            book_id = digest.hexdigest()
            if book is None:
                with self._lock:
                    existing = self.find(book_id)
                    parse_suffix = _managed_suffix(existing, suffix) if existing is not None else suffix
                if parse_suffix != suffix:
                    # A known digest keeps its saved interpretation, including
                    # compressed FB2, even if the incoming file was renamed.
                    canonical = staging / (source.stem + parse_suffix)
                    temporary = temporary.rename(canonical)
                book = load_book(temporary, cancel=cancel) if cancel is not None else load_book(temporary)
            check_cancel(cancel)
            with self._lock:
                # This is the last cancellation boundary. A completed commit
                # must be delivered to the caller, even if Cancel arrives next.
                check_cancel(cancel)
                existing = self.find(book_id)
                if existing is not None:
                    # Repair a missing managed copy when the user imports it again.
                    managed = Path(existing["path"])
                    if not managed.is_file():
                        managed = self.books_dir / (book_id + _managed_suffix(existing, suffix))
                        os.replace(temporary, managed)
                        _sync_directory(self.books_dir)
                        temporary = None
                        previous_path = existing["path"]
                        existing["path"] = str(managed)
                        try:
                            self.save()
                        except _CommittedSaveError:
                            raise
                        except Exception:
                            existing["path"] = previous_path
                            raise
                    return existing, book
                managed = self.books_dir / (book_id + suffix)
                os.replace(temporary, managed)
                _sync_directory(self.books_dir)
                temporary = None
                record = {
                    "id": book_id,
                    "title": book.title.strip() or source.stem,
                    "author": book.author,
                    "format": book.format,
                    "path": str(managed),
                    "added_at": datetime.now(timezone.utc).isoformat(),
                    "chapter": 0,
                    "offset": 0,
                    "bookmarks": [],
                    "reading_status": "unread",
                    "last_opened_at": "",
                    "progress_percent": 0.0,
                }
                self.books.append(record)
                try:
                    self.save()
                except _CommittedSaveError:
                    raise
                except Exception:
                    self.books.remove(record)
                    # Keep the managed book: metadata failure must never delete
                    # the only available copy, including a recovered orphan.
                    raise
                return record, book
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            if staging is not None:
                staging.rmdir()

    def _require_book(self, book_id: str) -> dict[str, Any]:
        book = self.find(book_id)
        if book is None:
            raise KeyError(_("Книга не найдена: {book_id}").format(book_id=book_id))
        return book

    def update_progress(self, book_id: str, chapter: int, offset: int) -> None:
        with self._lock:
            chapter, offset = _position(chapter), _position(offset)
            book = self._require_book(book_id)
            if (book["chapter"], book["offset"]) != (chapter, offset):
                previous = book["chapter"], book["offset"]
                book.update(chapter=chapter, offset=offset)
                try:
                    self.save()
                except _CommittedSaveError:
                    raise
                except Exception:
                    book.update(chapter=previous[0], offset=previous[1])
                    raise

    def update_reading_progress(self, book_id: str, chapter: int, offset: int, percent: float) -> None:
        """Persist a position and its display progress in one transaction.

        Reaching the final position does not silently mark a book as finished:
        the user's explicit reading status is independent of current position.
        """
        chapter, offset, percent = _position(chapter), _position(offset), _percent(percent)
        with self._lock:
            book = self._require_book(book_id)
            previous = book["chapter"], book["offset"], book.get("progress_percent", 0.0)
            if previous == (chapter, offset, percent):
                return
            book.update(chapter=chapter, offset=offset, progress_percent=percent)
            try:
                self.save()
            except _CommittedSaveError:
                raise
            except Exception:
                book.update(chapter=previous[0], offset=previous[1], progress_percent=previous[2])
                raise

    def add_bookmark(
        self, book_id: str, chapter: int, offset: int, label: str, *, note: str = "", page: int | None = None,
    ) -> None:
        if not isinstance(note, str) or (page is not None and (type(page) is not int or page < 1)):
            raise ValueError(_("Некорректная закладка."))
        bookmark = {"chapter": _position(chapter), "offset": _position(offset), "label": str(label).strip()}
        if note.strip():
            bookmark["note"] = note.strip()
        if page is not None:
            bookmark["page"] = page
        with self._lock:
            book = self._require_book(book_id)
            bookmarks = book["bookmarks"]
            existing = next((mark for mark in bookmarks
                             if (mark["chapter"], mark["offset"]) == (chapter, offset)), None)
            if existing is not None:
                previous = dict(existing)
                existing.update(bookmark)
                if existing == previous:
                    return
                try:
                    self.save()
                except _CommittedSaveError:
                    raise
                except Exception:
                    existing.clear()
                    existing.update(previous)
                    raise
                return
            bookmarks.append(bookmark)
            try:
                self.save()
            except _CommittedSaveError:
                raise
            except Exception:
                bookmarks.pop()
                raise

    def edit_bookmark(self, book_id: str, index: int, note: str) -> None:
        if not isinstance(note, str):
            raise ValueError(_("Некорректная закладка."))
        with self._lock:
            _position(index)
            bookmark = self._require_book(book_id)["bookmarks"][index]
            previous = dict(bookmark)
            if note.strip():
                bookmark["note"] = note.strip()
            else:
                bookmark.pop("note", None)
            if bookmark == previous:
                return
            try:
                self.save()
            except _CommittedSaveError:
                raise
            except Exception:
                bookmark.clear()
                bookmark.update(previous)
                raise

    def remove_bookmark(self, book_id: str, index: int) -> None:
        with self._lock:
            _position(index)
            bookmarks = self._require_book(book_id)["bookmarks"]
            bookmark = bookmarks.pop(index)
            try:
                self.save()
            except _CommittedSaveError:
                raise
            except Exception:
                bookmarks.insert(index, bookmark)
                raise

    def add_catalog(self, name: str, url: str) -> None:
        name, url = name.strip(), _catalog_url(url)
        if not name:
            raise ValueError(_("Укажите название каталога."))
        with self._lock:
            if any(catalog["url"] == url for catalog in self.catalogs):
                raise ValueError(_("Этот каталог уже добавлен."))
            self.catalogs.append({"name": name, "url": url})
            try:
                self.save()
            except _CommittedSaveError:
                raise
            except Exception:
                self.catalogs.pop()
                raise

    def remove_catalog(self, index: int) -> None:
        with self._lock:
            _position(index)
            catalog = self.catalogs.pop(index)
            try:
                self.save()
            except _CommittedSaveError:
                raise
            except Exception:
                self.catalogs.insert(index, catalog)
                raise
