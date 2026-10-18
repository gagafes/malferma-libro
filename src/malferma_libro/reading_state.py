"""Format-independent progress without changing persisted position units."""

from dataclasses import dataclass
from itertools import accumulate


@dataclass(frozen=True)
class ReadingProgressIndex:
    """One immutable prefix index for an opened book, with O(1) scroll reads.

    Text chapters are immutable while open. Lazy PDF/DjVu text extraction does
    not affect fixed-page progress, which uses normalized page offsets.
    """

    cumulative: tuple[int, ...] = (0,)
    paged: bool = False

    @classmethod
    def from_book(cls, book):
        if not book or not book.chapters:
            return cls()
        paged = book.page_document is not None
        sizes = (1 if paged else len(item.text) for item in book.chapters)
        return cls(tuple(accumulate(sizes, initial=0)), paged)

    @property
    def total_chars(self):
        return self.cumulative[-1]

    def read_characters(self, chapter, offset):
        count = len(self.cumulative) - 1
        if count == 0:
            return 0
        chapter = max(0, min(chapter, count - 1))
        length = self.cumulative[chapter + 1] - self.cumulative[chapter]
        return self.cumulative[chapter] + max(0, min(offset, length))

    def percent(self, chapter, offset):
        count = len(self.cumulative) - 1
        if count == 0:
            return 0.0
        if self.paged:
            chapter = max(0, min(chapter, count - 1))
            return 100 * (chapter + max(0, min(offset, 100000)) / 100000) / count
        return 100 * self.read_characters(chapter, offset) / max(1, self.total_chars)


def book_percent(book, chapter, offset):
    return ReadingProgressIndex.from_book(book).percent(chapter, offset)
