"""Compact, structured book navigation independent of chapter list indices."""

from __future__ import annotations

from bisect import bisect_right
from collections import deque
from time import monotonic
from types import SimpleNamespace

from gi.repository import Gio, GLib, Gtk, Pango

from .live_i18n import localized as _


class OutlineMixin:
    """Present real chapter/section titles and keep notes in a separate group."""

    def build_sidebar(self):
        from .app import accessible_label, label

        self._outline_selecting = False
        self._outline_rows = []
        self._outline_generation = 0
        self._outline_source = None
        self._outline_discard = deque()
        self._outline_pending = iter(())
        self._outline_rows_by_order = {}
        self._outline_entries_by_chapter = {}
        self._outline_navigation_positions = []
        self._outline_navigation_indices = {}
        self._outline_requested_position = None
        self.current_outline_entry = None
        self.outline_rows_by_chapter = {}
        self._outline_offsets_by_chapter = {}
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        heading = label(_("Оглавление"), "heading")
        heading.set_margin_start(12)
        heading.set_margin_end(8)
        heading.set_margin_top(10)
        heading.set_margin_bottom(6)
        sidebar.append(heading)
        self.toc = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.toc.add_css_class("navigation-sidebar")
        self.toc.set_activate_on_single_click(True)
        self.toc.set_header_func(self._outline_header)
        self.toc.connect("row-activated", lambda _list, row: self.outline_selected(row))
        accessible_label(self.toc, _("Оглавление"))
        placeholder = label(_("Книга не открыта"), "dim-label", wrap=True)
        placeholder.set_max_width_chars(22)
        for side in ("start", "end", "top", "bottom"):
            getattr(placeholder, f"set_margin_{side}")(12)
        self.toc.set_placeholder(placeholder)
        self.toc_scroll = Gtk.ScrolledWindow(hexpand=False, vexpand=True)
        self.toc_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.toc_scroll.set_child(self.toc)
        sidebar.append(self.toc_scroll)
        return sidebar

    def _outline_header(self, row, before, *_args):
        from .app import label

        if before is not None and before.outline_group == row.outline_group:
            row.set_header(None)
            return
        if row.outline_group == "notes":
            title = _("Примечания")
        elif row.outline_group == "pages":
            title = _("Страницы")
        else:
            title = _("Главы")
        heading = label(title, "caption-heading", wrap=True)
        heading.add_css_class("dim-label")
        heading.set_margin_start(12)
        heading.set_margin_end(8)
        heading.set_margin_top(8 if before is None else 14)
        heading.set_margin_bottom(4)
        row.set_header(heading)

    def _book_outline_entries(self):
        entries = getattr(self.book, "outline", None)
        if entries:
            return list(entries)
        # Old Book constructors and books with no navigation metadata remain
        # usable. Existing chapter titles are preserved without new prefixes.
        return [SimpleNamespace(
            title=_("Страница {number}").format(number=index + 1) if self.is_paged() else chapter.title,
            chapter=index, offset=0,
            level=getattr(chapter, "level", 0),
            kind="page" if self.is_paged() else getattr(chapter, "kind", "chapter"),
        ) for index, chapter in enumerate(self.book.chapters)]

    def rebuild_outline(self):
        self._cancel_outline_population()
        self._outline_discard.extend(self._outline_rows)
        self._outline_rows = []
        self._outline_rows_by_order = {}
        self.current_outline_entry = None
        self.outline_rows_by_chapter = {}
        self._outline_offsets_by_chapter = {}
        self._outline_entries_by_chapter = {}
        self._outline_navigation_positions = []
        self._outline_navigation_indices = {}
        self._outline_requested_position = None
        prepared = []
        if self.book is not None:
            # This lightweight index keeps navigation usable before thousands
            # of GTK rows have finished being populated. Only widgets are lazy.
            for order, entry in enumerate(self._book_outline_entries()):
                chapter = getattr(entry, "chapter", -1)
                if type(chapter) is not int or not 0 <= chapter < len(self.book.chapters):
                    continue
                kind = getattr(entry, "kind", "chapter")
                kind = kind.casefold() if isinstance(kind, str) else "chapter"
                notes = kind in {"note", "notes", "footnote", "endnote"}
                title = getattr(entry, "title", "")
                if not isinstance(title, str) or not title.strip():
                    title = self.book.chapters[chapter].title
                if not isinstance(title, str) or not title.strip():
                    title = (_("Примечания") if notes else
                             _("Страница {number}").format(number=chapter + 1) if self.is_paged() else
                             _("Глава {number}").format(number=chapter + 1))
                offset = getattr(entry, "offset", 0)
                offset = max(0, offset) if type(offset) is int else 0
                offset = min(offset, 100000 if self.is_paged() else len(self.book.chapters[chapter].text))
                level = getattr(entry, "level", 0)
                level = max(0, level) if type(level) is int else 0
                navigation = SimpleNamespace(title=title, chapter=chapter, offset=offset,
                                             level=level, kind=kind)
                item = SimpleNamespace(entry=entry, navigation_entry=navigation, notes=notes,
                                       order=order, chapter=chapter, offset=offset, level=level,
                                       kind=kind, title=title)
                prepared.append(item)
                self._outline_entries_by_chapter.setdefault(chapter, []).append(item)
            prepared.sort(key=lambda item: item.notes)
            for item in prepared:
                position = item.chapter, item.offset
                if position not in self._outline_navigation_indices:
                    self._outline_navigation_indices[position] = len(self._outline_navigation_positions)
                    self._outline_navigation_positions.append(position)
            for chapter, entries in self._outline_entries_by_chapter.items():
                entries.sort(key=lambda item: (item.offset, item.level, item.order))
                self._outline_offsets_by_chapter[chapter] = [item.offset for item in entries]
        self._outline_pending = iter(prepared)
        self._outline_small_result = len(prepared) <= 8
        self._populate_outline_rows(self._outline_generation)

    def _cancel_outline_population(self):
        self._outline_generation += 1
        if self._outline_source is not None:
            GLib.source_remove(self._outline_source)
            self._outline_source = None
        self._outline_pending = iter(())

    def close_outline_ui(self):
        self._cancel_outline_population()
        self._outline_discard.clear()

    def _populate_outline_rows(self, generation):
        if generation != self._outline_generation or self._closing:
            return False
        self._outline_source = None
        started = monotonic()
        self._outline_selecting = True
        finished = False
        try:
            for processed in range(16):
                if processed and not self._outline_small_result and monotonic() - started >= 0.004:
                    break
                if self._outline_discard:
                    self.toc.remove(self._outline_discard.popleft())
                    continue
                try:
                    item = next(self._outline_pending)
                except StopIteration:
                    finished = True
                    break
                row = self._outline_row(item)
                self.toc.append(row)
                self._outline_rows.append(row)
                self._outline_rows_by_order[item.order] = row
                self.outline_rows_by_chapter.setdefault(item.chapter, []).append(row)
        finally:
            self._outline_selecting = False
        if self._outline_requested_position is not None:
            self.select_outline_position(*self._outline_requested_position)
        if not finished:
            self._outline_source = GLib.idle_add(self._populate_outline_rows, generation,
                                               priority=GLib.PRIORITY_DEFAULT_IDLE)
        return False

    def _outline_row(self, item):
        from .app import accessible_label, bind, label

        row = Gtk.ListBoxRow()
        row.outline_generation = self._outline_generation
        row.outline_entry = item.entry
        row.outline_title = item.title
        row.navigation_entry = item.navigation_entry
        row.outline_index = item.order
        row.chapter_index = item.chapter
        row.outline_offset = item.offset
        row.outline_level = item.level
        row.outline_kind = item.kind
        row.outline_group = "notes" if item.notes else "pages" if self.is_paged() else "chapters"
        content = Gtk.Box(spacing=7)
        content.set_margin_start(10 + min(item.level, 3) * 10)
        content.set_margin_end(8)
        content.set_margin_top(6)
        content.set_margin_bottom(6)
        icon_name = (
            "document-edit-symbolic" if item.notes else
            "view-paged-symbolic" if self.is_paged() else
            "document-properties-symbolic" if item.kind == "frontmatter" else
            "view-list-symbolic" if item.kind == "appendix" else
            "text-x-generic-symbolic"
        )
        icon = Gtk.Image.new_from_gicon(Gio.ThemedIcon.new_from_names(
            [icon_name, "text-x-generic-symbolic"]))
        icon.set_pixel_size(16)
        icon.set_valign(Gtk.Align.START)
        icon.set_margin_top(2)
        content.append(icon)
        title_label = label(item.title, wrap=True)
        title_label.set_lines(3)
        title_label.set_max_width_chars(22)
        title_label.set_ellipsize(Pango.EllipsizeMode.END)
        title_label.set_hexpand(True)
        content.append(title_label)
        row.set_child(content)
        bind(row, tooltip_text=item.title)
        accessible_label(row, item.title)
        return row

    def select_outline_position(self, chapter, offset=0):
        self._outline_requested_position = chapter, offset
        entries = self._outline_entries_by_chapter.get(chapter, [])
        row = None
        entry = None
        if entries:
            offsets = self._outline_offsets_by_chapter[chapter]
            entry = entries[max(0, bisect_right(offsets, offset) - 1)]
            row = self._outline_rows_by_order.get(entry.order)
        self.current_outline_entry = entry.navigation_entry if entry is not None else None
        self._outline_selecting = True
        try:
            if row is None:
                self.toc.unselect_all()
            elif self.toc.get_selected_row() is not row:
                self.toc.select_row(row)
        finally:
            self._outline_selecting = False
        return row

    def adjacent_outline_position(self, delta):
        entry = self.current_outline_entry
        if entry is None:
            return None
        current = self._outline_navigation_indices.get((entry.chapter, entry.offset))
        if current is not None and 0 <= current + delta < len(self._outline_navigation_positions):
            return self._outline_navigation_positions[current + delta]
        return None

    def outline_selected(self, row):
        if (row is None or self._outline_selecting or self._chapter_switch
                or self._closing or self.book is None
                or row.outline_generation != self._outline_generation):
            return
        self.display_chapter(row.chapter_index, row.outline_offset)
        if self.reader_split.get_collapsed():
            self.reader_split.set_show_sidebar(False)
