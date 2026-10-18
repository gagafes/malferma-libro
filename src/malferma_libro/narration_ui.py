"""Piper voice selection, explicit model installation and isolated previews."""

from gi.repository import GLib, Gtk

from .i18n import SPEECH_LANGUAGE_CODES, SPEECH_LANGUAGE_CHOICES
from .live_i18n import localized as _, localized_join
from .speech import SpeechReader, detect_language
from .tasks import OperationToken
from .voices import VoiceManager


SAMPLES = {
    "ru": "Откройте книгу и отправляйтесь в путешествие. История начинается здесь.",
    "uk": "Відкрийте книжку й вирушайте в подорож. Історія починається тут.",
    "en": "Open a book and begin a journey. The story starts here.",
    "de": "Öffnen Sie ein Buch und gehen Sie auf eine Reise. Hier beginnt die Geschichte.",
    "fr": "Ouvrez un livre et partez en voyage. L’histoire commence ici.",
    "es": "Abre un libro y comienza un viaje. La historia empieza aquí.",
    "it": "Apri un libro e inizia un viaggio. La storia comincia qui.",
    "pt": "Abra um livro e comece uma viagem. A história começa aqui.",
}


class NarrationMixin:
    def init_narration_ui(self):
        self.voice_manager = VoiceManager(self.library.root / "voices")
        self.voice_preview = None
        self._voice_ui_syncing = False
        self._voice_ui_closed = False
        self._voice_downloads = set()
        self._voice_selection_serial = 0
        self._voice_import_dialog = None

    def build_voice_preferences(self, group, row):
        from .app import button, label

        self.speech_voice = Gtk.DropDown()
        self.speech_voice.set_enable_search(True)
        row(group, _("Голос"), self.speech_voice)
        self.voice_model_status = label("", "dim-label", wrap=True)
        self.voice_model_status.set_max_width_chars(48)
        group.add(self.voice_model_status)
        controls = Gtk.Box(spacing=8, homogeneous=True)
        self.voice_download_button = button(_("Загрузить голос"), self.download_selected_voice)
        self.voice_import_button = button(_("Добавить голос…"), self.choose_voice_model)
        controls.append(self.voice_download_button)
        controls.append(self.voice_import_button)
        group.add(controls)
        playback = Gtk.Box(spacing=8, homogeneous=True)
        self.voice_preview_button = button(_("Прослушать образец"), self.preview_voice)
        playback.append(self.voice_preview_button)
        playback.append(button(_("Установка Piper"), self.show_manual))
        group.add(playback)
        group.add(label(_("Для своего голоса выберите файл .onnx с соседним .onnx.json. Условия использования задаёт автор модели."),
                        "dim-label", wrap=True))
        self.refresh_voice_choices()
        self.speech_voice.connect("notify::selected", self.voice_choice_changed)

    def refresh_voice_choices(self):
        if self._voice_ui_closed or not hasattr(self, "speech_voice"):
            return
        from .app import bind, translated_strings

        self._voice_ui_syncing = True
        try:
            settings = self.library.settings
            entries = self.voice_manager.voices_for(settings["speech_language"])
            self._voice_choices = tuple(entries)
            identifiers = ["auto", *(entry.id for entry in entries)]
            languages = dict(SPEECH_LANGUAGE_CHOICES)
            names = [f"{entry.name} · {languages[entry.language]}" for entry in entries]
            selected = settings.get("speech_voice", "auto")
            missing = selected not in identifiers
            if missing:
                identifiers.append(selected)
                names.append(localized_join(" · ", (_("Модель голоса не установлена"), selected)))
            self._voice_ids = tuple(identifiers)
            self.speech_voice.set_model(translated_strings([_("Автоматически"), *names]))
            self.speech_voice.set_selected(self._voice_ids.index(selected))
            entry = self.selected_voice_entry()
            installed = entry is not None and self.voice_manager.get_model(entry.language, voice_id=entry.id) is not None
            downloading = entry is not None and entry.id in self._voice_downloads
            if missing:
                message = _("Модель голоса не установлена")
            elif entry is None:
                message = (_("Выберите язык или голос.") if settings["speech_language"] == "auto"
                           else _("Для этого языка добавьте свою модель Piper."))
            else:
                message = _("Голос установлен") if installed else _("Модель голоса не установлена")
            bind(self.voice_model_status, label=message)
            self.voice_download_button.set_sensitive(entry is not None and not installed and not downloading)
            self.voice_preview_button.set_sensitive(installed)
        finally:
            self._voice_ui_syncing = False

    def selected_voice_entry(self):
        settings = self.library.settings
        language = settings["speech_language"]
        if language == "auto":
            if not self.book:
                return None
            language = detect_language(self.book.chapters[self.chapter_index].text[:4000])
        if language is None:
            return None
        return self.voice_manager.voice_for(language, voice_id=settings.get("speech_voice", "auto"))

    def voice_choice_changed(self, control, *_args):
        if self._voice_ui_closed or self._voice_ui_syncing or self._syncing_preferences:
            return
        index = control.get_selected()
        if not 0 <= index < len(self._voice_ids):
            return
        voice_id = self._voice_ids[index]
        changes = {"speech_voice": voice_id}
        if 0 < index <= len(self._voice_choices):
            changes["speech_language"] = self._voice_choices[index - 1].language
        if self.save_settings(changes):
            syncing = self._syncing_preferences
            self._syncing_preferences = True
            try:
                self.speech_language.set_selected(SPEECH_LANGUAGE_CODES.index(self.library.settings["speech_language"]))
            finally:
                self._syncing_preferences = syncing
            self.apply_narration_options()
        self.refresh_voice_choices()

    def download_selected_voice(self, *_args, voice_id=None):
        entry = self.selected_voice_entry()
        if voice_id is not None:
            entry = next((item for item in self.voice_manager.voices_for("auto") if item.id == voice_id), None)
        if entry is None or entry.id in self._voice_downloads:
            return
        token = OperationToken()
        selection = (self._voice_selection_serial, self._book_serial, self._speech_intent)
        self._voice_downloads.add(entry.id)
        self.refresh_voice_choices()

        def refresh(*_args):
            self._voice_downloads.discard(entry.id)
            self.refresh_voice_choices()

        def ready(_model):
            refresh()
            if selection == (self._voice_selection_serial, self._book_serial, self._speech_intent):
                self.set_status(_("Голос готов: {voice}").format(voice=entry.name))

        self.run_task(lambda: self.voice_manager.install(entry.id, cancel=token), ready,
                      _("Загрузка голоса: {voice}").format(voice=entry.name),
                      token=token, on_cancel=self.refresh_voice_choices, on_stale=refresh, on_error=refresh,
                      retry=lambda: self.download_selected_voice(voice_id=entry.id))

    def choose_voice_model(self, *_args):
        if self._voice_import_dialog is not None:
            self._voice_import_dialog.show()
            return
        from .app import _translations, bind

        dialog = Gtk.FileChooserNative.new(_("Добавить модель Piper"), self.preferences_window,
                                           Gtk.FileChooserAction.OPEN, _("Открыть…"), _("Отмена"))
        bind(dialog, title=_("Добавить модель Piper"))
        file_filter = Gtk.FileFilter()
        _translations.bind_value(file_filter, "name", _("Модель Piper (*.onnx)"), lambda item, value: item.set_name(value))
        file_filter.add_pattern("*.onnx")
        dialog.add_filter(file_filter)
        self._voice_import_dialog = dialog

        def response(chooser, result):
            selected = chooser.get_file() if result == Gtk.ResponseType.ACCEPT else None
            self._voice_import_dialog = None
            chooser.destroy()
            if selected is not None and selected.get_path() and not self._voice_ui_closed:
                self.import_voice_model(selected.get_path())

        dialog.connect("response", response)
        dialog.show()

    def import_voice_model(self, path):
        token = OperationToken()
        selection = (self._voice_selection_serial, self._book_serial, self._speech_intent)

        def ready(entry):
            current = (self._voice_selection_serial, self._book_serial, self._speech_intent)
            if current == selection and self.save_settings({"speech_voice": entry.id, "speech_language": entry.language}):
                syncing = self._syncing_preferences
                self._syncing_preferences = True
                try:
                    self.speech_language.set_selected(SPEECH_LANGUAGE_CODES.index(entry.language))
                finally:
                    self._syncing_preferences = syncing
                self.apply_narration_options()
            self.refresh_voice_choices()
            if current == selection:
                self.set_status(_("Голос готов: {voice}").format(voice=entry.name))

        self.run_task(lambda: self.voice_manager.import_model(path, cancel=token), ready,
                      _("Добавление голоса…"), token=token,
                      on_stale=self.refresh_voice_choices,
                      retry=lambda: self.import_voice_model(path))

    def preview_voice(self, *_args):
        if self.voice_preview is not None and self.voice_preview.state in {"speaking", "paused"}:
            self.stop_voice_preview()
            return
        entry = self.selected_voice_entry()
        if entry is None or self.voice_manager.get_model(entry.language, voice_id=entry.id) is None:
            return
        self._speech_intent += 1
        self.speech.pause()
        if self.voice_preview is not None:
            self.voice_preview.close()
        self.voice_preview = SpeechReader(GLib.idle_add, self.voice_preview_state,
                                          lambda *_args: None, lambda: self.voice_preview_state("idle", ""),
                                          voices=self.voice_manager)
        self.voice_preview.start(SAMPLES[entry.language], language=entry.language,
                                 rate=self.library.settings["speech_rate"], voice_id=entry.id)

    def voice_preview_state(self, state, message):
        if self._voice_ui_closed or self._closing:
            return
        from .app import accessible_label, bind, button_content

        title = _("Стоп") if state in {"speaking", "paused"} else _("Прослушать образец")
        button_content(self.voice_preview_button, title)
        accessible_label(self.voice_preview_button, title)
        bind(self.voice_preview_button, tooltip_text=title)
        if message:
            self.set_status(message)

    def stop_voice_preview(self):
        if self.voice_preview is not None:
            self.voice_preview.stop()
            self.voice_preview_state("idle", "")

    def show_voice_settings(self, *_args):
        self.preferences_window.set_visible_page(self.general_preferences_page)
        self.preferences_window.present()
        self.refresh_voice_choices()
        self.speech_voice.grab_focus()

    def narration_preferences_visible(self, window, *_args):
        if window.get_visible():
            self.refresh_voice_choices()
        else:
            self.stop_voice_preview()

    def close_narration_ui(self):
        self._voice_ui_closed = True
        if self.voice_preview is not None:
            self.voice_preview.close()
        if self._voice_import_dialog is not None:
            self._voice_import_dialog.destroy()
            self._voice_import_dialog = None
