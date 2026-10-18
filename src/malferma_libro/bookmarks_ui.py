"""Bookmark presentation and optional notes for the native reader window."""

from dataclasses import dataclass

from gi.repository import Gtk

from .bookmark_text import bookmark_excerpt, compact_snippet
from .live_i18n import localized as _


NOTE_LIMIT = 2000


@dataclass
class _NoteEditor:
    book_id: str
    bookmark: dict
    view: Gtk.TextView


class BookmarkMixin:
    """Keep all callbacks bound to a specific book and bookmark object."""

    def _bookmark_target(self, book_id, bookmark):
        if (self._closing or self.book is None or self.record is None
                or self.record.get("id") != book_id or self.library.find(book_id) is not self.record):
            return None
        return next((index for index, mark in enumerate(self.record.get("bookmarks", []))
                     if mark is bookmark), None)

    def _bookmark_caption(self, bookmark):
        chapter = bookmark["chapter"]
        if self.is_paged():
            return _("Страница {page}").format(page=bookmark.get("page", chapter + 1))
        if 0 <= chapter < len(self.book.chapters):
            return self.book.chapters[chapter].title
        return _("Закладка")

    def add_bookmark(self, _button=None):
        if not self.record or not self.book:
            self.set_status(_("Сначала откройте книгу."))
            return
        offset = self.current_offset()
        chapter = self.book.chapters[self.chapter_index]
        selection = ""
        if self.is_paged():
            bounds = self.buffer.get_selection_bounds()
            if bounds:
                selection = self.buffer.get_text(*bounds, False)
        excerpt = bookmark_excerpt(chapter.text, offset, paged=self.is_paged(), selection=selection)
        page = self.chapter_index + 1 if self.is_paged() else None
        fallback = _("Страница {page}").format(page=page) if page is not None else chapter.title
        try:
            self.library.add_bookmark(self.record["id"], self.chapter_index, offset,
                                      excerpt or str(fallback), page=page)
        except (OSError, ValueError) as error:
            self.show_error(_("Не удалось сохранить закладку"), error)
            return
        self.refresh_bookmarks()
        self.set_status(_("Закладка добавлена."))

    def _bookmark_unavailable(self):
        if not self._closing:
            self.set_status(_("Закладка больше недоступна."))

    def jump_to_bookmark(self, book_id, bookmark, popover=None):
        if self._bookmark_target(book_id, bookmark) is None:
            self._bookmark_unavailable()
            return
        if not 0 <= bookmark["chapter"] < len(self.book.chapters):
            self._bookmark_unavailable()
            return
        if popover is not None:
            popover.popdown()
        self.display_chapter(bookmark["chapter"], bookmark["offset"])

    def remove_bookmark(self, book_id, bookmark):
        index = self._bookmark_target(book_id, bookmark)
        if index is None:
            self._bookmark_unavailable()
            return
        try:
            self.library.remove_bookmark(book_id, index)
        except (OSError, ValueError) as error:
            self.show_error(_("Не удалось удалить закладку"), error)
            return
        for dialog, editor in tuple(getattr(self, "bookmark_note_dialogs", {}).items()):
            if editor.book_id == book_id and editor.bookmark is bookmark:
                self._close_bookmark_note_dialog(dialog)
        self.refresh_bookmarks()

    def refresh_bookmarks(self):
        # Imports are lazy because app.ReaderWindow inherits this mixin.
        from .app import accessible_label, button, label, margins

        popover = Gtk.Popover()
        box = margins(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8))
        box.append(button(_("＋ Закладка"), self.add_bookmark))
        marks = self.record.get("bookmarks", []) if self.record else []
        if self.record:
            heading = label(self.record["title"], "heading", True)
            heading.set_max_width_chars(38)
            box.append(heading)
        if not marks:
            box.append(label(_("Закладок пока нет."), wrap=True))
        book_id = self.record["id"] if self.record else None
        for mark in marks:
            row = Gtk.Box(spacing=4)
            jump = Gtk.Button(hexpand=True)
            jump.add_css_class("flat")
            contents = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            caption = self._bookmark_caption(mark)
            chapter_label = label(caption, "heading", True)
            chapter_label.set_max_width_chars(36)
            contents.append(chapter_label)
            excerpt = label(mark["label"], wrap=True)
            excerpt.set_max_width_chars(36)
            contents.append(excerpt)
            if mark.get("note"):
                note = label(compact_snippet(mark["note"], limit=180), "dim-label", True)
                note.set_max_width_chars(36)
                contents.append(note)
            jump.set_child(contents)
            accessible_text = _("Открыть закладку: {chapter}. {excerpt}").format(
                chapter=caption, excerpt=mark["label"])
            if mark.get("note"):
                accessible_text += "\n" + compact_snippet(mark["note"], limit=180)
            accessible_label(jump, accessible_text)
            jump.connect("clicked", lambda _button, item=mark, identifier=book_id:
                         self.jump_to_bookmark(identifier, item, popover))
            row.append(jump)
            edit = button(_("Заметка к закладке"),
                          lambda _button, item=mark, identifier=book_id: self.edit_bookmark_note(identifier, item),
                          compact=True, icon="document-edit-symbolic")
            remove = button(_("Удалить закладку"),
                            lambda _button, item=mark, identifier=book_id: self.remove_bookmark(identifier, item),
                            compact=True, icon="user-trash-symbolic")
            for action in (edit, remove):
                action.set_valign(Gtk.Align.START)
                row.append(action)
            box.append(row)
        scroll = Gtk.ScrolledWindow(max_content_height=420, propagate_natural_height=True,
                                    propagate_natural_width=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_child(box)

        def fit_width(*_args):
            width = self.get_width()
            maximum = min(480, max(160, width - 48)) if width else 400
            scroll.set_min_content_width(0)
            scroll.set_max_content_width(maximum)
            scroll.set_min_content_width(min(300, maximum))

        fit_width()
        popover.connect("map", fit_width)
        popover.set_child(scroll)
        self.bookmarks_button.set_popover(popover)

    def edit_bookmark_note(self, book_id, bookmark):
        from .app import accessible_label, bind, label, margins, translated

        if self._bookmark_target(book_id, bookmark) is None:
            self._bookmark_unavailable()
            return None
        if not hasattr(self, "bookmark_note_dialogs"):
            self.bookmark_note_dialogs = {}
        for dialog, editor in self.bookmark_note_dialogs.items():
            if editor.book_id == book_id and editor.bookmark is bookmark:
                dialog.present()
                return dialog
        self.bookmarks_button.get_popover().popdown()
        dialog = translated(Gtk.Dialog, transient_for=self, modal=True, destroy_with_parent=True,
                            title=_("Заметка к закладке"), default_width=480, default_height=340,
                            use_header_bar=True)
        bind(dialog.add_button(_("Отмена"), Gtk.ResponseType.CANCEL), label=_("Отмена"))
        save = bind(dialog.add_button(_("Сохранить"), Gtk.ResponseType.ACCEPT), label=_("Сохранить"))
        save.add_css_class("suggested-action")
        dialog.set_default_response(Gtk.ResponseType.ACCEPT)
        content = margins(dialog.get_content_area())
        content.set_spacing(10)
        caption = label(self._bookmark_caption(bookmark), "heading", True)
        content.append(caption)
        view = Gtk.TextView(editable=True, cursor_visible=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                            accepts_tab=False, left_margin=8, right_margin=8,
                            top_margin=8, bottom_margin=8, vexpand=True)
        view.add_css_class("reader-text")
        accessible_label(view, _("Заметка к закладке"))
        view.get_buffer().set_text(bookmark.get("note", ""))
        content.append(Gtk.ScrolledWindow(child=view, min_content_height=160, vexpand=True))
        counter = label("", "dim-label")
        content.append(counter)

        def changed(buffer):
            count = buffer.get_char_count()
            bind(counter, label=_("{count} из {limit} символов").format(count=count, limit=NOTE_LIMIT))
            save.set_sensitive(count <= NOTE_LIMIT)

        view.get_buffer().connect("changed", changed)
        changed(view.get_buffer())
        self.bookmark_note_dialogs[dialog] = _NoteEditor(book_id, bookmark, view)
        dialog.connect("response", self._bookmark_note_response)
        dialog.connect("close-request", self._bookmark_note_close_requested)
        dialog.present()
        view.grab_focus()
        return dialog

    def _bookmark_note_response(self, dialog, response):
        editor = getattr(self, "bookmark_note_dialogs", {}).get(dialog)
        if editor is None:
            return
        if response != Gtk.ResponseType.ACCEPT:
            self._close_bookmark_note_dialog(dialog)
            return
        index = self._bookmark_target(editor.book_id, editor.bookmark)
        if index is None:
            self._close_bookmark_note_dialog(dialog)
            self._bookmark_unavailable()
            return
        buffer = editor.view.get_buffer()
        note = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
        if len(note) > NOTE_LIMIT:
            self.set_status(_("Заметка слишком длинная: максимум {limit} символов.").format(limit=NOTE_LIMIT))
            return
        try:
            self.library.edit_bookmark(editor.book_id, index, note)
        except (OSError, ValueError) as error:
            self.show_error(_("Не удалось сохранить заметку"), error)
            return
        self._close_bookmark_note_dialog(dialog)
        self.refresh_bookmarks()

    def _bookmark_note_close_requested(self, dialog):
        self._close_bookmark_note_dialog(dialog)
        return True

    def _close_bookmark_note_dialog(self, dialog):
        getattr(self, "bookmark_note_dialogs", {}).pop(dialog, None)
        dialog.destroy()

    def close_bookmark_dialogs(self):
        for dialog in tuple(getattr(self, "bookmark_note_dialogs", {})):
            self._close_bookmark_note_dialog(dialog)
