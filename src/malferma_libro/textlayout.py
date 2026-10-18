"""Unicode paragraph directions independent of the application's UI language.

Offsets use Unicode character indices, matching GtkTextBuffer and the saved
reading position. Direction tags never insert marks or reorder source text;
Pango remains responsible for shaping and the Unicode bidirectional layout.
"""

from __future__ import annotations

from collections.abc import Iterator
from itertools import chain
import re
import unicodedata


_PARAGRAPH_END = re.compile(r"\r\n|[\n\r\x1c-\x1e\x85\u2029]")


def first_strong_direction(text: str, fallback: str = "ltr") -> str:
    """Return the first strong Unicode direction, ignoring isolated content.

    The P2/P3 base-direction rule ignores text inside explicit bidi isolates.
    Numbers, combining marks and punctuation alone inherit the fallback.
    """
    direction = "rtl" if fallback == "rtl" else "ltr"
    isolate_depth = 0
    for char in text:
        kind = unicodedata.bidirectional(char)
        if kind in {"LRI", "RLI", "FSI"}:
            isolate_depth += 1
        elif kind == "PDI":
            isolate_depth = max(0, isolate_depth - 1)
        elif not isolate_depth:
            if kind == "L":
                return "ltr"
            if kind in {"R", "AL"}:
                return "rtl"
    return direction


def paragraph_runs(text: str) -> Iterator[tuple[int, int, str]]:
    """Yield merged direction ranges covering text without changing offsets."""
    offset = 0
    run_start = 0
    previous = "ltr"
    # U+2028, form feed and vertical tab are line/segment breaks, not bidi
    # paragraph breaks. In particular, isolates can continue across them.
    ends = chain((match.end() for match in _PARAGRAPH_END.finditer(text)), (len(text),))
    for end in ends:
        if end == offset:
            continue
        direction = first_strong_direction(text[offset:end], previous)
        if offset and direction != previous:
            yield run_start, offset, previous
            run_start = offset
        previous = direction
        offset = end
    if offset:
        yield run_start, offset, previous
