"""Whole-book search popover integrated through a small reader-window mixin."""

from __future__ import annotations

from gi.repository import Gdk, GLib, Gtk, Pango

from .live_i18n import localized as _
from .search import MAX_QUERY_CHARS, SearchReport, search_book
from .tasks import OperationToken


class SearchMixin:
    def build_book_search_controls(self, container):
        # Import widget helpers lazily: app imports this mixin before defining
        # its widgets, while this method runs only after module initialization.
        from .app import bind, button, label

        actions = Gtk.Box(spacing=2)
        self.book_search_previous = button(_("Предыдущее совпадение"), lambda _b: self.find_text(True),
                                           compact=True, icon="go-up-symbolic")
        self.book_search_next = button(_("Следующее совпадение"), lambda _b: self.find_text(),
                                       compact=True, icon="go-down-symbolic")
        self.book_search_return = button(_("Вернуться к месту до поиска"), self.return_to_search_origin,
                                         compact=True, icon="edit-undo-symbolic")
        self.book_search_cancel = button(_("Отменить поиск"), self.cancel_book_search,
                                         compact=True, icon="process-stop-symbolic")
        for control in (self.book_search_previous, self.book_search_next, self.book_search_return,
                        self.book_search_cancel):
            actions.append(control)
        container.append(actions)
        self.book_search_status = label("", "dim-label", True)
        self.book_search_status.set_max_width_chars(44)
        container.append(self.book_search_status)
        self.book_search_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.book_search_list.add_css_class("boxed-list")
        self.book_search_list.connect("row-activated", self.book_search_row_activated)
        self.book_search_scroll = Gtk.ScrolledWindow(max_content_height=300,
                                                     propagate_natural_height=True)
        self.book_search_scroll.set_child(self.book_search_list)
        self.book_search_scroll.set_visible(False)
        container.append(self.book_search_scroll)
        bind(self.reader_search, placeholder_text=_("Поиск по всей книге"))
        for control in (self.book_search_previous, self.book_search_next, self.book_search_return,
                        self.book_search_cancel):
            control.set_sensitive(False)

    def init_book_search(self):
        self._book_search_serial = 0
        self._book_search_token = None
        self._book_search_future = None
        self._book_search_query = ""
        self._book_search_report = SearchReport(())
        self._book_search_origin = None
        self._book_search_current = None
        self._book_search_pending = None
        self._book_search_step_pending = 0
        self._book_search_resetting = False
        delegate = self.reader_search.get_delegate()
        if delegate is not None and hasattr(delegate, "set_max_length"):
            delegate.set_max_length(MAX_QUERY_CHARS)
        self.reader_search.connect("search-changed", self.search_changed)
        self.reader_search.connect("activate", lambda _entry: self.find_text())
        controller = Gtk.EventControllerKey()
        controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        controller.connect("key-pressed", self.book_search_key)
        self.reader_search.add_controller(controller)
        self.book_search_key_controller = controller

    def book_search_key(self, _controller, key, _code, state):
        modifier_mask = (Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK
                         | Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SUPER_MASK
                         | Gdk.ModifierType.HYPER_MASK | Gdk.ModifierType.META_MASK)
        if (key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter)
                and state & modifier_mask == Gdk.ModifierType.SHIFT_MASK):
            self.find_text(True)
            return True
        return False

    def _clear_book_search_highlight(self):
        self.buffer.remove_tag(self.search_tag, self.buffer.get_start_iter(), self.buffer.get_end_iter())

    def _cancel_book_search_work(self):
        self._book_search_serial += 1
        if self._book_search_token is not None:
            self._book_search_token.cancel()
        if self._book_search_future is not None:
            self._book_search_future.cancel()
        self._book_search_token = self._book_search_future = None
        self.book_search_cancel.set_sensitive(False)

    def reset_book_search(self):
        """Call after assigning a newly opened book; never restore another book."""
        from .app import bind

        self._cancel_book_search_work()
        self._book_search_query = ""
        self._book_search_report = SearchReport(())
        self._book_search_origin = self._book_search_current = self._book_search_pending = None
        self._book_search_step_pending = 0
        self._book_search_resetting = True
        try:
            self.reader_search.set_text("")
        finally:
            self._book_search_resetting = False
        self._clear_book_search_highlight()
        self.clear_list(self.book_search_list)
        self.book_search_scroll.set_visible(False)
        bind(self.book_search_status, label="")
        self.book_search_previous.set_sensitive(False)
        self.book_search_next.set_sensitive(False)
        self.book_search_return.set_sensitive(False)

    def cancel_book_search(self, _button=None):
        from .app import bind

        self._cancel_book_search_work()
        self._book_search_step_pending = 0
        bind(self.book_search_status, label=_("Поиск отменён."))

    def search_changed(self, _entry=None):
        if self._book_search_resetting:
            return
        query = self.reader_search.get_text().strip()[:MAX_QUERY_CHARS]
        if query == self._book_search_query:
            return
        self._clear_book_search_highlight()
        self._book_search_current = self._book_search_pending = None
        self._book_search_step_pending = 0
        self.start_book_search(query)

    def _capture_book_search_origin(self):
        if self._book_search_origin is None and self.record is not None:
            self._book_search_origin = (self.record["id"], self.chapter_index, self.current_offset())
            self.book_search_return.set_sensitive(True)

    def start_book_search(self, query=None):
        from .app import bind

        if query is None:
            query = self.reader_search.get_text().strip()[:MAX_QUERY_CHARS]
        self._cancel_book_search_work()
        self._book_search_query = query
        self._book_search_report = SearchReport(())
        self.clear_list(self.book_search_list)
        self.book_search_scroll.set_visible(False)
        self.book_search_previous.set_sensitive(False)
        self.book_search_next.set_sensitive(False)
        if not query or self.book is None or self.record is None:
            bind(self.book_search_status, label="")
            return
        self._capture_book_search_origin()
        serial = self._book_search_serial
        book, document, book_id = self.book, self.page_document, self.record["id"]
        token = self._book_search_token = OperationToken()
        self.book_search_cancel.set_sensitive(True)
        bind(self.book_search_status, label=_("Поиск по книге…"))

        def relevant():
            return (not self._closing and self._book_search_serial == serial
                    and self.book is book and self.record is not None and self.record["id"] == book_id)

        def search():
            return search_book(book, query, document=document,
                               cancelled=token.check, progress=token.progress)

        def ready(report):
            self._book_search_token = self._book_search_future = None
            self.book_search_cancel.set_sensitive(False)
            self._book_search_report = report
            self._show_book_search_results()
            if self._book_search_step_pending:
                direction, self._book_search_step_pending = self._book_search_step_pending, 0
                self._step_book_search(direction)

        def failed(_error):
            self._book_search_token = self._book_search_future = None
            self.book_search_cancel.set_sensitive(False)
            self._book_search_step_pending = 0
            bind(self.book_search_status, label=_("Не удалось выполнить поиск."))

        def cancelled():
            if relevant():
                self._book_search_token = self._book_search_future = None
                self._book_search_step_pending = 0
                self.book_search_cancel.set_sensitive(False)
                bind(self.book_search_status, label=_("Поиск отменён."))

        self._book_search_future = self.run_task(
            search, ready, _("Поиск по книге…"), relevant=relevant, on_error=failed,
            token=token, retry=lambda: self.start_book_search(query), on_cancel=cancelled,
        )

    def _show_book_search_results(self):
        from .app import bind, label, margins

        report = self._book_search_report
        self.clear_list(self.book_search_list)
        for match in report.matches:
            row = Gtk.ListBoxRow(activatable=True)
            row.book_match = match
            row.book_search_book_id = self.record["id"] if self.record else None
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            title = label(match.title, "heading", True)
            title.set_max_width_chars(44)
            title.set_ellipsize(Pango.EllipsizeMode.END)
            title.set_lines(2)
            content.append(title)
            excerpt = label(match.snippet, "dim-label", True)
            excerpt.set_max_width_chars(44)
            excerpt.set_ellipsize(Pango.EllipsizeMode.END)
            excerpt.set_lines(3)
            content.append(excerpt)
            row.set_child(margins(content, 6))
            self.book_search_list.append(row)
        self.book_search_scroll.set_visible(bool(report.matches))
        status = (_("Показаны первые {count} совпадений. Уточните запрос.").format(count=len(report.matches))
                  if report.truncated else _("Совпадений: {count}").format(count=len(report.matches))
                  if report.matches else _("Ничего не найдено."))
        if report.failed_chapters:
            status += "\n" + _("Не удалось прочитать текст на страницах: {count}.").format(count=len(report.failed_chapters))
        bind(self.book_search_status, label=status)
        self.book_search_previous.set_sensitive(bool(report.matches))
        self.book_search_next.set_sensitive(bool(report.matches))

    def book_search_row_activated(self, _list, row):
        match = getattr(row, "book_match", None)
        if (match is not None and self.record is not None
                and getattr(row, "book_search_book_id", None) == self.record["id"]):
            self._show_book_search_match(match)

    @staticmethod
    def _match_identity(match):
        return (match.chapter, match.start, match.end) if match is not None else None

    def _step_book_search(self, direction):
        matches = self._book_search_report.matches
        if not matches:
            return False
        identity = self._match_identity(self._book_search_current)
        current = next((index for index, match in enumerate(matches)
                        if self._match_identity(match) == identity), None)
        if current is not None:
            target = (current + direction) % len(matches)
        else:
            offset = 0 if self.is_paged() else self.current_offset()
            position = (self.chapter_index, offset)
            candidates = [index for index, match in enumerate(matches)
                          if ((match.chapter, match.start) >= position if direction > 0
                              else (match.chapter, match.end) <= position)]
            target = (candidates[0] if direction > 0 else candidates[-1]) if candidates else (0 if direction > 0 else len(matches) - 1)
        self._show_book_search_match(matches[target])
        return True

    def find_text(self, backwards=False):
        query = self.reader_search.get_text().strip()[:MAX_QUERY_CHARS]
        if not query or self.book is None:
            return False
        if query != self._book_search_query or (not self._book_search_report.matches
                                                and self._book_search_token is None):
            self.start_book_search(query)
        direction = -1 if backwards else 1
        if self._step_book_search(direction):
            return True
        # Enter requests navigation once the worker has results. Scanning even
        # the current chapter here can freeze GTK on a large single-file book.
        self._book_search_step_pending = direction
        return False

    def _show_book_search_match(self, match):
        if self.book is None or self.record is None or not 0 <= match.chapter < len(self.book.chapters):
            return
        self._capture_book_search_origin()
        self._book_search_current = match
        self._speech_intent += 1
        self.speech.stop()
        self._speech_offset = None
        if match.chapter != self.chapter_index:
            if self.is_paged():
                self._book_search_pending = (self.record["id"], match)
                self.display_chapter(match.chapter, 0)
                return
            self.display_chapter(match.chapter, match.start)
        if self.is_paged() and not self._document_ready:
            self._book_search_pending = (self.record["id"], match)
            return
        self._apply_book_search_match(match)

    def _apply_book_search_match(self, match):
        from .app import bind

        if self.chapter_index != match.chapter:
            return
        if not self.is_paged():
            self.cancel_restore()
        self._clear_book_search_highlight()
        begin = self.reader_iter_at_offset(match.start, after_images=True)
        end = self.reader_iter_at_offset(match.end)
        self.buffer.apply_tag(self.search_tag, begin, end)
        self.buffer.select_range(begin, end)
        if self.is_paged():
            self.document_text_expander.set_expanded(True)
            self.search_popover.popdown()
            self.reader_tools_popover.popup()
        text_view = self.document_text_view if self.is_paged() else self.text_view
        text_view.scroll_to_mark(self.buffer.get_insert(), 0.15, True, 0, 0.3)
        matches = self._book_search_report.matches
        index = next((index for index, item in enumerate(matches)
                      if self._match_identity(item) == self._match_identity(match)), None)
        if index is not None:
            bind(self.book_search_status, label=_("Результат {number} из {count}").format(number=index + 1, count=len(matches)))
        query = self._book_search_query
        self.set_status(_("Найдено в тексте страницы: {query}").format(query=query) if self.is_paged()
                        else _("Найдено: {query}").format(query=query))

    def after_book_search_page_ready(self):
        pending = self._book_search_pending
        if pending is None:
            return
        book_id, match = pending
        if self.record is None or self.record["id"] != book_id:
            self._book_search_pending = None
            return
        if self.chapter_index == match.chapter and self._document_ready:
            self._book_search_pending = None
            self._apply_book_search_match(match)

    def return_to_search_origin(self, _button=None):
        origin = self._book_search_origin
        if origin is None or self.record is None or self.record["id"] != origin[0]:
            return False
        self._book_search_step_pending = 0
        self._book_search_pending = self._book_search_current = None
        self._clear_book_search_highlight()
        self.display_chapter(origin[1], origin[2])
        self.search_popover.popdown()
        self.book_search_return.set_sensitive(False)
        self._book_search_origin = None
        return True
