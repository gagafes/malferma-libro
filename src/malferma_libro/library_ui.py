"""Compact library controls and an explicit route back to the last book."""

from time import monotonic

from gi.repository import Adw, GLib, Gtk, Pango

from .i18n import N_
from .live_i18n import localized as _, localized_join
from .tasks import OperationToken
from .books import load_book


STATUS_LABELS = (("unread", N_("Не начато")), ("reading", N_("Читаю")),
                 ("finished", N_("Прочитано")))


class LibraryMixin:
    def build_library(self):
        from .app import APP_ID, APP_NAME, margins, label, translated, translated_dropdown, accessible_label

        self._book_operation = None
        self._startup_handled = False
        self._library_refreshing = False
        self._library_render_serial = 0
        self._library_render_source = None
        self._library_render = None
        page = margins(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), 8)
        heading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        heading.append(label(_("Ваша библиотека"), "heading"))
        self.library_count = label("", "dim-label")
        heading.append(self.library_count)
        self.header_titles.add_named(heading, "library")
        self.library_search = translated(Gtk.SearchEntry, placeholder_text=_("Название или автор"))
        self.library_search.connect("search-changed", lambda _entry: self.refresh_library())
        self.search_stack.add_named(self.library_search, "library")

        controls = margins(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), 12)
        self.library_filter = translated_dropdown([_("Все книги"), *(_(text) for _code, text in STATUS_LABELS)])
        self.library_sort = translated_dropdown([_("Недавние"), _("По автору"), _("По названию")])
        accessible_label(self.library_filter, _("Фильтр библиотеки"))
        accessible_label(self.library_sort, _("Сортировка библиотеки"))
        for title, widget in ((_("Фильтр библиотеки"), self.library_filter),
                              (_("Сортировка библиотеки"), self.library_sort)):
            controls.append(label(title))
            controls.append(widget)
            widget.connect("notify::selected", lambda *_args: self.refresh_library())
        self.library_controls = translated(Gtk.MenuButton, icon_name="view-filter-symbolic",
                                           tooltip_text=_("Фильтр библиотеки"))
        self.library_controls.set_popover(Gtk.Popover(child=controls))
        accessible_label(self.library_controls, _("Фильтр библиотеки"))

        self.continue_button = Gtk.Button()
        self.continue_button.set_vexpand(False)
        self.continue_button.add_css_class("card")
        self.continue_button.connect("clicked", lambda _button: self.continue_reading())
        continue_row = margins(Gtk.Box(spacing=12), 12)
        self.continue_cover = self.cover_thumbnail()
        continue_row.append(self.continue_cover)
        continue_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                               hexpand=True, valign=Gtk.Align.CENTER)
        continue_box.append(label(_("Продолжить чтение"), "heading"))
        self.continue_title = label("", wrap=True)
        self.continue_title.set_lines(2)
        self.continue_title.set_ellipsize(Pango.EllipsizeMode.END)
        self.continue_progress = label("", "dim-label")
        continue_box.append(self.continue_title)
        continue_box.append(self.continue_progress)
        continue_row.append(continue_box)
        self.continue_button.set_child(continue_row)
        self.continue_button.set_visible(False)
        page.append(self.continue_button)

        self.library_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.library_list.add_css_class("boxed-list")
        self.library_list.connect("row-activated", self.activate_book)
        empty = translated(Adw.StatusPage, icon_name=APP_ID, title=APP_NAME,
            description=_("Откройте книгу или подключите OPDS-каталог во вкладке «Сетевые библиотеки».") + "\n\n"
                        + _("EPUB · FB2 · FB2.ZIP · TXT · PDF · DjVu · HTML · Markdown · CBZ. Книги копируются в локальную библиотеку."))
        self.library_scroll = Gtk.ScrolledWindow(vexpand=True, child=self.library_list)
        self.library_content = Gtk.Stack(vexpand=True)
        self.library_content.add_named(self.library_scroll, "books")
        self.library_content.add_named(empty, "empty")
        page.append(self.library_content)
        return page

    def refresh_library(self):
        from .app import bind, accessible_label

        if self._library_refreshing or self._syncing_preferences or getattr(self, "_closing", False):
            return
        self._library_refreshing = True
        try:
            self._cancel_library_render()
            query = self.library_search.get_text().strip()
            statuses = ("all", "unread", "reading", "finished")
            sorts = ("recent", "author", "title")
            books = self.library.filtered_books(
                query, status=statuses[min(3, self.library_filter.get_selected())],
                sort=sorts[min(2, self.library_sort.get_selected())],
            )
            self._library_render = iter(books)
            self._library_clearing = True
            self._library_small_result = len(books) <= 8
            count = len(self.library.books)
            bind(self.library_count, label=_("Книг: {count}").format(count=count)
                 + (_(" · Найдено: {count}").format(count=len(books)) if query or self.library_filter.get_selected() else ""))
            self._library_no_matches = not books and bool(count)
            self.library_content.set_visible_child_name("empty" if not count else "books")
            recent = self.library.last_opened_book()
            self._continue_book_id = recent["id"] if recent else None
            self.continue_button.set_visible(recent is not None)
            if recent:
                self.set_cover_record(self.continue_cover, recent)
                title = recent["title"] + (f" — {recent['author']}" if recent["author"] else "")
                bind(self.continue_title, label=title)
                bind(self.continue_progress, label=_("{percent}% прочитано").format(
                    percent=int(recent.get("progress_percent", 0))))
                accessible_label(self.continue_button, localized_join(" · ", (_("Продолжить чтение"), title)))
            self._populate_library_rows(self._library_render_serial)
        finally:
            self._library_refreshing = False

    def _cancel_library_render(self):
        self._library_render_serial += 1
        if self._library_render_source is not None:
            GLib.source_remove(self._library_render_source)
            self._library_render_source = None
        self._library_render = None

    def close_library_ui(self):
        self._cancel_library_render()

    def _populate_library_rows(self, serial):
        """Yield between bounded widget batches, including removing old rows.

        GTK widgets must be built on the main thread. A large ListBox refresh
        therefore has a small time and row budget instead of monopolizing one
        event callback. Superseded searches cancel their remaining work.
        """
        if serial != self._library_render_serial or getattr(self, "_closing", False):
            return False
        self._library_render_source = None
        started = monotonic()
        processed = 0
        while processed < 16:
            if processed and not self._library_small_result and monotonic() - started >= 0.004:
                break
            if self._library_clearing:
                child = self.library_list.get_first_child()
                if child is not None:
                    self.library_list.remove(child)
                    processed += 1
                    continue
                self._library_clearing = False
            try:
                item = next(self._library_render)
            except StopIteration:
                self._library_render = None
                if self._library_no_matches:
                    from .app import margins, label
                    self.library_list.append(margins(label(_("Ничего не найдено."), wrap=True), 24))
                self.schedule_cover_scan()
                return False
            self.library_list.append(self._library_book_row(item))
            processed += 1
        self.schedule_cover_scan()
        self._library_render_source = GLib.idle_add(
            self._populate_library_rows, serial, priority=GLib.PRIORITY_DEFAULT_IDLE)
        return False

    def _library_book_row(self, item):
        from .app import margins, label, button, accessible_label, translated

        row = Gtk.ListBoxRow(activatable=True)
        row.book_id = item["id"]
        horizontal = margins(Gtk.Box(spacing=8), 10)
        row.cover_thumbnail = self.cover_thumbnail(item)
        horizontal.append(row.cover_thumbnail)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        title = label(item["title"], "heading", True)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.set_lines(2)
        text.append(title)
        text.append(label(item["author"] or _("Автор не указан"), "dim-label", True))
        state = dict(STATUS_LABELS)[item.get("reading_status", "unread")]
        detail = localized_join(" · ", (item["format"].upper(), _(state),
            _("{percent}% прочитано").format(percent=int(item.get("progress_percent", 0)))))
        text.append(label(detail, "caption", True))
        horizontal.append(text)
        status_button = translated(Gtk.MenuButton, icon_name="view-more-symbolic",
                                   tooltip_text=_("Изменить статус чтения"), valign=Gtk.Align.CENTER)
        accessible_label(status_button, _("Изменить статус чтения"))
        choices = margins(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4), 6)
        for status, source in STATUS_LABELS:
            def set_status(_button, book_id=item["id"], value=status):
                self.set_book_status(book_id, value)
            choices.append(button(_(source), set_status))
        status_button.set_popover(Gtk.Popover(child=choices))
        horizontal.append(status_button)
        row.set_child(horizontal)
        return row

    def set_book_status(self, book_id, status):
        try:
            self.library.set_reading_status(book_id, status)
        except (OSError, ValueError, KeyError) as error:
            self.show_error(_("Не удалось сохранить библиотеку"), error)
        self.refresh_library()

    def continue_reading(self, *_args):
        item = self.library.last_opened_book()
        if item is not None:
            self.open_library_book(item["id"])

    def maybe_reopen_last_book(self):
        if self._startup_handled:
            return
        self._startup_handled = True
        if self.library.settings["reopen_last_book"] and self.record is None:
            self.continue_reading()

    def activate_book(self, _list, row):
        book_id = getattr(row, "book_id", None)
        if book_id:
            self.open_library_book(book_id)

    def begin_book_operation(self):
        if self._book_operation is not None:
            self._book_operation.cancel()
        self._startup_handled = True
        self._book_serial += 1
        self._book_operation = OperationToken()
        return self._book_operation, self._book_serial, self._navigation_serial

    def open_library_book(self, book_id):
        item = self.library.find(book_id)
        if item is None:
            return
        token, serial, navigation = self.begin_book_operation()

        def load():
            token.check()
            book = load_book(item["path"], cancel=token)
            token.check()
            return book

        self.run_task(load, lambda book: self.complete_book(item, book, navigation),
                      _("Открытие книги…"), relevant=lambda: serial == self._book_serial,
                      token=token, retry=lambda: self.open_library_book(book_id))

    def confirm_duplicate(self, record, book, navigation):
        from .app import translated, translated_dialog_button

        dialog = translated(Gtk.MessageDialog, transient_for=self, modal=True, destroy_with_parent=True,
                            message_type=Gtk.MessageType.QUESTION,
                            text=_("Книга уже в библиотеке"),
                            secondary_text=_("Книга «{title}» уже добавлена. Сохранённые закладки и место чтения будут использованы.").format(title=record["title"]))
        translated_dialog_button(dialog, _("Отмена"), Gtk.ResponseType.CANCEL)
        translated_dialog_button(dialog, _("Открыть"), Gtk.ResponseType.ACCEPT)
        dialog.set_default_response(Gtk.ResponseType.ACCEPT)
        serial = self._book_serial

        def respond(widget, response):
            widget.destroy()
            if response == Gtk.ResponseType.ACCEPT and not self._closing and serial == self._book_serial:
                self.complete_book(record, book, navigation)

        dialog.connect("response", respond)
        dialog.present()
