"""Stable whole-book reference pages, independent of chapter boundaries.

Reflowable text has no physical pages. Reference pages count Unicode code
points in the immutable progress index, so font size, window size and scrolling
do not renumber the book. The visible range uses an exclusive end offset, as
GTK text iterators do. Fixed-layout documents retain their real page numbers.
"""

from dataclasses import dataclass

from .reading_state import ReadingProgressIndex


REFERENCE_PAGE_CHARS = 1800


@dataclass(frozen=True)
class PageSpan:
    first: int
    last: int
    pages: int


def reference_page_range(
    index: ReadingProgressIndex,
    chapter: int,
    start: int,
    end: int | None = None,
) -> PageSpan:
    """Return one-based whole-book pages covering a chapter-local text range.

    Out-of-range positions are clamped by the index. An absent, reversed or
    empty range selects the page at ``start``; EOF selects the final page even
    when the text length is an exact page multiple. This function reads only
    prefix-index entries, with constant time and memory per scroll callback.
    """
    if index.paged:
        pages = max(1, len(index.cumulative) - 1)
        page = max(1, min(chapter + 1, pages))
        return PageSpan(page, page, pages)

    pages = max(1, (index.total_chars + REFERENCE_PAGE_CHARS - 1) // REFERENCE_PAGE_CHARS)
    first_offset = index.read_characters(chapter, start)
    first = min(pages, first_offset // REFERENCE_PAGE_CHARS + 1)
    if end is None:
        return PageSpan(first, first, pages)
    end_offset = index.read_characters(chapter, end)
    last = min(pages, (end_offset - 1) // REFERENCE_PAGE_CHARS + 1) if end_offset > first_offset else first
    return PageSpan(first, last, pages)
