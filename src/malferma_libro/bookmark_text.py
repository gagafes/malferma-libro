"""Readable bookmark excerpts without GTK or document-coordinate guessing."""

import unicodedata


def _word_character(character: str) -> bool:
    return character.isalnum() or unicodedata.category(character).startswith("M") or character in "_'’\u200c\u200d"


def _grapheme_extension(character: str) -> bool:
    return (unicodedata.category(character).startswith("M")
            or character == "\u200d" or "\U0001f3fb" <= character <= "\U0001f3ff")


def compact_snippet(text: str, offset: int = 0, limit: int = 120) -> str:
    """Return a whitespace-normalized excerpt with complete words when possible.

    ``offset`` is a character offset into the *original* text. Long unbroken
    tokens must occasionally be shortened, but combining marks and common
    emoji joiner sequences are not left dangling at the boundary.
    """
    if not isinstance(text, str):
        raise TypeError("The excerpt source must be text")
    if type(offset) is not int or type(limit) is not int or limit < 2:
        raise ValueError("The offset must be an integer and the limit at least two")
    start = max(0, min(len(text), offset))
    while (0 < start < len(text)
           and (_grapheme_extension(text[start]) or text[start - 1] == "\u200d")):
        start -= 1
    if start < len(text) and _word_character(text[start]):
        boundary = start
        while (boundary > 0 and start - boundary <= limit // 2
               and _word_character(text[boundary - 1])):
            boundary -= 1
        # CJK paragraphs and very long identifiers need not rewind to the
        # beginning of an arbitrarily long unbroken run.
        if start - boundary <= limit // 2:
            start = boundary
        else:
            while start > 0 and _grapheme_extension(text[start]):
                start -= 1
    # A bookmark needs nearby context, not a copy of an entire large chapter.
    # Bound whitespace normalization as well as the backwards word scan.
    window_end = min(len(text), start + max(512, limit * 8))
    normalized = " ".join(text[start:window_end].split())
    if not normalized:
        return ""
    if len(normalized) <= limit and window_end == len(text):
        return normalized
    end = min(len(normalized), limit - 1)
    space = normalized.rfind(" ", 0, end + 1)
    if space >= max(1, end // 3):
        end = space
    else:
        while 0 < end < len(normalized) and (_grapheme_extension(normalized[end]) or normalized[end - 1] == "\u200d"):
            end -= 1
    return normalized[:end].rstrip() + "…"


def bookmark_excerpt(text: str, offset: int, *, paged: bool = False, selection: str = "", limit: int = 120) -> str:
    """Paged offsets are viewport fractions, never indices into page text."""
    if paged:
        return compact_snippet(selection if selection.strip() else text, limit=limit)
    return compact_snippet(text, offset=offset, limit=limit)
