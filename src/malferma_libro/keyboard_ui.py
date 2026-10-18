"""Reading viewport navigation, independent of the text insertion cursor.

GTK is imported only by the focus guard, keeping the scheduling/geometry
behavior testable without a display. Controls and selection keep native keys.
"""

from .keyboard_navigation import navigation_for, scroll_target


def _gtk():
    from gi.repository import Gtk
    return Gtk


class KeyboardNavigationMixin:
    def reading_navigation_has_focus(self):
        if (self._closing or self.book is None
                or self.stack.get_visible_child_name() != "reader"):
            return False
        if (getattr(self, "_accessibility_popup_tick", None) is not None
                or getattr(self, "_native_chooser", None) is not None
                or getattr(getattr(self, "_portal_chooser", None), "active", False)
                or self._immersive_visible_dialog()):
            return False
        # A popover can retain the old focus while opening. Check known popup
        # roots without traversing thousands of library/outline row widgets.
        for name in ("reading_context_popover", "search_popover", "reader_tools_popover", "operation_popover",
                     "catalog_popover"):
            popup = getattr(self, name, None)
            if popup is not None and popup.get_visible():
                return False
        for name in ("bookmarks_button", "main_menu_button", "accessibility_button"):
            button = getattr(self, name, None)
            popup = button.get_popover() if button is not None else None
            if popup is not None and popup.get_visible():
                return False
        focus = self.get_focus()
        if focus is None:
            return True
        if focus.get_root() is not self:
            return False
        # The context menu is parented to reader_scroll: ancestry alone would
        # otherwise mistake its buttons for part of the reading viewport.
        Gtk = _gtk()
        ancestor = focus
        while ancestor is not None:
            if isinstance(ancestor, Gtk.Popover):
                return False
            ancestor = ancestor.get_parent()
        return focus is self.reader_scroll or focus.is_ancestor(self.reader_scroll)

    def focus_reading_surface(self):
        if self._closing or self.book is None:
            return
        (self.document_canvas if self.is_paged() else self.text_view).grab_focus()

    def reading_pointer_pressed(self, *_args):
        self.manual_scroll()
        if self.is_paged():
            self.focus_reading_surface()

    def _navigation_end_offset(self, index):
        return 100000 if self.is_paged() else len(self.book.chapters[index].text)

    def handle_reader_navigation(self, key_name, modifiers):
        action = navigation_for(key_name, modifiers)
        if action is None or not self.reading_navigation_has_focus():
            return False
        # Initial raster layout has no meaningful scrollbar. Do not turn a
        # loading placeholder into a new saved/restored document position.
        if self.is_paged() and not self._document_ready and action not in {"book-start", "book-end"}:
            return True
        if self._restoring and action in {"line-up", "line-down", "page-up", "page-down",
                                           "turn-previous", "turn-next"}:
            # A chapter switch or distant text mark needs a few layout frames.
            # Repeated page keys must not use the preceding chapter's range.
            return True
        self.manual_scroll()
        if action in {"turn-previous", "turn-next"}:
            if self.is_paged():
                # A document page is independent of its zoomed viewport. Both
                # directions open the adjacent page at its top, never pan it.
                index = self.chapter_index + (-1 if action == "turn-previous" else 1)
                if 0 <= index < len(self.book.chapters):
                    self.display_chapter(index, 0)
                    self.queue_progress_save()
                return True
            # Reflowable books have no fixed page rectangle: retain the same
            # ten-percent context and boundary transitions as Page Up/Down.
            action = "page-up" if action == "turn-previous" else "page-down"
        if action in {"book-start", "book-end"}:
            index = 0 if action == "book-start" else len(self.book.chapters) - 1
            offset = 0 if action == "book-start" else self._navigation_end_offset(index)
            if index != self.chapter_index:
                self.display_chapter(index, offset)
            else:
                self.restore_position(offset)
            self.queue_progress_save()
            return True
        adjustment = self.reader_scroll.get_vadjustment()
        value, lower, upper, size = (adjustment.get_value(), adjustment.get_lower(),
                                     adjustment.get_upper(), adjustment.get_page_size())
        target = scroll_target(action, value, lower, upper, size, adjustment.get_step_increment())
        if action in {"page-up", "page-down"} and size > 0 and abs(target - value) < 0.01:
            delta = -1 if action == "page-up" else 1
            index = self.chapter_index + delta
            if 0 <= index < len(self.book.chapters):
                self.display_chapter(index, self._navigation_end_offset(index) if delta < 0 else 0)
                self.queue_progress_save()
                return True
        adjustment.set_value(target)
        if self.is_paged():
            # Record the new fraction after moving, so an in-flight scale/size
            # render cannot restore the snapshot from before this key press.
            self.document_position.user_input(self.document_geometry(), self.visible_offset())
        elif action in {"start", "end"}:
            # GtkTextView validates distant lines lazily. A text mark reaches
            # the true end even when its current scrollbar maximum is stale.
            self.restore_position(0 if action == "start" else self._navigation_end_offset(self.chapter_index))
        self.queue_progress_save()
        return True
