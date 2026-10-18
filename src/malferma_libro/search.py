"""Bounded whole-book text search, independent of GTK and document rendering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator


MAX_QUERY_CHARS = 512
DEFAULT_RESULT_LIMIT = 200
SEARCH_CHUNK_CHARS = 32 * 1024


class SearchCancelled(Exception):
    """The caller replaced or cancelled a search before it completed."""


@dataclass(frozen=True)
class BookMatch:
    chapter: int
    start: int
    end: int
    title: str
    snippet: str


@dataclass(frozen=True)
class SearchReport:
    matches: tuple[BookMatch, ...]
    truncated: bool = False
    failed_chapters: tuple[int, ...] = ()
    scanned_chapters: int = 0


def _check_cancelled(cancelled: Callable[[], object] | None):
    # A predicate may return True, or a task token's check() may raise its own
    # cancellation exception. Both contracts keep GTK out of this worker.
    if cancelled is not None and cancelled():
        raise SearchCancelled()


def text_matches(
    text: str, query: str, *, cancelled: Callable[[], object] | None = None,
) -> Iterator[tuple[int, int]]:
    """Yield non-overlapping casefold matches as original Unicode offsets.

    Casefold can expand one character (for example ß to ss or İ to i + dot).
    Map only positions needed for matches, and search bounded chunks rather
    than creating a per-character offset table for the entire chapter. A short
    overlap retains matches across chunk boundaries. Repeated folded matches
    within one expanded original character yield only one selectable range.
    """
    if not isinstance(query, str) or len(query) > MAX_QUERY_CHARS:
        raise ValueError("Search query must contain at most 512 characters")
    folded_query = query.casefold()
    if not folded_query:
        return
    tail, folded_seen, resume, previous_range = "", 0, 0, None
    for chunk_start in range(0, len(text), SEARCH_CHUNK_CHARS):
        _check_cancelled(cancelled)
        part = text[chunk_start:chunk_start + SEARCH_CHUNK_CHARS]
        folded_part = part.casefold()
        folded_tail = tail.casefold()
        window = tail + part
        folded_window = folded_tail + folded_part
        original_base = chunk_start - len(tail)
        folded_base = folded_seen - len(folded_tail)
        search_at = max(0, resume - folded_base)
        original_cursor = folded_cursor = 0

        def original_at(folded_position):
            nonlocal original_cursor, folded_cursor
            while original_cursor < len(window):
                next_folded = folded_cursor + len(window[original_cursor].casefold())
                if next_folded > folded_position:
                    return original_base + original_cursor
                folded_cursor = next_folded
                original_cursor += 1
                if original_cursor % 4096 == 0:
                    _check_cancelled(cancelled)
            return original_base + len(window)

        while (position := folded_window.find(folded_query, search_at)) >= 0:
            _check_cancelled(cancelled)
            end_position = position + len(folded_query)
            match_range = (original_at(position), original_at(end_position - 1) + 1)
            resume = folded_base + end_position
            search_at = end_position
            if match_range != previous_range:
                previous_range = match_range
                yield match_range
        folded_seen += len(folded_part)
        tail = window[-len(folded_query):]
    _check_cancelled(cancelled)


def _snippet(text: str, start: int, end: int) -> str:
    left, right = max(0, start - 50), min(len(text), max(end, start + 1) + 90)
    excerpt = " ".join(text[left:right].split())
    return ("…" if left else "") + excerpt + ("…" if right < len(text) else "")


def search_book(
    book,
    query: str,
    *,
    limit: int = DEFAULT_RESULT_LIMIT,
    document=None,
    cancelled: Callable[[], object] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> SearchReport:
    """Search chapters or lazily extract document pages without rasterizing.

    Pass the managed ``document`` from the window when its backend has been
    relocated after import. Page text stays inside the backend's bounded cache;
    this function never fills the book's otherwise empty page chapters.
    One failed text layer does not hide results from the rest of the book.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10_000:
        raise ValueError("Search result limit must be an integer from 1 to 10000")
    if not isinstance(query, str) or len(query) > MAX_QUERY_CHARS:
        raise ValueError("Search query must contain at most 512 characters")
    query = query.strip()
    if not query:
        return SearchReport(())
    if document is None:
        document = getattr(book, "page_document", None)
    chapters = tuple(book.chapters)
    matches, failures, scanned = [], [], 0
    for index, chapter in enumerate(chapters):
        _check_cancelled(cancelled)
        try:
            text = document.page_text(index) if document is not None else chapter.text
        except (OSError, ValueError):
            failures.append(index)
        else:
            for start, end in text_matches(text, query, cancelled=cancelled):
                if len(matches) >= limit:
                    return SearchReport(tuple(matches), True, tuple(failures), scanned + 1)
                matches.append(BookMatch(index, start, end, chapter.title, _snippet(text, start, end)))
        scanned += 1
        if progress is not None:
            progress(scanned, len(chapters))
    _check_cancelled(cancelled)
    return SearchReport(tuple(matches), False, tuple(failures), scanned)
