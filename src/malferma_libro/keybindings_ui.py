"""Native, transactional keyboard preferences and a modal key capture dialog."""

from __future__ import annotations

from gi.repository import Adw, Gdk, Gtk

from .live_i18n import localized as _
from .shortcuts import (
    SHORTCUTS, BindingError, default_binding, effective_binding,
    effective_bindings, find_conflict, validate_binding,
)


_RESET_RESPONSE = 101
_DISABLE_RESPONSE = 102
_MODIFIER_FLAGS = (
    ("control", "CONTROL_MASK"), ("shift", "SHIFT_MASK"), ("alt", "ALT_MASK"),
    ("super", "SUPER_MASK"), ("meta", "META_MASK"), ("hyper", "HYPER_MASK"),
)
_MODIFIER_KEYS = frozenset({
    "Control_L", "Control_R", "Shift_L", "Shift_R", "Alt_L", "Alt_R",
    "Super_L", "Super_R", "Meta_L", "Meta_R", "Hyper_L", "Hyper_R",
    "ISO_Level3_Shift", "ISO_Level5_Shift", "Mode_switch",
})


class KeybindingsMixin:
    """Persist only validated changes; canonical dispatch lives in shortcuts.py."""

    def build_shortcut_preferences(self, target):
        from .app import accessible_label, bind, button, translated, translated_dropdown

        self.shortcut_dialog = None
        self._shortcut_ui_closed = False
        self._shortcut_ui_syncing = False
        self.shortcut_rows = {}
        if isinstance(target, Adw.PreferencesWindow):
            self._shortcut_preferences_host = target
            page = translated(Adw.PreferencesPage, title=_("Горячие клавиши"),
                              icon_name="preferences-desktop-keyboard-shortcuts-symbolic")
            target.add(page)
        else:
            page = target
            self._shortcut_preferences_host = None
        self.shortcut_preferences_page = page
        options = translated(Adw.PreferencesGroup, title=_("Горячие клавиши"))
        page.add(options)
        mode_row = translated(Adw.ActionRow, title=_("Режим"))
        self.shortcut_mode_selector = translated_dropdown([_("По умолчанию"), _("Пользовательские")])
        self.shortcut_mode_selector.set_valign(Gtk.Align.CENTER)
        accessible_label(self.shortcut_mode_selector, _("Режим"))
        mode_row.add_suffix(self.shortcut_mode_selector)
        mode_row.set_activatable_widget(self.shortcut_mode_selector)
        options.add(mode_row)
        self.shortcut_restore_all = button(_("Восстановить все сочетания"), self.reset_all_shortcuts)
        options.add(self.shortcut_restore_all)
        groups = {}
        for shortcut in SHORTCUTS:
            group = groups.get(shortcut.group)
            if group is None:
                group = translated(Adw.PreferencesGroup, title=_(shortcut.group))
                groups[shortcut.group] = group
                page.add(group)
            row = translated(Adw.ActionRow, title=_(shortcut.title))
            row.shortcut_action = shortcut.action
            row.shortcut_label = translated(Gtk.ShortcutLabel, disabled_text=_("Отключено"))
            row.shortcut_label.set_direction(Gtk.TextDirection.LTR)
            row.shortcut_label.set_valign(Gtk.Align.CENTER)
            row.add_suffix(row.shortcut_label)
            row.edit_button = button(_("Изменить сочетание"),
                                     lambda _button, action=shortcut.action: self.show_shortcut_editor(action),
                                     compact=True, icon="document-edit-symbolic")
            row.edit_button.set_valign(Gtk.Align.CENTER)
            row.add_suffix(row.edit_button)
            row.set_activatable_widget(row.edit_button)
            group.add(row)
            self.shortcut_rows[shortcut.action] = row
        self._shortcut_mode_handler = self.shortcut_mode_selector.connect(
            "notify::selected", self._shortcut_mode_changed)
        self.refresh_shortcut_ui()
        return page

    def refresh_shortcut_ui(self):
        if getattr(self, "_shortcut_ui_closed", True):
            return
        self._shortcut_ui_syncing = True
        try:
            settings = self.library.settings
            self.shortcut_mode_selector.set_selected(1 if settings["shortcut_mode"] == "custom" else 0)
            for shortcut in effective_bindings(settings):
                try:
                    accelerator = self._binding_accelerator(effective_binding(shortcut.action, settings))
                except BindingError:
                    accelerator = ""
                self.shortcut_rows[shortcut.action].shortcut_label.set_accelerator(accelerator)
            self.shortcut_restore_all.set_sensitive(
                settings["shortcut_mode"] != "default" or bool(settings["custom_shortcuts"]))
        finally:
            self._shortcut_ui_syncing = False

    def _save_shortcut_preferences(self, changes):
        saved = self.save_settings(changes)
        self.refresh_shortcut_ui()
        if saved:
            hook = getattr(self, "shortcut_bindings_changed", None)
            if hook is not None:
                hook()
        return saved

    def _shortcut_mode_changed(self, control, *_args):
        if self._shortcut_ui_closed or self._shortcut_ui_syncing or self._syncing_preferences:
            return
        mode = "custom" if control.get_selected() == 1 else "default"
        self._save_shortcut_preferences({"shortcut_mode": mode})

    def reset_all_shortcuts(self, *_args):
        if not self._shortcut_ui_closed:
            self._save_shortcut_preferences({"shortcut_mode": "default", "custom_shortcuts": {}})

    @staticmethod
    def _binding_accelerator(binding):
        if binding is None:
            return ""
        key = Gdk.keyval_from_name(binding["key"])
        if key in (0, Gdk.KEY_VoidSymbol):
            raise BindingError("invalid")
        modifiers = Gdk.ModifierType(0)
        for name, flag in _MODIFIER_FLAGS:
            if name in binding["modifiers"]:
                modifiers |= getattr(Gdk.ModifierType, flag, 0)
        # Unmodified Space is intentionally scoped to the reading surface by
        # the model. GTK's global-accelerator policy must not disable it.
        if not Gtk.accelerator_valid(key, modifiers) and not (key == Gdk.KEY_space and not modifiers):
            raise BindingError("invalid")
        return Gtk.accelerator_name(key, modifiers)

    def _shortcut_candidate_settings(self, dialog):
        overrides = dict(self.library.settings["custom_shortcuts"])
        if dialog.reset_to_default:
            overrides.pop(dialog.shortcut_action, None)
        else:
            overrides[dialog.shortcut_action] = dialog.candidate_binding
        return self.library.settings | {"shortcut_mode": "custom", "custom_shortcuts": overrides}

    @staticmethod
    def _shortcut_binding_error(error):
        if error.code in {"reserved", "modifiers"}:
            return _("Это сочетание зарезервировано системой.")
        if error.code in {"typing", "space"}:
            return _("Используйте Ctrl, Alt или функциональную клавишу.")
        return _("Некорректное сочетание клавиш.")

    def _validate_shortcut_candidate(self, dialog):
        from .app import bind

        dialog.candidate_valid = False
        dialog.candidate_accelerator = ""
        try:
            dialog.candidate_binding = validate_binding(dialog.candidate_binding, action=dialog.shortcut_action)
            dialog.candidate_accelerator = self._binding_accelerator(dialog.candidate_binding)
            conflict = find_conflict(dialog.shortcut_action, dialog.candidate_binding,
                                     self._shortcut_candidate_settings(dialog))
        except BindingError as error:
            message = self._shortcut_binding_error(error)
        else:
            if conflict:
                title = next(shortcut.title for shortcut in SHORTCUTS if shortcut.action == conflict)
                message = _("Сочетание занято: {action}").format(action=_(title))
            else:
                dialog.candidate_valid = True
                message = ""
        bind(dialog.error_label, label=message)
        dialog.error_label.set_visible(bool(message))
        dialog.save_button.set_sensitive(dialog.candidate_valid)
        return dialog.candidate_valid

    def set_shortcut_candidate(self, dialog, binding, *, reset=False):
        if self._shortcut_ui_closed or dialog is not self.shortcut_dialog:
            return False
        dialog.candidate_binding = binding
        dialog.reset_to_default = reset
        valid = self._validate_shortcut_candidate(dialog)
        dialog.capture_label.set_accelerator(dialog.candidate_accelerator)
        dialog.capture_area.grab_focus()
        return valid

    def show_shortcut_editor(self, action):
        from .app import accessible_label, bind, label, margins, translated, translated_dialog_button

        if self._shortcut_ui_closed:
            return None
        shortcut = next((item for item in SHORTCUTS if item.action == action), None)
        if shortcut is None:
            return None
        if self.shortcut_dialog is not None:
            self._destroy_shortcut_dialog(self.shortcut_dialog)
        parent = self._shortcut_preferences_host or self
        dialog = translated(Gtk.Dialog, transient_for=parent, modal=True, destroy_with_parent=True,
                            title=_(shortcut.title))
        dialog.set_default_size(480, 260)
        dialog.set_direction(self.get_direction())
        dialog.shortcut_action = action
        dialog.candidate_binding = effective_binding(action, self.library.settings)
        dialog.candidate_valid = False
        dialog.reset_to_default = False
        content = margins(dialog.get_content_area(), 16)
        content.set_spacing(12)
        prompt = label(_("Нажмите новое сочетание клавиш."), wrap=True)
        prompt.set_max_width_chars(45)
        content.append(prompt)
        dialog.capture_label = translated(Gtk.ShortcutLabel, disabled_text=_("Отключено"))
        dialog.capture_label.set_direction(Gtk.TextDirection.LTR)
        try:
            accelerator = self._binding_accelerator(dialog.candidate_binding)
        except BindingError:
            accelerator = ""
        dialog.capture_label.set_accelerator(accelerator)
        dialog.capture_area = Gtk.Button(child=dialog.capture_label)
        dialog.capture_area.set_margin_top(4)
        dialog.capture_area.set_margin_bottom(4)
        accessible_label(dialog.capture_area, _("Нажмите новое сочетание клавиш."))
        content.append(dialog.capture_area)
        dialog.error_label = label("", "error", wrap=True)
        dialog.error_label.set_max_width_chars(45)
        dialog.error_label.set_visible(False)
        content.append(dialog.error_label)
        dialog.reset_button = translated_dialog_button(dialog, _("По умолчанию"), _RESET_RESPONSE)
        dialog.reset_button.set_sensitive(action in self.library.settings["custom_shortcuts"])
        dialog.disable_button = translated_dialog_button(dialog, _("Отключить"), _DISABLE_RESPONSE)
        translated_dialog_button(dialog, _("Отмена"), Gtk.ResponseType.CANCEL)
        dialog.save_button = translated_dialog_button(dialog, _("Сохранить"), Gtk.ResponseType.ACCEPT)
        dialog.save_button.add_css_class("suggested-action")
        dialog.save_button.set_sensitive(False)
        dialog.key_controller = Gtk.EventControllerKey()
        dialog.key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        dialog._shortcut_key_handler = dialog.key_controller.connect(
            "key-pressed", lambda _controller, key, _code, state: self.capture_shortcut_key(dialog, key, state))
        dialog.add_controller(dialog.key_controller)
        dialog._shortcut_response_handler = dialog.connect("response", self._shortcut_editor_response)
        dialog._shortcut_close_handler = dialog.connect("close-request", self._shortcut_editor_close)
        self.shortcut_dialog = dialog
        dialog.present()
        dialog.capture_area.grab_focus()
        return dialog

    def capture_shortcut_key(self, dialog, key, state):
        """Consume capture keys while retaining native keyboard access to buttons."""
        if self._shortcut_ui_closed or dialog is not self.shortcut_dialog:
            return True
        name = Gdk.keyval_name(key)
        modifiers = [name for name, flag in _MODIFIER_FLAGS if state & getattr(Gdk.ModifierType, flag, 0)]
        if key == Gdk.KEY_Escape:
            dialog.response(Gtk.ResponseType.CANCEL)
            return True
        if name in _MODIFIER_KEYS:
            return True
        if key in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab) and not set(modifiers) - {"shift"}:
            backward = key == Gdk.KEY_ISO_Left_Tab or "shift" in modifiers
            dialog.child_focus(Gtk.DirectionType.TAB_BACKWARD if backward else Gtk.DirectionType.TAB_FORWARD)
            return True
        focus = dialog.get_focus()
        if not modifiers and focus is not dialog.capture_area:
            if key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space) and isinstance(focus, Gtk.Button):
                focus.emit("clicked")
                return True
            directions = {Gdk.KEY_Left: Gtk.DirectionType.LEFT, Gdk.KEY_Right: Gtk.DirectionType.RIGHT,
                          Gdk.KEY_Up: Gtk.DirectionType.UP, Gdk.KEY_Down: Gtk.DirectionType.DOWN}
            if key in directions:
                dialog.child_focus(directions[key])
                return True
        if not modifiers and key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and dialog.candidate_valid:
            dialog.response(Gtk.ResponseType.ACCEPT)
            return True
        self.set_shortcut_candidate(dialog, {"key": name, "modifiers": modifiers})
        return True

    def _shortcut_editor_response(self, dialog, response):
        from .app import bind

        if self._shortcut_ui_closed or dialog is not self.shortcut_dialog:
            return
        if response == _DISABLE_RESPONSE:
            self.set_shortcut_candidate(dialog, None)
            return
        if response == _RESET_RESPONSE:
            self.set_shortcut_candidate(dialog, default_binding(dialog.shortcut_action), reset=True)
            return
        if response == Gtk.ResponseType.ACCEPT:
            if not dialog.candidate_valid or not self._validate_shortcut_candidate(dialog):
                return
            settings = self._shortcut_candidate_settings(dialog)
            changes = {"custom_shortcuts": settings["custom_shortcuts"],
                       "shortcut_mode": self.library.settings["shortcut_mode"] if dialog.reset_to_default else "custom"}
            if not self._save_shortcut_preferences(changes):
                bind(dialog.error_label, label=_("Не удалось сохранить библиотеку"))
                dialog.error_label.set_visible(True)
                return
        self._destroy_shortcut_dialog(dialog)

    def _shortcut_editor_close(self, dialog):
        self._destroy_shortcut_dialog(dialog)
        return True

    def _destroy_shortcut_dialog(self, dialog):
        if dialog is not self.shortcut_dialog:
            return
        self.shortcut_dialog = None
        dialog.disconnect(dialog._shortcut_response_handler)
        dialog.disconnect(dialog._shortcut_close_handler)
        dialog.key_controller.disconnect(dialog._shortcut_key_handler)
        dialog.remove_controller(dialog.key_controller)
        dialog.destroy()

    def close_shortcut_ui(self):
        if getattr(self, "_shortcut_ui_closed", True):
            return
        self._shortcut_ui_closed = True
        if self.shortcut_dialog is not None:
            self._destroy_shortcut_dialog(self.shortcut_dialog)
        self.shortcut_mode_selector.disconnect(self._shortcut_mode_handler)
