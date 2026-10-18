"""Whole-book page labels and legacy toolkit-independent screen calculations.

Text books use stable reference pages across the entire text, independently
of chapter boundaries. Fixed-layout documents retain their original pages.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from .book_pagination import PageSpan, reference_page_range


@dataclass(frozen=True)
class PageNumber:
    page: int
    pages: int


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result


def scroll_page_number(lower, upper, page_size, value) -> PageNumber:
    """Return the current screen and total screens in one text chapter.

    The normal screen is floor((value-lower)/page_size)+1. At the bottom it
    becomes ceil((upper-lower)/page_size): otherwise, a partially filled last
    screen could never be selected because the maximum scroll value is
    upper-page_size. The last screen can therefore overlap the preceding one.
    Tiny floating-point errors do not create an extra page or hide the last.
    Empty, short or invalid geometry safely returns page 1 of 1.
    """
    lower, upper, viewport = map(_number, (lower, upper, page_size))
    if (lower is None or upper is None or viewport is None
            or not all(math.isfinite(item) for item in (lower, upper, viewport))
            or viewport <= 0):
        return PageNumber(1, 1)
    content = upper - lower
    if not math.isfinite(content) or content <= viewport:
        return PageNumber(1, 1)
    ratio = content / viewport
    if not math.isfinite(ratio):
        return PageNumber(1, 1)
    nearest = round(ratio)
    pages = max(1, nearest if math.isclose(ratio, nearest, rel_tol=1e-12, abs_tol=1e-9)
                else math.ceil(ratio))
    if pages == 1:
        return PageNumber(1, 1)
    maximum = upper - viewport
    position = _number(value)
    if position is None or math.isnan(position):
        position = lower
    position = max(lower, min(maximum, position))
    if math.isclose(position, maximum, rel_tol=1e-12, abs_tol=1e-6):
        return PageNumber(pages, pages)
    page = math.floor((position - lower) / viewport) + 1
    return PageNumber(max(1, min(pages, page)), pages)


def document_page_number(index, count) -> PageNumber:
    """Return the one-based document page, independently of image zoom/scroll."""
    if type(count) is not int or count < 1:
        count = 1
    if type(index) is not int:
        index = 0
    return PageNumber(max(1, min(count, index + 1)), count)


class PageNumberMixin:
    """Reserve a small page-number line inside the reading surface."""

    def init_page_numbers(self, reader_overlay):
        from gi.repository import Gtk

        self.page_number_label = Gtk.Label(
            halign=Gtk.Align.CENTER,
            can_focus=False, can_target=False, margin_top=2, margin_bottom=4,
            visible=False,
        )
        self.page_number_label.add_css_class("reader-page-number")
        # A badge over the scroll area can cover the final text line. Give the
        # page number its own small natural-height line instead. The overlay
        # remains available for the magnifier, whose source is reader_scroll.
        reader_overlay.set_child(None)
        self.reader_surface = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                      vexpand=True, hexpand=True)
        self.reader_surface.add_css_class("reader-surface")
        self.reader_scroll.set_vexpand(True)
        self.reader_surface.append(self.reader_scroll)
        self.reader_surface.append(self.page_number_label)
        reader_overlay.set_child(self.reader_surface)
        self._page_number_state = None
        self._current_page_span = None
        self._page_number_adjustment = self.reader_scroll.get_vadjustment()
        self._page_number_handlers = tuple(
            self._page_number_adjustment.connect(signal, self.update_page_number)
            for signal in ("changed", "value-changed")
        )
        self.update_page_number()

    def visible_text_offsets(self):
        """Return the visible display-line range as Unicode character offsets.

        A right-to-left line's physical left edge can hit its logical end.
        Normalize both boundaries to display-line starts before advancing the
        bottom iterator. Only visible lines need GTK layout, never other chapters.
        """
        # Reparenting the viewport can emit adjustment changes before
        # show_book has replaced the preceding book's chapter index.
        chapter = max(0, min(self.chapter_index, len(self.book.chapters) - 1))
        length = len(self.book.chapters[chapter].text)
        if self._restoring or not self.text_view.get_mapped():
            offset = max(0, min(length, self._pending_offset))
            return offset, offset
        start = max(0, min(length, self.visible_offset()))
        rectangle = self.text_view.get_visible_rect()
        if rectangle.height <= 0:
            return start, start
        _found, end, _trailing = self.text_view.get_iter_at_position(
            rectangle.x, rectangle.y + rectangle.height - 1,
        )
        if not self.text_view.starts_display_line(end):
            self.text_view.backward_display_line_start(end)
        if self.text_view.forward_display_line(end):
            if not self.text_view.starts_display_line(end):
                self.text_view.backward_display_line_start(end)
            stop = end.get_offset()
        else:
            stop = length
        return start, max(start, min(length, stop))

    def current_page_span(self):
        if self.is_paged():
            result = document_page_number(self.chapter_index, self.page_document.page_count)
            return PageSpan(result.page, result.page, result.pages)
        start, end = self.visible_text_offsets()
        return reference_page_range(self._reading_progress_index, self.chapter_index, start, end)

    @staticmethod
    def page_number_text(span):
        from .live_i18n import localized as _

        if span.first == span.last:
            return _("Страница {page} из {pages}").format(page=span.first, pages=span.pages)
        return _("Страницы {first}–{last} из {pages}").format(
            first=span.first, last=span.last, pages=span.pages,
        )

    def update_page_number(self, *_args):
        if not hasattr(self, "page_number_label"):
            return
        if self.book is None or getattr(self, "_closing", False):
            self.page_number_label.set_visible(False)
            self._page_number_state = None
            self._current_page_span = None
            return
        from .app import accessible_label, bind
        from .live_i18n import localized as _, localized_join

        paged = self.is_paged()
        result = self._current_page_span = self.current_page_span()
        state = id(self.book), paged, result
        if state != self._page_number_state:
            self._page_number_state = state
            text = self.page_number_text(result)
            bind(self.page_number_label, label=text,
                 tooltip_text=None if paged else _("Условные страницы всей книги"))
            accessible_label(self.page_number_label, text if paged else localized_join(
                " · ", (text, _("Условные страницы всей книги"))))
            if hasattr(self, "reading_progress"):
                self.refresh_reading_progress()
        self.page_number_label.set_visible(True)

    def close_page_numbers(self):
        adjustment = getattr(self, "_page_number_adjustment", None)
        if adjustment is not None:
            for handler in getattr(self, "_page_number_handlers", ()):
                adjustment.disconnect(handler)
        self._page_number_handlers = ()
        if hasattr(self, "page_number_label"):
            self.page_number_label.set_visible(False)
