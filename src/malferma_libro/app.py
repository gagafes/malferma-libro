"""Adaptive GTK/libadwaita reader that respects desktop preferences."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from xml.sax.saxutils import escape
import logging
import math
import tempfile
from urllib.parse import quote

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango

from . import APP_ID, APP_NAME, __version__
from .i18n import (
    configure_language, is_rtl_language, LANGUAGE_CHOICES, SPEECH_LANGUAGE_CHOICES,
    INTERFACE_LANGUAGE_CODES, SPEECH_LANGUAGE_CODES,
)
from .live_i18n import LocalizedText, TranslationBindings, localized as _, localized_join
from .books import load_book
from .opds import download_book, fetch_catalog
from .storage import (
    Library, FONT_SIZE_MIN, FONT_SIZE_MAX, READER_WIDTH_MIN, READER_WIDTH_MAX,
    LINE_SPACING_MIN, LINE_SPACING_MAX,
)
from .gestures import GestureNavigation
from .document_layout import page_layout
from .document_position import DocumentPosition
from .library_ui import LibraryMixin
from .search_ui import SearchMixin
from .immersive import ImmersiveMixin
from .task_ui import TaskMixin
from .bookmarks_ui import BookmarkMixin
from .accessibility_ui import AccessibilityMixin
from .pagination import PageNumberMixin
from .outline_ui import OutlineMixin
from .cover_ui import CoverUIMixin
from .illustration_ui import IllustrationUIMixin
from .illustrations import TextImageOffsets
from .keybindings_ui import KeybindingsMixin
from .narration_ui import NarrationMixin
from .keyboard_ui import KeyboardNavigationMixin
from .keyboard_navigation import NAVIGATION_SHORTCUTS
from .reading_state import ReadingProgressIndex
from .tasks import OperationToken
from .importing import import_books
from .helptext import MANUAL_LANGUAGES, manual_language, manual_text
from .shortcuts import BindingError, SHORTCUTS, READING, effective_bindings, effective_binding, shortcut_for
from .appearance import FONT_FAMILIES, font_css, reader_colors, reader_theme
from .desktop import BOOK_EXTENSIONS, BOOK_FILTER_NAME, PortalFileChooser
from .desktop_settings import DesktopAppearance
from .speech import SpeechReader
from .textlayout import paragraph_runs
from .pdf import PdfError
from .djvu import DjvuError
from .cbz import CbzError


LOG = logging.getLogger(__name__)
BRANDING_DIR = Path(__file__).resolve().parent / "assets" / "branding"

BUTTON_ICONS = {
    "Открыть…": "document-open-symbolic",
    "‹": "go-previous-symbolic", "›": "go-next-symbolic",
    "Найти": "edit-find-symbolic", "＋ Закладка": "bookmark-new-symbolic",
    "＋": "list-add-symbolic", "−": "list-remove-symbolic", "×": "window-close-symbolic",
    "Озвучить": "media-playback-start-symbolic", "Продолжить": "media-playback-start-symbolic",
    "Пауза": "media-playback-pause-symbolic", "Стоп": "media-playback-stop-symbolic",
    "Назад": "go-previous-symbolic", "Далее": "go-next-symbolic",
    "Подключиться": "network-server-symbolic", "Открыть раздел": "folder-open-symbolic",
}


_translations = TranslationBindings()


def bind(widget, **properties):
    """Set UI text and retain its source when it is explicitly localized."""
    return _translations.bind(widget, **properties)


def translated(factory, *args, **properties):
    widget = factory(*args, **properties)
    bind(widget, **{key: value for key, value in properties.items()
                    if isinstance(value, LocalizedText)})
    if isinstance(widget, Gtk.Label) and "xalign" in properties:
        _translations.leading_label(widget)
    return widget


def accessible_label(widget, text):
    return _translations.bind_value(
        widget, "accessible-label", text,
        lambda item, value: item.update_property([Gtk.AccessibleProperty.LABEL], [value]),
    )


def translated_strings(values):
    model = Gtk.StringList.new([])

    def replace(item, strings):
        current = tuple(item.get_string(index) for index in range(item.get_n_items()))
        if current != tuple(strings):
            item.splice(0, item.get_n_items(), list(strings))

    return _translations.bind_sequence(model, "strings", values, replace)


def translated_dropdown(values):
    return Gtk.DropDown(model=translated_strings(values))


def translated_page(stack, child, name, title):
    return bind(stack.add_titled(child, name, title), title=title)


def translated_dialog_button(dialog, text, response):
    return bind(dialog.add_button(text, response), label=text)


def translated_menu(items):
    menu = Gio.Menu()
    actions = tuple(action for _title, action in items)

    def replace(item, titles):
        for index, (title, action) in enumerate(zip(titles, actions)):
            if index < item.get_n_items():
                current = item.get_item_attribute_value(index, "label", None)
                if current is not None and current.unpack() == title:
                    continue
                # Keep an open menu populated while replacing its labels.
                item.insert(index, title, action)
                item.remove(index + 1)
            else:
                item.append(title, action)

    return _translations.bind_sequence(menu, "items", (title for title, _action in items), replace)


def button_content(widget, text, compact=False, icon=None):
    # Icon lookup keeps stable source labels while UI text follows the locale.
    icon = icon or BUTTON_ICONS.get(text) or next(
        (name for source, name in BUTTON_ICONS.items() if _(source) == text), None
    )
    if not icon:
        bind(widget, label=text)
        return
    image = Gtk.Image.new_from_gicon(Gio.ThemedIcon.new_from_names([icon, icon.removesuffix("-symbolic")]))
    if compact or text in {"‹", "›", "＋", "−", "×"}:
        widget.set_child(image)
        bind(widget, tooltip_text=text)
        accessible_label(widget, text)
    else:
        box = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        box.append(image)
        box.append(translated(Gtk.Label, label=text))
        widget.set_child(box)


def margins(widget, size=12):
    for side in ("top", "bottom", "start", "end"):
        getattr(widget, f"set_margin_{side}")(size)
    return widget


def label(text, css=None, wrap=False):
    widget = translated(Gtk.Label, label=text, xalign=1 if Gtk.Widget.get_default_direction() == Gtk.TextDirection.RTL else 0)
    widget.set_wrap(wrap)
    if wrap:
        widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if css:
        widget.add_css_class(css)
    return widget


def button(text, callback, tooltip=None, compact=False, icon=None):
    widget = Gtk.Button()
    button_content(widget, text, compact, icon)
    widget.connect("clicked", callback)
    if tooltip:
        bind(widget, tooltip_text=tooltip)
        accessible_label(widget, tooltip)
    return widget


class DocumentPaintable(GObject.Object, Gdk.Paintable):
    """Keep the page's logical size independent of its HiDPI raster density."""

    def __init__(self, texture, width, height):
        super().__init__()
        self.texture = texture
        self.width, self.height = width, height

    def do_get_intrinsic_width(self):
        return self.width

    def do_get_intrinsic_height(self):
        return self.height

    def do_get_intrinsic_aspect_ratio(self):
        return self.width / self.height

    def do_get_flags(self):
        # Static size (bit 0) and contents (bit 1); GI versions expose these
        # as either STATIC_SIZE/STATIC_CONTENTS or SIZE/CONTENTS.
        return Gdk.PaintableFlags(3)

    def do_snapshot(self, snapshot, width, height):
        self.texture.snapshot(snapshot, width, height)


class ReaderApplication(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_OPEN,
        )
        self.window = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        GLib.set_application_name(APP_NAME)
        Gtk.Window.set_default_icon_name(APP_ID)
        display = Gdk.Display.get_default()
        if display is not None:
            # Keep source checkouts branded without replacing desktop control icons.
            Gtk.IconTheme.get_for_display(display).add_search_path(str(BRANDING_DIR))

    def do_activate(self):
        self.activate_window()

    def activate_window(self, restore=True):
        if self.window is None:
            try:
                self.window = ReaderWindow(self)
            except (OSError, ValueError) as error:
                dialog = translated(Gtk.MessageDialog,
                    application=self,
                    modal=True,
                    message_type=Gtk.MessageType.ERROR,
                    buttons=Gtk.ButtonsType.CLOSE,
                    text=_("Не удалось открыть библиотеку"),
                    secondary_text=str(error),
                )
                dialog.connect("response", lambda item, _response: item.destroy())
                dialog.present()
                return
        self.window.present()
        if restore:
            self.window.maybe_reopen_last_book()

    def do_open(self, files, _count, _hint):
        self.activate_window(restore=False)
        paths = [item.get_path() for item in files if item.get_path()]
        if paths and self.window is not None:
            self.window.import_paths(paths)


class ReaderWindow(LibraryMixin, SearchMixin, ImmersiveMixin, TaskMixin, BookmarkMixin,
                   AccessibilityMixin, PageNumberMixin, OutlineMixin, CoverUIMixin, KeybindingsMixin, NarrationMixin,
                   KeyboardNavigationMixin, IllustrationUIMixin,
                   Adw.ApplicationWindow):
    def __init__(self, application):
        library = Library()
        startup_language = library.settings.get("interface_language", "system")
        resolved_language = configure_language(startup_language)
        direction = Gtk.TextDirection.RTL if is_rtl_language(resolved_language) else Gtk.TextDirection.LTR
        Gtk.Widget.set_default_direction(direction)
        super().__init__(application=application, title=APP_NAME)
        self.set_direction(direction)
        self.add_css_class("reader-window")
        self.set_icon_name(APP_ID)
        self.set_default_size(1080, 760)
        self.set_size_request(560, 420)
        self.library = library
        self.init_narration_ui()
        self._startup_interface_language = startup_language
        self._resolved_interface_language = resolved_language
        self.executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="reader")
        self.init_cover_ui()
        self.book = None
        self._reading_progress_index = ReadingProgressIndex.from_book(None)
        self.record = None
        self.chapter_index = 0
        self._chapter_switch = False
        self._restoring = False
        self._restore_serial = 0
        self._pending_offset = 0
        self._book_serial = 0
        self._navigation_serial = 0
        self._internal_navigation = False
        self._last_page = "library"
        self._speech_offset = None
        self._speech_intent = 0
        self._speech_completion_intent = 0
        self._restore_mark = None
        self._save_source = None
        self._closing = False
        self._accessibility_popup_tick = None
        self.manual_window = None
        self.manual_text_view = None
        self.manual_language_selector = None
        self._manual_language_override = None
        self._manual_text_language = None
        self.shortcuts_window = None
        self._syncing_preferences = False
        self._busy_count = 0
        self._catalog_serial = 0
        self.page_document = None
        self._document_serial = 0
        self._document_ready = False
        self._document_render_pending = False
        self._document_view_width = 0
        self._document_view_height = 0
        self._document_view_scale = 1
        self.document_position = DocumentPosition()
        self._document_resize_source = None
        self._document_future = None
        self._portal_chooser = None
        self._native_chooser = None
        self._reader_layout_key = None
        self.mouse_navigation = GestureNavigation()
        self._mouse_active = False
        self._mouse_origin = (0, 0)
        self._mouse_distance = 0
        self._mouse_context = None
        self.desktop_appearance = None
        self.catalog_page = None
        self.catalog_history = []
        self.catalog_url = None
        self.style_manager = Adw.StyleManager.get_default()
        self._style_handler = None
        self._style_support_handler = None
        self._style_contrast_handler = None
        self._reader_style_key = None
        self.css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), self.css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self.stack = Adw.ViewStack(vexpand=True)
        self.header_titles = Gtk.Stack(hhomogeneous=False, vhomogeneous=False)
        self.search_stack = Gtk.Stack(hhomogeneous=False, vhomogeneous=False)
        self.toast_overlay = Adw.ToastOverlay(child=self.stack)
        self._status_toast = None
        self.toolbar_view = toolbar_view = Adw.ToolbarView()
        toolbar_view.set_content(self.toast_overlay)
        self.set_content(toolbar_view)
        self.header = header = Adw.HeaderBar()
        header.set_title_widget(self.header_titles)
        self.header_start = Gtk.Box(spacing=8)
        self.header_end = Gtk.Box(spacing=8)
        self.file_controls = Gtk.Box(spacing=2)
        self.section_controls = Gtk.Box(spacing=2)
        self.document_controls = Gtk.Box(spacing=2)
        self.view_controls = Gtk.Box(spacing=2)
        self.utility_controls = Gtk.Box(spacing=2)
        self.header_start.append(self.file_controls)
        self.header_start.append(self.section_controls)
        self.header_end.append(self.document_controls)
        self.header_end.append(self.view_controls)
        self.header_end.append(self.utility_controls)
        header.pack_start(self.header_start)
        header.pack_end(self.header_end)
        self.open_button = button(_("Открыть…"), self.choose_files, compact=True)
        self.file_controls.append(self.open_button)
        self.spinner = Gtk.Spinner()
        toolbar_view.add_top_bar(header)

        translated_page(self.stack, self.build_library(), "library", _("Мои книги"))
        translated_page(self.stack, self.build_reader(), "reader", _("Чтение"))
        translated_page(self.stack, self.build_catalogs(), "catalogs", _("Сетевые библиотеки"))
        self.section_controls.append(self.library_controls)
        self.section_controls.append(self.reader_navigation)
        self.section_controls.append(self.catalog_navigation)
        self.search_popover = Gtk.Popover(child=margins(self.search_stack, 12))
        self.search_popover.set_size_request(300, -1)
        self.search_button = translated(Gtk.MenuButton, icon_name="edit-find-symbolic", tooltip_text=_("Найти"))
        accessible_label(self.search_button, _("Найти"))
        self.search_button.set_popover(self.search_popover)
        self.document_controls.append(self.search_button)
        self.document_controls.append(self.reader_actions)
        self.day_night_button = Gtk.ToggleButton(icon_name="weather-clear-night-symbolic")
        self.day_night_button.connect("clicked", self.toggle_day_night)
        self.view_controls.append(self.day_night_button)
        self.fullscreen_button = button(_("Полноэкранный режим"), self.toggle_fullscreen,
                                        compact=True, icon="view-fullscreen-symbolic")
        self.view_controls.append(self.fullscreen_button)
        self.connect("notify::fullscreened", self.sync_fullscreen)
        # Keep the last message available to diagnostics without a permanent footer.
        self.status = label(_("Добавьте книгу или подключите OPDS-каталог."))

        self.preferences_window = self.build_preferences()
        self.preferences_window.connect("notify::visible", self.narration_preferences_visible)
        self.init_reading_magnifier(self.reader_overlay)
        self.accessibility_button = self.build_accessibility_menu()
        self.utility_controls.append(self.accessibility_button)
        self.init_tasks()
        self.init_book_search()
        self.init_immersive()
        preferences_action = Gio.SimpleAction.new("preferences", None)
        preferences_action.connect("activate", lambda *_args: self.preferences_window.present())
        self.add_action(preferences_action)
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self.show_about)
        self.add_action(about_action)
        for name, callback in (("manual", self.show_manual), ("shortcuts", self.show_shortcuts)):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)
        for page in ("library", "reader", "catalogs"):
            action = Gio.SimpleAction.new(page, None)
            action.connect("activate", lambda _action, _parameter, page=page:
                           self.stack.set_visible_child_name(page))
            self.add_action(action)
        menu = Gio.Menu()
        menu.append_section(None, translated_menu((
            (_("Мои книги"), "win.library"),
            (_("Чтение"), "win.reader"),
            (_("Сетевые библиотеки"), "win.catalogs"),
        )))
        menu.append_section(None, translated_menu((
            (_("Настройки"), "win.preferences"),
            (_("Руководство пользователя"), "win.manual"),
            (_("Горячие клавиши"), "win.shortcuts"),
            (_("О приложении"), "win.about"),
        )))
        self.main_menu_button = menu_button = translated(Gtk.MenuButton, icon_name="open-menu-symbolic", menu_model=menu, tooltip_text=_("Главное меню"))
        accessible_label(menu_button, _("Главное меню"))
        self.utility_controls.append(menu_button)
        self.speech = SpeechReader(GLib.idle_add, self.speech_state, self.speech_range, self.speech_finished,
                                   voices=self.voice_manager)
        self.speech_state(self.speech.state, "")
        self.stack.connect("notify::visible-child-name", self.page_changed)
        self._style_handler = self.style_manager.connect("notify::dark", self.refresh_reader_style)
        self._style_contrast_handler = self.style_manager.connect(
            "notify::high-contrast", self.refresh_reader_style)
        self._style_support_handler = self.style_manager.connect(
            "notify::system-supports-color-schemes", lambda *_args: self.desktop_style_changed(None))
        self.desktop_appearance = DesktopAppearance(
            Gtk.Settings.get_default(), self.desktop_style_changed,
            initial_dark=self.style_manager.get_dark(),
        )

        self.apply_style()
        self.shortcut_bindings_changed()
        self.refresh_library()
        self.refresh_catalogs()
        self.update_header()
        self.connect("close-request", self.on_close)
        self.key_controller = Gtk.EventControllerKey()
        # Observe navigation before TextView consumes its keyboard bindings.
        self.key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.key_controller.connect("key-pressed", self.on_key)
        self.add_controller(self.key_controller)
        if self.library.warning:
            self.set_status(self.library.warning)

    def toggle_fullscreen(self, *_args):
        self.cancel_mouse_gesture()
        if self.is_fullscreen():
            self.unfullscreen()
        else:
            self.fullscreen()

    def sync_fullscreen(self, *_args):
        active = self.is_fullscreen()
        button_content(self.fullscreen_button,
                       _("Выйти из полноэкранного режима") if active else _("Полноэкранный режим"),
                       compact=True, icon="view-restore-symbolic" if active else "view-fullscreen-symbolic")
        self.refresh_shortcut_hints()
        self.sync_immersive()

    def _resolved_reader_theme(self):
        desktop_dark = self.desktop_appearance.dark if self.desktop_appearance else self.style_manager.get_dark()
        return reader_theme(self.library.settings.get("theme", "system"), desktop_dark)

    def sync_day_night(self):
        if not hasattr(self, "day_night_button"):
            return
        night = self._resolved_reader_theme() == "dark"
        self.day_night_button.set_active(night)
        self.day_night_button.set_icon_name("weather-clear-symbolic" if night else "weather-clear-night-symbolic")
        text = _("Включить дневной режим") if night else _("Включить ночной режим")
        hint = self.shortcut_hint("day-night", text)
        bind(self.day_night_button, tooltip_text=hint)
        accessible_label(self.day_night_button, hint)

    def toggle_day_night(self, *_args):
        offset = self.current_offset() if self.book else None
        target = "light" if self._resolved_reader_theme() == "dark" else "dark"
        if not self.save_settings({"theme": target, "interface_theme": target}):
            self.sync_day_night()
            return
        syncing = self._syncing_preferences
        self._syncing_preferences = True
        try:
            self.theme_selector.set_selected(("system", "light", "sepia", "dark").index(target))
            self.interface_selector.set_selected(("system", "light", "dark").index(target))
        finally:
            self._syncing_preferences = syncing
        self.apply_interface_scheme()
        self.refresh_reader_style()
        if offset is not None:
            self.restore_position(offset)

    def shortcut_hint(self, action, title):
        binding = effective_binding(action, self.library.settings)
        if binding is None:
            return title
        modifiers = Gdk.ModifierType(0)
        for name, mask in (("control", Gdk.ModifierType.CONTROL_MASK),
                           ("shift", Gdk.ModifierType.SHIFT_MASK),
                           ("alt", Gdk.ModifierType.ALT_MASK)):
            if name in binding["modifiers"]:
                modifiers |= mask
        key = Gdk.keyval_from_name(binding["key"])
        if key in (0, Gdk.KEY_VoidSymbol):
            return title
        accelerator = Gtk.accelerator_get_label(key, modifiers)
        return localized_join(" · ", (title, accelerator))

    def refresh_shortcut_hints(self):
        fullscreen = (_("Выйти из полноэкранного режима") if self.is_fullscreen()
                      else _("Полноэкранный режим"))
        targets = (
            ("open_button", "open", _("Открыть книги")),
            ("search_button", "search", _("Найти")),
            ("toc_button", "contents", _("Оглавление")),
            ("previous_button", "previous", _("Предыдущая глава")),
            ("next_button", "next", _("Следующая глава")),
            ("fullscreen_button", "fullscreen", fullscreen),
            ("accessibility_button", "accessibility", _("Специальные возможности")),
            ("text_size_decrease", "smaller", _("Уменьшить текст")),
            ("text_size_reset", "reset-size", _("Стандартный размер текста")),
            ("text_size_increase", "larger", _("Увеличить текст")),
        )
        for name, action, title in targets:
            widget = getattr(self, name, None)
            if widget is not None:
                hint = self.shortcut_hint(action, title)
                bind(widget, tooltip_text=hint)
                accessible_label(widget, hint)
        self.sync_day_night()

    def shortcut_bindings_changed(self):
        self.refresh_shortcut_ui()
        self.refresh_shortcut_hints()
        if hasattr(self, "_shortcut_widgets"):
            shortcuts = effective_bindings(self.library.settings)
            for shortcut in shortcuts:
                widget = self._shortcut_widgets[shortcut.action]
                try:
                    accelerator = self._binding_accelerator(effective_binding(shortcut.action, self.library.settings))
                except BindingError:
                    accelerator = ""
                widget.set_property("accelerator", accelerator)
                widget.set_visible(bool(shortcut.combinations))
            for group, widget in self._shortcut_groups.items():
                widget.set_visible(group == READING or any(item.group == group and item.combinations for item in shortcuts))
            for shortcut, widget in self._navigation_shortcut_widgets:
                # A user action can replace e.g. Ctrl+Home. Keep the static
                # navigation guide honest about the active shortcut profile.
                widget.set_visible(shortcut_for(
                    shortcut.key_name, shortcut.modifiers, reading=True,
                    has_book=True, reading_focus=True, settings=self.library.settings,
                ) is None)

    def show_about(self, *_args):
        dialog = translated(Adw.AboutWindow,
            transient_for=self,
            modal=True,
            destroy_with_parent=True,
            application_name=APP_NAME,
            application_icon=APP_ID,
            version=__version__,
            comments=_("Читалка EPUB, FB2, TXT, PDF, DjVu, HTML, Markdown и CBZ с локальной библиотекой и каталогами OPDS."),
            license_type=Gtk.License.GPL_3_0,
        )
        dialog.present()

    def show_manual(self, *_args):
        if self.manual_window is None:
            self.manual_window = translated(
                Adw.Window, transient_for=self, modal=False, destroy_with_parent=True,
                hide_on_close=True, title=_("Руководство пользователя"),
                default_width=760, default_height=650,
            )
            toolbar = Adw.ToolbarView()
            header = Adw.HeaderBar()
            self.manual_language_selector = translated_dropdown([
                _("Язык интерфейса"), "Русский", "English", "Deutsch", "Українська",
            ])
            accessible_label(self.manual_language_selector, _("Язык"))
            bind(self.manual_language_selector, tooltip_text=_("Язык"))
            self.manual_language_selector.connect("notify::selected", self.manual_language_changed)
            header.pack_end(self.manual_language_selector)
            toolbar.add_top_bar(header)
            self.manual_text_view = Gtk.TextView(
                editable=False, cursor_visible=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                left_margin=24, right_margin=24, top_margin=20, bottom_margin=24,
                vexpand=True,
            )
            self.manual_text_view.add_css_class("reader-text")
            # All four guides use left-to-right text, independently of the UI.
            self.manual_text_view.set_direction(Gtk.TextDirection.LTR)
            accessible_label(self.manual_text_view, _("Руководство пользователя"))
            toolbar.set_content(Gtk.ScrolledWindow(child=self.manual_text_view, vexpand=True))
            self.manual_window.set_content(toolbar)
        self.refresh_manual_content()
        self.manual_window.present()

    def manual_language_changed(self, *_args):
        if self._syncing_preferences:
            return
        selected = self.manual_language_selector.get_selected()
        self._manual_language_override = MANUAL_LANGUAGES[selected - 1] if 1 <= selected <= len(MANUAL_LANGUAGES) else None
        self.refresh_manual_content()

    def refresh_manual_content(self):
        if self.manual_text_view is None:
            return
        language = manual_language(self._manual_language_override or self._resolved_interface_language)
        if language == self._manual_text_language:
            return
        try:
            text = manual_text(language)
        except (OSError, UnicodeError) as error:
            self.show_error(_("Не удалось выполнить действие"), error)
            return
        self.manual_text_view.get_buffer().set_text(text)
        self._manual_text_language = language

    def show_shortcuts(self, *_args):
        if self.shortcuts_window is None:
            # GtkShortcutsWindow owns an internal stack; its public GtkBuildable
            # interface routes sections into that stack on all supported GTK4s.
            groups = dict.fromkeys(item.group for item in SHORTCUTS)
            fragments = []
            titles = []
            for index, group in enumerate(groups):
                fragments.append(f'<child><object class="GtkShortcutsGroup" id="group{index}">')
                titles.append((f"group{index}", group))
                for number, shortcut in enumerate(SHORTCUTS):
                    if shortcut.group != group:
                        continue
                    fragments.append(
                        f'<child><object class="GtkShortcutsShortcut" id="shortcut{number}">'
                        f'<property name="accelerator">{escape(shortcut.accelerator)}</property>'
                        '</object></child>'
                    )
                    titles.append((f"shortcut{number}", shortcut.title))
                if group == READING:
                    for number, shortcut in enumerate(NAVIGATION_SHORTCUTS):
                        fragments.append(
                            f'<child><object class="GtkShortcutsShortcut" id="navigation{number}">'
                            f'<property name="accelerator">{escape(shortcut.accelerator)}</property>'
                            '</object></child>'
                        )
                        titles.append((f"navigation{number}", shortcut.title))
                fragments.append('</object></child>')
            builder = Gtk.Builder.new_from_string(
                '<interface><object class="GtkShortcutsWindow" id="shortcuts">'
                '<child><object class="GtkShortcutsSection">'
                '<property name="section-name">reader</property>'
                + ''.join(fragments) + '</object></child></object></interface>', -1,
            )
            self.shortcuts_window = bind(builder.get_object("shortcuts"), title=_("Горячие клавиши"))
            self._shortcut_widgets = {
                shortcut.action: builder.get_object(f"shortcut{number}")
                for number, shortcut in enumerate(SHORTCUTS)
            }
            self._shortcut_groups = {
                group: builder.get_object(f"group{index}") for index, group in enumerate(groups)
            }
            self._navigation_shortcut_widgets = tuple(
                (shortcut, builder.get_object(f"navigation{number}"))
                for number, shortcut in enumerate(NAVIGATION_SHORTCUTS)
            )
            for identifier, title in titles:
                bind(builder.get_object(identifier), title=_(title))
            self.shortcuts_window.set_transient_for(self)
            self.shortcuts_window.set_modal(True)
            self.shortcuts_window.set_hide_on_close(True)
            self.shortcuts_window.set_destroy_with_parent(True)
        self.shortcut_bindings_changed()
        self.shortcuts_window.present()

    def set_status(self, message, announce=True):
        if not self._closing:
            changed = str(message) != self.status.get_text()
            bind(self.status, label=message)
            bind(self.status, tooltip_text=message)
            bind(self.spinner, tooltip_text=message)
            if announce and message and (changed or self._status_toast is None):
                if self._status_toast is not None:
                    self._status_toast.dismiss()
                toast = bind(Adw.Toast.new(str(message)), title=message)
                toast.set_timeout(4)
                def dismissed(item):
                    if self._status_toast is item:
                        self._status_toast = None
                toast.connect("dismissed", dismissed)
                self._status_toast = toast
                self.toast_overlay.add_toast(toast)

    def show_error(self, title, error):
        if self._closing:
            return
        self.set_status(title)
        dialog = translated(Gtk.MessageDialog,
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE,
            text=title,
            secondary_text=str(error),
        )
        dialog.connect("response", lambda item, _response: item.destroy())
        dialog.present()


    def page_changed(self, _stack, _property):
        self.cancel_mouse_gesture()
        self.reading_context_popover.popdown()
        page = self.stack.get_visible_child_name()
        if not self._internal_navigation:
            self._navigation_serial += 1
        if self._last_page == "reader" and page != "reader":
            self._speech_intent += 1
            self.save_progress()
            self.speech.pause()
        if page == "library":
            self.refresh_library()
        self._last_page = page
        self.search_popover.popdown()
        self.update_header()

    def update_header(self):
        page = self.stack.get_visible_child_name() or "library"
        self.header_titles.set_visible_child_name(page)
        self.search_stack.set_visible_child_name(page)
        self.reader_navigation.set_visible(page == "reader")
        self.reader_actions.set_visible(page == "reader")
        self.reader_tools_button.set_visible(self.is_paged())
        self.catalog_navigation.set_visible(page == "catalogs")
        self.search_button.set_sensitive(
            page == "library" or (page == "reader" and self.book is not None)
            or (page == "catalogs" and self.catalog_page is not None and bool(self.catalog_page.search_url)))
        self.reader_navigation.set_sensitive(self.book is not None)
        self.reader_actions.set_sensitive(self.book is not None)
        self.update_text_size_controls()
        self.update_page_number()
        self.update_accessibility_state()
        self.library_controls.set_visible(page == "library")
        self.sync_immersive()

    def open_search(self):
        if not self.search_button.get_sensitive():
            return
        self.search_popover.popup()
        entry = {"library": self.library_search, "reader": self.reader_search,
                 "catalogs": self.catalog_search}[self.stack.get_visible_child_name()]
        entry.grab_focus()

    def open_accessibility_menu(self):
        self.toolbar_view.set_reveal_top_bars(True)
        if self._accessibility_popup_tick is not None:
            return

        def popup(button, _clock):
            # A hidden fullscreen header needs a layout frame before the
            # popover can be positioned against its button.
            if self._closing:
                self._accessibility_popup_tick = None
                return GLib.SOURCE_REMOVE
            if not button.get_mapped() or button.get_width() <= 0:
                return GLib.SOURCE_CONTINUE
            self._accessibility_popup_tick = None
            button.popup()
            self.sync_immersive()
            return GLib.SOURCE_REMOVE

        self._accessibility_popup_tick = self.accessibility_button.add_tick_callback(popup)

    def complete_book(self, record, book, navigation):
        self.refresh_library()
        if navigation == self._navigation_serial:
            self.show_book(record, book)
        else:
            self.set_status(_("Книга готова к чтению в библиотеке."))


    @staticmethod
    def clear_list(widget):
        while widget.get_first_child():
            widget.remove(widget.get_first_child())


    def choose_files(self, _button=None):
        if self._portal_chooser is not None:
            self._portal_chooser.cancel()
        if self._native_chooser is not None:
            self._native_chooser.destroy()
            self._native_chooser = None
        self._portal_chooser = PortalFileChooser(self, self.import_paths, self.choose_native_files)
        self._portal_chooser.open()

    def choose_native_files(self):
        if self._closing:
            return
        chooser = translated(Gtk.FileChooserNative,
            title=_("Открыть книги"),
            transient_for=self,
            action=Gtk.FileChooserAction.OPEN,
            accept_label=_("Добавить"),
            cancel_label=_("Отмена"),
        )
        self._native_chooser = chooser
        chooser.set_select_multiple(True)
        book_filter = Gtk.FileFilter()
        bind(book_filter, name=_(BOOK_FILTER_NAME))
        for extension in BOOK_EXTENSIONS:
            book_filter.add_pattern(f"*.{extension}")
            book_filter.add_pattern(f"*.{extension.upper()}")
        chooser.add_filter(book_filter)

        def selected(dialog, response):
            if response == Gtk.ResponseType.ACCEPT and not self._closing:
                items = dialog.get_files()
                paths = [items.get_item(i).get_path() for i in range(items.get_n_items())]
                self.import_paths([path for path in paths if path])
            dialog.destroy()
            if self._native_chooser is dialog:
                self._native_chooser = None

        chooser.connect("response", selected)
        chooser.show()

    def import_paths(self, paths):
        paths = list(paths)
        if not paths:
            return
        token, serial, navigation = self.begin_book_operation()
        def imported(result):
            books, errors = result
            self.refresh_library()
            if books and serial == self._book_serial:
                item, book, duplicate = books[-1]
                if duplicate:
                    self.confirm_duplicate(item, book, navigation)
                else:
                    self.complete_book(item, book, navigation)
            if errors:
                failed_paths = [path for path, _error in errors]
                error = errors[0][1] if len(errors) == 1 else ValueError("\n".join(
                    f"{Path(path).name}: {failure}" for path, failure in errors))
                self._show_task_error(_("Некоторые книги не удалось открыть"), error,
                                      retry=lambda: self.import_paths(failed_paths))

        self.run_task(lambda: import_books(self.library, paths, token), imported,
                      _("Добавление книг: {count}…").format(count=len(paths)),
                      relevant=lambda: serial == self._book_serial, on_stale=self.refresh_library,
                      on_cancel=self.refresh_library, token=token, retry=lambda: self.import_paths(paths))


    def build_reader(self):
        self.reader_navigation = Gtk.Box(spacing=2)
        self.toc_button = translated(Gtk.ToggleButton, icon_name="view-list-symbolic", tooltip_text=_("Оглавление"))
        accessible_label(self.toc_button, _("Оглавление"))
        self.reader_navigation.append(self.toc_button)
        self.chapter_step_controls = Gtk.Box(spacing=0)
        self.previous_button = button("‹", lambda _b: self.change_chapter(-1), _("Предыдущая глава"))
        self.next_button = button("›", lambda _b: self.change_chapter(1), _("Следующая глава"))
        self.chapter_step_controls.append(self.previous_button)
        self.chapter_step_controls.append(self.next_button)
        self.reader_navigation.append(self.chapter_step_controls)
        self.font_size = Gtk.SpinButton.new_with_range(FONT_SIZE_MIN, FONT_SIZE_MAX, 1)
        self.font_size.set_value(self.library.settings.get("font_size", 20))
        bind(self.font_size, tooltip_text=_("Размер шрифта"))
        self.font_size.connect("value-changed", self.style_changed)
        self.font_size.connect("value-changed", lambda *_args: self.update_text_size_controls())
        tools = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.document_toolbar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.document_toolbar.append(label(_("Масштаб страницы, %")))
        self.document_zoom = Gtk.SpinButton.new_with_range(25, 300, 25)
        self.document_zoom.set_value(100)
        bind(self.document_zoom, tooltip_text=_("100% — по ширине окна; вёрстка PDF, DjVu и CBZ сохраняется"))
        accessible_label(self.document_zoom, _("Масштаб страницы, %"))
        self.document_zoom.connect("value-changed", self.document_zoom_changed)
        self.document_zoom.connect("value-changed", lambda *_args: self.update_text_size_controls())
        self.document_toolbar.append(self.document_zoom)
        self.document_retry = button(_("Повторить"), lambda _b: self.render_document_page(self.current_offset()),
                                     compact=True, icon="view-refresh-symbolic")
        self.document_retry.set_visible(False)
        self.reader_navigation.append(self.document_retry)
        self.document_toolbar.set_visible(False)
        tools.append(self.document_toolbar)

        searchbar = Gtk.Box(spacing=8)
        self.reader_search = translated(Gtk.SearchEntry, placeholder_text=_("Поиск по всей книге"), hexpand=True)
        searchbar.append(self.reader_search)
        searchbar.append(button(_("Найти"), lambda _b: self.find_text(), compact=True))
        searchbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        searchbox.append(searchbar)
        self.build_book_search_controls(searchbox)
        self.search_stack.add_named(searchbox, "reader")
        self.bookmarks_button = translated(Gtk.MenuButton, icon_name="user-bookmarks-symbolic", tooltip_text=_("Закладки"))
        accessible_label(self.bookmarks_button, _("Закладки"))
        heading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.reader_title = label(_("Откройте книгу в библиотеке."), "heading")
        self.reader_title.set_max_width_chars(30)
        self.reader_title.set_ellipsize(Pango.EllipsizeMode.END)
        heading.append(self.reader_title)
        self.reading_progress = label("", "dim-label")
        self.reading_progress.set_max_width_chars(34)
        self.reading_progress.set_ellipsize(Pango.EllipsizeMode.END)
        heading.append(self.reading_progress)
        self.header_titles.add_named(heading, "reader")
        self.reader_split = Adw.OverlaySplitView(vexpand=True)
        self.reader_split.set_min_sidebar_width(160)
        self.reader_split.set_max_sidebar_width(220)
        self.reader_split.set_sidebar_width_fraction(0.19)
        self.reader_split.set_sidebar(self.build_sidebar())
        self.reader_split.set_show_sidebar(True)
        self.reader_split.bind_property(
            "show-sidebar", self.toc_button, "active",
            GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE,
        )
        breakpoint = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 900sp"))
        breakpoint.add_setter(self.reader_split, "collapsed", True)
        breakpoint.add_setter(self.reader_split, "show-sidebar", False)
        self.add_breakpoint(breakpoint)
        self.text_view = Gtk.TextView(
            editable=False,
            cursor_visible=True,
            wrap_mode=Gtk.WrapMode.WORD_CHAR,
            left_margin=36,
            right_margin=36,
            top_margin=24,
            bottom_margin=48,
            pixels_below_lines=8,
        )
        # The page's paragraphs follow their own Unicode direction, independent
        # of the language selected for toolbars and preferences.
        self.text_view.set_direction(Gtk.TextDirection.LTR)
        accessible_label(self.text_view, _("Страница книги"))
        self.text_view.add_css_class("reader-text")
        self.buffer = self.text_view.get_buffer()
        self._reader_direction_tags = {
            "ltr": self.buffer.create_tag("reader-ltr", direction=Gtk.TextDirection.LTR,
                                          justification=Gtk.Justification.LEFT),
            "rtl": self.buffer.create_tag("reader-rtl", direction=Gtk.TextDirection.RTL,
                                          justification=Gtk.Justification.RIGHT),
        }
        self.search_tag = self.buffer.create_tag("search", background="#f3d775", foreground="#222222")
        self.speech_tag = self.buffer.create_tag("speech", background="#d4e4b8", foreground="#202820")
        self.reader_scroll = Gtk.ScrolledWindow(has_frame=False)
        self.reader_scroll.set_child(self.text_view)
        self.init_illustration_ui()
        self.document_picture = Gtk.Picture(can_shrink=False, halign=Gtk.Align.CENTER, valign=Gtk.Align.START)
        bind(self.document_picture, alternative_text=_("Страница документа"))
        self.document_canvas = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.document_canvas.set_focusable(True)
        accessible_label(self.document_canvas, _("Страница документа"))
        self.document_canvas.add_css_class("document-canvas")
        self.document_notice = margins(label(_("Загрузка страницы…"), wrap=True), 24)
        self.document_notice.add_css_class("document-notice")
        self.document_canvas.append(self.document_notice)
        self.document_canvas.append(self.document_picture)
        self.reader_scroll.add_tick_callback(self.document_view_tick)
        self.reader_scroll.add_tick_callback(self.reader_layout_tick)
        self.reader_scroll.get_vadjustment().connect("value-changed", self.scroll_changed)
        scroll_input = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll_input.connect("scroll", self.manual_scroll)
        self.reader_scroll.add_controller(scroll_input)
        click = Gtk.GestureClick()
        click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click.connect("pressed", self.reading_pointer_pressed)
        self.reader_scroll.add_controller(click)
        self.install_mouse_gestures()
        self.reader_overlay = Gtk.Overlay(child=self.reader_scroll)
        self.init_page_numbers(self.reader_overlay)
        self.reader_split.set_content(self.reader_overlay)
        self.document_text_view = Gtk.TextView(buffer=self.buffer, editable=False, cursor_visible=True,
                                         wrap_mode=Gtk.WrapMode.WORD_CHAR, left_margin=16, right_margin=16,
                                         top_margin=8, bottom_margin=8)
        self.document_text_view.set_direction(Gtk.TextDirection.LTR)
        accessible_label(self.document_text_view, _("Текст страницы · поиск и озвучка"))
        self.document_text_view.add_css_class("reader-text")
        text_scroll = Gtk.ScrolledWindow(min_content_height=120, max_content_height=240,
                                         propagate_natural_height=True)
        text_scroll.set_child(self.document_text_view)
        self.document_text_expander = translated(Gtk.Expander, label=_("Текст страницы · поиск и озвучка"))
        self.document_text_expander.set_child(text_scroll)
        self.document_text_expander.set_visible(False)
        tools.append(self.document_text_expander)
        self.speech_status = label(_("Озвучка через Piper"), "dim-label", True)
        self.speech_status.set_max_width_chars(36)
        self.reader_tools_popover = Gtk.Popover(child=margins(tools, 12))
        self.reader_tools_popover.set_size_request(300, -1)
        self.reader_tools_button = translated(Gtk.MenuButton, icon_name="view-more-symbolic", tooltip_text=_("Страница книги"))
        accessible_label(self.reader_tools_button, _("Страница книги"))
        self.reader_tools_button.set_popover(self.reader_tools_popover)
        self.speech_play = button(_("Озвучить"), self.toggle_speech, tooltip=_("Озвучить"))
        self.reader_actions = Gtk.Box(spacing=2)
        self.text_size_actions = Gtk.Box()
        self.text_size_actions.add_css_class("linked")
        self.text_size_decrease = button(_("Уменьшить текст"), lambda _b: self.adjust_text_size(-1),
                                         compact=True, icon="zoom-out-symbolic")
        self.text_size_reset = button(_("Стандартный размер текста"), lambda _b: self.adjust_text_size(0),
                                      compact=True, icon="zoom-original-symbolic")
        self.text_size_increase = button(_("Увеличить текст"), lambda _b: self.adjust_text_size(1),
                                         compact=True, icon="zoom-in-symbolic")
        for control in (self.text_size_decrease, self.text_size_reset, self.text_size_increase):
            self.text_size_actions.append(control)
        # A single size group is placed in the accessibility menu below.
        # Avoid separate toolbar and narrow-window copies of the same actions.
        self.reader_actions.append(self.bookmarks_button)
        self.reader_actions.append(self.reader_tools_button)
        compact = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 680sp"))
        compact.add_setter(self.reader_split, "collapsed", True)
        compact.add_setter(self.reader_split, "show-sidebar", False)
        compact.add_setter(self.reader_title, "max-width-chars", 12)
        compact.add_setter(self.reading_progress, "max-width-chars", 16)
        self.add_breakpoint(compact)
        self.refresh_bookmarks()
        return self.reader_split

    def adjust_text_size(self, direction):
        if self.book is None:
            return
        paged = self.is_paged()
        control = self.document_zoom if paged else self.font_size
        default, step = (100, 25) if paged else (20, 2)
        control.set_value(default if direction == 0 else control.get_value() + direction * step)
        self.update_text_size_controls()

    def update_text_size_controls(self):
        if not hasattr(self, "text_size_increase"):
            return
        control = self.document_zoom if self.is_paged() else self.font_size
        value = control.get_value()
        adjustment = control.get_adjustment()
        opened = self.book is not None
        self.text_size_decrease.set_sensitive(opened and value > adjustment.get_lower())
        self.text_size_increase.set_sensitive(opened and value < adjustment.get_upper())
        self.text_size_reset.set_sensitive(opened and value != (100 if self.is_paged() else 20))

    def install_mouse_gestures(self):
        menu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.copy_context_button = button(_("Копировать"), self.copy_reader_text)
        self.select_context_button = button(_("Выделить всё"), self.select_reader_text)
        for item in (self.copy_context_button, self.select_context_button):
            item.add_css_class("flat")
            menu.append(item)
        self.reading_context_popover = Gtk.Popover(child=margins(menu, 4), has_arrow=False)
        self.reading_context_popover.set_parent(self.reader_scroll)
        # Delay the right-click menu until release: TextView's native popup on
        # press would grab the pointer before a right-drag can be recognized.
        self.gesture_click = Gtk.GestureClick(button=3)
        self.gesture_drag = Gtk.GestureDrag(button=3)
        for gesture in (self.gesture_drag, self.gesture_click):
            gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            self.reader_scroll.add_controller(gesture)
            gesture.connect("cancel", lambda *_args: self.cancel_mouse_gesture())
        self.gesture_click.group(self.gesture_drag)
        self.gesture_click.connect("pressed", lambda gesture, _count, x, y: self.gesture_begin(gesture, x, y))
        self.gesture_click.connect("released", self.gesture_click_released)
        self.gesture_drag.connect("drag-begin", self.gesture_begin)
        self.gesture_drag.connect("drag-update", self.gesture_update)
        self.gesture_drag.connect("drag-end", self.gesture_end)

    def gesture_begin(self, gesture, x, y):
        if (not math.isfinite(x) or not math.isfinite(y)
                or self._closing or self.book is None or self.record is None
                or self.stack.get_visible_child_name() != "reader"
                or not self.library.settings["mouse_gestures"]):
            return False
        if not self._mouse_active:
            self._mouse_origin = (x, y)
            self._mouse_distance = 0
            self._mouse_context = (self.record["id"], self.chapter_index, self._navigation_serial)
            self.mouse_navigation.begin(x, y)
            self._mouse_active = True
            self.reading_context_popover.popdown()
        if gesture is not None:
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        return True

    def gesture_update(self, _gesture, dx, dy):
        if not math.isfinite(dx) or not math.isfinite(dy):
            self.cancel_mouse_gesture()
            return
        if self._mouse_active:
            self._mouse_distance = max(self._mouse_distance, math.hypot(dx, dy))
            self.mouse_navigation.update(self._mouse_origin[0] + dx, self._mouse_origin[1] + dy)

    def gesture_click_released(self, gesture, _count, x, y):
        self.gesture_end(gesture, x - self._mouse_origin[0], y - self._mouse_origin[1])

    def gesture_end(self, _gesture, dx, dy):
        if not self._mouse_active:
            return 0
        self.gesture_update(_gesture, dx, dy)
        if not self._mouse_active:
            return 0
        x, y = self._mouse_origin[0] + dx, self._mouse_origin[1] + dy
        context = (self.record["id"], self.chapter_index, self._navigation_serial) if self.record else None
        valid = (not self._closing and self.book is not None and context == self._mouse_context
                 and self.stack.get_visible_child_name() == "reader"
                 and self.library.settings["mouse_gestures"])
        delta = self.mouse_navigation.finish(x, y) if valid else 0
        distance = self._mouse_distance
        self.cancel_mouse_gesture()
        if valid:
            if delta:
                self.change_chapter(delta)
            elif distance < 12:
                self.show_reader_context_menu(x, y)
        return delta

    def cancel_mouse_gesture(self):
        self.mouse_navigation.cancel()
        self._mouse_active = False
        self._mouse_context = None

    def show_reader_context_menu(self, x, y):
        self.copy_context_button.set_sensitive(bool(self.buffer.get_selection_bounds()))
        self.select_context_button.set_sensitive(self.buffer.get_char_count() > 0)
        rectangle = Gdk.Rectangle()
        rectangle.x, rectangle.y, rectangle.width, rectangle.height = round(x), round(y), 1, 1
        self.reading_context_popover.set_pointing_to(rectangle)
        self.reading_context_popover.popup()

    def copy_reader_text(self, _button=None):
        self.buffer.copy_clipboard(self.get_clipboard())
        self.reading_context_popover.popdown()

    def select_reader_text(self, _button=None):
        self.manual_scroll()
        self.buffer.select_range(self.buffer.get_start_iter(), self.buffer.get_end_iter())
        self.reading_context_popover.popdown()

    def build_preferences(self):
        window = translated(Adw.PreferencesWindow, transient_for=self, title=_("Настройки"), hide_on_close=True)
        window.set_direction(self.get_direction())
        window.set_default_size(640, 660)
        page = translated(Adw.PreferencesPage, title=_("Настройки"), icon_name="preferences-system-symbolic")
        self.general_preferences_page = page
        window.add(page)
        interface = translated(Adw.PreferencesGroup, title=_("Интерфейс"),
            description=_("Системные шрифты, масштаб и оконные кнопки задаёт рабочая среда. Виджеты используют libadwaita."))
        page.add(interface)
        self.interface_selector = translated_dropdown([_("Как в системе"), _("Светлый"), _("Тёмный")])
        self.interface_selector.set_selected(("system", "light", "dark").index(self.library.settings["interface_theme"]))
        self.interface_language_selector = translated_dropdown(
            [_("Системный"), *(name for _code, name in LANGUAGE_CHOICES)])
        self.interface_language_selector.set_selected(
            INTERFACE_LANGUAGE_CODES.index(self._startup_interface_language))
        self.reopen_last_book_switch = Gtk.Switch(active=self.library.settings["reopen_last_book"])
        self.auto_hide_header_switch = Gtk.Switch(active=self.library.settings["auto_hide_header"])

        def row(group, title, widget, subtitle=None):
            item = translated(Adw.ActionRow, title=title)
            if subtitle:
                bind(item, subtitle=subtitle)
            widget.set_valign(Gtk.Align.CENTER)
            accessible_label(widget, title)
            item.add_suffix(widget)
            item.set_activatable_widget(widget)
            group.add(item)

        row(interface, _("Язык интерфейса"), self.interface_language_selector)
        row(interface, _("Оформление окна"), self.interface_selector)
        row(interface, _("Открывать последнюю книгу при запуске"), self.reopen_last_book_switch)
        reading = translated(Adw.PreferencesGroup, title=_("Страница книги"),
            description=_("Цвета и шрифты страницы настраиваются отдельно от интерфейса."))
        page.add(reading)
        self.theme_selector = translated_dropdown([_("Как в системе"), _("Дневной"), _("Сепия"), _("Ночной")])
        themes = ("system", "light", "sepia", "dark")
        self.theme_selector.set_selected(themes.index(self.library.settings.get("theme", "system")))
        self.font_keys = list(FONT_FAMILIES)
        self.font_selector = translated_dropdown([_(FONT_FAMILIES[key][0]) for key in self.font_keys])
        self.font_selector.set_selected(self.font_keys.index(self.library.settings.get("font_family", "notoserif")))
        self.brightness = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 30, 100, 1)
        self.brightness.set_size_request(180, -1)
        self.brightness.set_digits(0)
        self.brightness.set_value(self.library.settings.get("brightness", 1.0) * 100)
        bind(self.brightness, tooltip_text=_("Приглушение цветов страницы; яркость монитора не меняется."))
        self.reader_width = Gtk.SpinButton.new_with_range(READER_WIDTH_MIN, READER_WIDTH_MAX, 40)
        self.reader_width.set_value(self.library.settings["reader_width"])
        row(reading, _("Фон страницы"), self.theme_selector)
        row(reading, _("Автоматически скрывать панель в полном экране"), self.auto_hide_header_switch)
        row(reading, _("Шрифт книги"), self.font_selector)
        row(reading, _("Размер текста"), self.font_size)
        row(reading, _("Максимальная ширина текста"), self.reader_width,
            _("В пикселях; на широком окне текст располагается по центру."))
        row(reading, _("Яркость страницы, %"), self.brightness,
            _("PDF, DjVu и CBZ сохраняют исходные шрифты и цвета; размер меняется масштабом."))
        accessibility = translated(Adw.PreferencesGroup, title=_("Специальные возможности"))
        page.add(accessibility)
        self.high_contrast_switch = Gtk.Switch(active=self.library.settings["high_contrast"])
        self.bold_text_switch = Gtk.Switch(active=self.library.settings["bold_text"])
        self.line_spacing = Gtk.SpinButton.new_with_range(LINE_SPACING_MIN, LINE_SPACING_MAX, 0.1)
        self.line_spacing.set_digits(1)
        self.line_spacing.set_value(self.library.settings["line_spacing"])
        self.mouse_gestures_switch = Gtk.Switch(active=self.library.settings["mouse_gestures"])
        bind(self.mouse_gestures_switch, tooltip_text=_("Удерживайте правую кнопку мыши и проведите влево или вправо для перехода между главами или страницами."))
        row(accessibility, _("Высокая контрастность"), self.high_contrast_switch)
        row(accessibility, _("Полужирный текст"), self.bold_text_switch)
        row(accessibility, _("Межстрочный интервал"), self.line_spacing)
        row(accessibility, _("Режим для слабовидящих"), button(_("Применить"), self.low_vision_preset))
        row(accessibility, _("Жесты мышью"), self.mouse_gestures_switch)
        speech = translated(Adw.PreferencesGroup, title=_("Озвучка"))
        page.add(speech)
        self.speech_language = translated_dropdown(
            [_("По тексту главы"), *(name for _code, name in SPEECH_LANGUAGE_CHOICES)])
        self.speech_language.set_selected(SPEECH_LANGUAGE_CODES.index(self.library.settings.get("speech_language", "auto")))
        self.speech_rate = Gtk.SpinButton.new_with_range(44, 250, 10)
        self.speech_rate.set_value(self.library.settings.get("speech_rate", 180) / 1.8)
        row(speech, _("Язык"), self.speech_language)
        row(speech, _("Скорость, %"), self.speech_rate)
        self.build_voice_preferences(speech, row)
        self.interface_selector.connect("notify::selected", self.interface_style_changed)
        self.interface_language_selector.connect("notify::selected", self.interface_language_changed)
        self.theme_selector.connect("notify::selected", self.style_changed)
        self.font_selector.connect("notify::selected", self.style_changed)
        self.brightness.connect("value-changed", self.style_changed)
        self.reader_width.connect("value-changed", self.style_changed)
        self.speech_language.connect("notify::selected", self.speech_options_changed)
        self.speech_rate.connect("value-changed", self.speech_options_changed)
        self.high_contrast_switch.connect("notify::active", self.accessibility_changed)
        self.bold_text_switch.connect("notify::active", self.accessibility_changed)
        self.mouse_gestures_switch.connect("notify::active", self.accessibility_changed)
        self.line_spacing.connect("value-changed", self.accessibility_changed)
        self.reopen_last_book_switch.connect("notify::active", self.reading_preferences_changed)
        self.auto_hide_header_switch.connect("notify::active", self.reading_preferences_changed)
        self.build_shortcut_preferences(window)
        return window

    def reading_preferences_changed(self, *_args):
        if not self._syncing_preferences:
            self.save_settings({"reopen_last_book": self.reopen_last_book_switch.get_active(),
                                "auto_hide_header": self.auto_hide_header_switch.get_active()})
            self.sync_immersive()

    def accessibility_changed(self, *_args):
        if self._syncing_preferences:
            return
        offset = self.current_offset() if self.book else None
        if not self.save_settings({
            "high_contrast": self.high_contrast_switch.get_active(),
            "bold_text": self.bold_text_switch.get_active(),
            "line_spacing": self.line_spacing.get_value(),
            "mouse_gestures": self.mouse_gestures_switch.get_active(),
        }):
            return
        if not self.library.settings["mouse_gestures"]:
            self.cancel_mouse_gesture()
        self.refresh_reader_style()
        self.sync_immersive()
        if offset is not None:
            self.restore_position(offset)

    def low_vision_preset(self, _button=None):
        offset = self.current_offset() if self.book else None
        if not self.save_settings({"font_size": 32, "font_family": "notosans", "reader_width": 1000,
                                   "high_contrast": True, "bold_text": True, "line_spacing": 1.5}):
            return
        self._syncing_preferences = True
        try:
            self.font_size.set_value(32)
            self.font_selector.set_selected(self.font_keys.index("notosans"))
            self.reader_width.set_value(1000)
            self.high_contrast_switch.set_active(True)
            self.bold_text_switch.set_active(True)
            self.line_spacing.set_value(1.5)
        finally:
            self._syncing_preferences = False
        self.refresh_reader_style()
        self.sync_immersive()
        if self.is_paged():
            self.document_zoom.set_value(max(150, self.document_zoom.get_value()))
        if offset is not None:
            self.restore_position(offset)

    def interface_language_changed(self, *_args):
        if self._syncing_preferences:
            return
        selected = INTERFACE_LANGUAGE_CODES[self.interface_language_selector.get_selected()]
        if self.save_settings({"interface_language": selected}):
            self.apply_interface_language(selected)

    def apply_interface_language(self, choice):
        """Translate the current UI without rebuilding the reader or its state."""
        offset = self.current_offset() if self.book else None
        selectors = (
            self.interface_language_selector, self.interface_selector,
            self.theme_selector, self.font_selector,
            self.speech_language, self.catalog_selector,
            self.library_filter, self.library_sort,
            self.shortcut_mode_selector,
            self.speech_voice,
        )
        if self.manual_language_selector is not None:
            selectors += (self.manual_language_selector,)
        selectors += (self.accessibility_speech_language,)
        selected = [(widget, widget.get_selected()) for widget in selectors]
        syncing, switching, restoring = self._syncing_preferences, self._chapter_switch, self._restoring
        self._syncing_preferences = self._chapter_switch = self._restoring = True
        try:
            self._resolved_interface_language = configure_language(choice)
            rtl = is_rtl_language(self._resolved_interface_language)
            direction = Gtk.TextDirection.RTL if rtl else Gtk.TextDirection.LTR
            Gtk.Widget.set_default_direction(direction)
            self.set_direction(direction)
            self.preferences_window.set_direction(direction)
            # Already-open application dialogs follow the new direction too.
            windows = Gtk.Window.get_toplevels()
            for index in range(windows.get_n_items()):
                window = windows.get_item(index)
                parent = window
                while parent is not None and parent is not self:
                    parent = parent.get_transient_for()
                if parent is self:
                    window.set_direction(direction)
            _translations.refresh(rtl=rtl)
            self.refresh_task_translations()
            for widget, index in selected:
                widget.set_selected(index)
        finally:
            self._syncing_preferences, self._chapter_switch, self._restoring = syncing, switching, restoring
        # The UI's new labels can change its allocation. Restore the same book
        # character/page fraction without touching text, search marks or audio.
        self.refresh_library()
        self.refresh_bookmarks()
        self.refresh_manual_content()
        self.shortcut_bindings_changed()
        self.refresh_voice_choices()
        if offset is not None and (not self.is_paged() or self._document_ready):
            self.restore_position(offset)

    def interface_style_changed(self, *_args):
        if self._syncing_preferences:
            return
        if self.save_settings({
            "interface_theme": ("system", "light", "dark")[self.interface_selector.get_selected()],
        }):
            self.apply_style()

    def apply_style(self):
        self.apply_interface_scheme()
        self.refresh_reader_style()

    def apply_interface_scheme(self):
        scheme = {
            "system": Adw.ColorScheme.DEFAULT,
            "light": Adw.ColorScheme.FORCE_LIGHT,
            "dark": Adw.ColorScheme.FORCE_DARK,
        }.get(self.library.settings.get("interface_theme"), Adw.ColorScheme.DEFAULT)
        if (scheme == Adw.ColorScheme.DEFAULT and self.desktop_appearance is not None
                and self.desktop_appearance.dark and not self.style_manager.get_system_supports_color_schemes()):
            scheme = Adw.ColorScheme.PREFER_DARK
        self.style_manager.set_color_scheme(scheme)

    def desktop_style_changed(self, _dark):
        if self._closing:
            return
        self.apply_interface_scheme()
        self.refresh_reader_style()

    def refresh_reader_style(self, *_args):
        if self._closing:
            return
        desktop_dark = self.desktop_appearance.dark if self.desktop_appearance else self.style_manager.get_dark()
        theme = reader_theme(self.library.settings.get("theme", "system"), desktop_dark)
        high_contrast = self.library.settings["high_contrast"]
        background, foreground = reader_colors(theme, self.library.settings.get("brightness", 1.0), high_contrast)
        size = max(FONT_SIZE_MIN, min(FONT_SIZE_MAX, int(self.library.settings.get("font_size", 20))))
        family = font_css(self.library.settings.get("font_family", "notoserif"))
        weight = 700 if self.library.settings["bold_text"] else 400
        # A scheme change can notify synchronously from apply_style(). Avoid
        # reparsing CSS and relaying out every paragraph twice for one action.
        native_contrast = self.style_manager.get_high_contrast()
        style_key = (background, foreground, size, family, weight,
                     self.library.settings["line_spacing"], high_contrast,
                     self.library.settings.get("brightness", 1.0), native_contrast)
        if style_key == self._reader_style_key:
            self.sync_day_night()
            return
        frame_css = (
            "window.reader-window { border: 1px solid currentColor; box-shadow: none; }\n"
            if native_contrast or high_contrast else
            "window.reader-window { border: 1px solid alpha(currentColor, 0.18); "
            "box-shadow: 0 2px 6px alpha(black, 0.12); }\n"
        )
        self.css.load_from_data(
            (frame_css +
            "window.reader-window.maximized, window.reader-window.fullscreen { border-width: 0; box-shadow: none; }\n" +
            # This provider belongs only to this process, including its dialogs.
            # rem follows the system font without compounding in nested menus;
            # the explicit reader-text rule below keeps book size independent.
            "window, popover { font-size: 1.15rem; }\n" +
            f"textview.reader-text {{ font-family: {family}; font-size: {size}px; font-weight: {weight}; color: {foreground}; background-color: {background}; }}\n"
            f"textview.reader-text text {{ color: {foreground}; background-color: {background}; }}\n"
            f".reader-surface {{ background-color: {background}; }}\n"
            f".reader-page-number {{ font-size: {max(13, min(size, 24))}px; font-weight: 600; "
            f"color: {foreground}; background-color: {background}; padding: 2px 10px; }}\n"
            ".document-canvas { background-color: #000000; }\n"
            ".document-notice { color: #ffffff; }").encode()
        )
        self._reader_style_key = style_key
        self.document_picture.set_opacity(1.0 if high_contrast else self.library.settings.get("brightness", 1.0))
        for view in (self.text_view, self.document_text_view):
            view.set_pixels_inside_wrap(round(size * (self.library.settings["line_spacing"] - 1)))
            view.set_pixels_below_lines(max(8, round(size * 0.4)))
        def tint(amount):
            return "#" + "".join(
                f"{round(int(background[index:index + 2], 16) * (1 - amount) + int(foreground[index:index + 2], 16) * amount):02x}"
                for index in (1, 3, 5)
            )
        for tag, amount in ((self.search_tag, 0.3), (self.speech_tag, 0.2)):
            tag.set_property("background", tint(amount))
            tag.set_property("foreground", foreground)
        self.sync_day_night()

    def style_changed(self, *_args):
        if self._syncing_preferences:
            return
        offset = self.current_offset() if self.book else 0
        if not self.save_settings({
            "font_size": self.font_size.get_value_as_int(),
            "theme": ("system", "light", "sepia", "dark")[self.theme_selector.get_selected()],
            "font_family": self.font_keys[self.font_selector.get_selected()],
            "brightness": self.brightness.get_value() / 100,
            "reader_width": self.reader_width.get_value_as_int(),
        }):
            return
        self.refresh_reader_style()
        if self.book:
            self.restore_position(offset)

    def speech_options_changed(self, *_args):
        if self._syncing_preferences:
            return
        language = SPEECH_LANGUAGE_CODES[self.speech_language.get_selected()]
        voice_id = self.library.settings.get("speech_voice", "auto")
        if language != self.library.settings["speech_language"]:
            voice_id = "auto"
        if not self.save_settings({
            "speech_language": language,
            "speech_rate": round(self.speech_rate.get_value() * 1.8),
            "speech_voice": voice_id,
        }):
            return
        self.refresh_voice_choices()
        self.apply_narration_options()

    def apply_narration_options(self):
        self._voice_selection_serial += 1
        self.stop_voice_preview()
        if self.speech.state in {"speaking", "paused"}:
            offset = self._speech_offset if self.is_paged() else self.current_offset()
            running = self.speech.state == "speaking"
            self.speech.stop()
            self._speech_offset = offset
            if running:
                self.start_speech(offset)

    def manual_scroll(self, *_args):
        self._speech_intent += 1
        if hasattr(self, "speech"):
            self.speech.pause()
        self._speech_offset = None
        if self.is_paged() and not self._document_ready:
            return False
        if self.is_paged():
            self.document_position.user_input(self.document_geometry(), self.visible_offset())
        self.cancel_restore()
        return False

    def start_speech(self, offset=None):
        if not self.book or not self.record:
            self.set_status(_("Сначала откройте книгу."))
            return
        self.stop_voice_preview()
        if not self.speech.available:
            # The user may have installed the optional engine since opening the app.
            self.speech.close()
            self.speech = SpeechReader(GLib.idle_add, self.speech_state, self.speech_range, self.speech_finished,
                                       voices=self.voice_manager)
        text = self.book.chapters[self.chapter_index].text
        if self.is_paged() and not self._document_ready:
            self.set_status(_("Повторите загрузку страницы.") if self.document_retry.get_visible() else _("Дождитесь загрузки страницы."))
            return
        if self.is_paged() and not text.strip():
            self.set_status(_("На этой странице нет доступного текста для озвучки. Распознавание сканов пока не поддерживается."))
            return
        position = (0 if self.is_paged() else self.current_offset()) if offset is None else offset
        if position >= len(text):
            position = 0
        self._speech_offset = position
        self._speech_book = (self.record["id"], self.chapter_index)
        self._speech_completion_intent = self._speech_intent
        self.speech.start(text, position, self.library.settings["speech_language"], self.library.settings["speech_rate"],
                          voice_id=self.library.settings.get("speech_voice", "auto"))

    def toggle_speech(self, _button=None):
        self.stop_voice_preview()
        if self.speech.state == "speaking":
            self._speech_intent += 1
            self.speech.pause()
        elif self.speech.state == "paused" and self._speech_offset is not None:
            self._speech_completion_intent = self._speech_intent
            self.speech.resume()
        else:
            self.start_speech(self._speech_offset)

    def stop_speech(self, _button=None):
        self._speech_intent += 1
        self.save_progress()
        self.speech.stop()
        self._speech_offset = None
        self.buffer.remove_tag(self.speech_tag, self.buffer.get_start_iter(), self.buffer.get_end_iter())

    def speech_state(self, state, message):
        if self._closing:
            return
        speech_label = (_("Пауза") if state == "speaking" else _("Продолжить")
                        if state == "paused" and self._speech_offset is not None else _("Озвучить"))
        button_content(self.speech_play, speech_label)
        bind(self.speech_play, tooltip_text=speech_label)
        accessible_label(self.speech_play, speech_label)
        bind(self.speech_status, label=message or {
            "idle": _("Готово к озвучке"), "speaking": _("Идёт озвучка текущей главы"), "paused": _("Озвучка приостановлена"),
            "unavailable": _("Piper не установлен. Инструкция доступна в руководстве."),
        }.get(state, ""))
        if message and state in {"error", "unavailable"}:
            self.set_status(message)

    def speech_range(self, start, end):
        if self._closing or not self.record or getattr(self, "_speech_book", None) != (self.record["id"], self.chapter_index):
            return
        if not self.is_paged():
            self.cancel_restore()
        self._speech_offset = start
        if self.stack.get_visible_child_name() != "reader":
            self.save_progress()
            return
        begin = self.reader_iter_at_offset(start, after_images=True)
        finish = self.reader_iter_at_offset(end)
        self.buffer.remove_tag(self.speech_tag, self.buffer.get_start_iter(), self.buffer.get_end_iter())
        self.buffer.apply_tag(self.speech_tag, begin, finish)
        self.buffer.place_cursor(begin)
        if self.is_paged():
            self.document_text_expander.set_expanded(True)
        text_view = self.document_text_view if self.is_paged() else self.text_view
        text_view.scroll_to_mark(self.buffer.get_insert(), 0.1, True, 0, 0.2)
        self.update_progress_label(self.current_offset())
        self.save_progress()

    def speech_finished(self):
        if self._closing or not self.book or not self.record or getattr(self, "_speech_book", None) != (self.record["id"], self.chapter_index):
            return
        if self._speech_completion_intent != self._speech_intent:
            # A completed worker may already have queued this callback when
            # the reader manually scrolls or pauses. Do not overwrite that
            # position or start another chapter after the user's action.
            return
        self._speech_offset = len(self.book.chapters[self.chapter_index].text)
        self.save_progress()
        self.update_progress_label(self.current_offset())
        if self.stack.get_visible_child_name() != "reader":
            return
        if self.chapter_index + 1 < len(self.book.chapters):
            self.display_chapter(self.chapter_index + 1, autoplay=True)
        else:
            self.set_status(_("Озвучка книги завершена."))

    def safe_save(self):
        try:
            self.library.save()
        except OSError as error:
            self.show_error(_("Не удалось сохранить библиотеку"), error)

    def save_settings(self, changes):
        try:
            self.library.update_settings(changes)
        except (OSError, ValueError) as error:
            # A pre-publication error rolls settings back; a directory-sync
            # failure after publication keeps the committed values. Reflect
            # the actual library state without recursively saving widgets.
            self._syncing_preferences = True
            try:
                settings = self.library.settings
                self.interface_language_selector.set_selected(INTERFACE_LANGUAGE_CODES.index(settings["interface_language"]))
                self.interface_selector.set_selected(("system", "light", "dark").index(settings["interface_theme"]))
                self.font_size.set_value(settings["font_size"])
                self.theme_selector.set_selected(("system", "light", "sepia", "dark").index(settings["theme"]))
                self.font_selector.set_selected(self.font_keys.index(settings["font_family"]))
                self.brightness.set_value(settings["brightness"] * 100)
                self.reader_width.set_value(settings["reader_width"])
                self.speech_language.set_selected(SPEECH_LANGUAGE_CODES.index(settings["speech_language"]))
                self.speech_rate.set_value(settings["speech_rate"] / 1.8)
                self.refresh_voice_choices()
                self.high_contrast_switch.set_active(settings["high_contrast"])
                self.bold_text_switch.set_active(settings["bold_text"])
                self.line_spacing.set_value(settings["line_spacing"])
                self.mouse_gestures_switch.set_active(settings["mouse_gestures"])
                self.reopen_last_book_switch.set_active(settings["reopen_last_book"])
                self.auto_hide_header_switch.set_active(settings["auto_hide_header"])
            finally:
                self._syncing_preferences = False
            self.show_error(_("Не удалось сохранить библиотеку"), error)
            return all(self.library.settings.get(key) == value for key, value in changes.items())
        return True

    def show_book(self, record, book):
        self.cancel_mouse_gesture()
        self.reading_context_popover.popdown()
        document = book.page_document.with_path(record["path"]) if book.page_document is not None else None
        self.save_progress()
        self.speech.stop()
        self._speech_offset = None
        self.cancel_restore()
        self._document_serial += 1
        if self._document_future is not None:
            self.cancel_task(self._document_future)
        self._document_ready = False
        was_paged = self.is_paged()
        self.record, self.book = record, book
        self._reading_progress_index = ReadingProgressIndex.from_book(book)
        try:
            self.library.mark_opened(record["id"])
        except (OSError, ValueError) as error:
            self.show_error(_("Не удалось сохранить библиотеку"), error)
        self.page_document = document
        self.reset_book_search()
        self.document_toolbar.set_visible(self.is_paged())
        self.document_text_expander.set_visible(self.is_paged())
        self.document_text_expander.set_expanded(False)
        self.font_size.set_sensitive(not self.is_paged())
        self.speech_play.set_sensitive(True)
        bind(self.reader_search, placeholder_text=_("Поиск по всей книге"))
        # Reparent only after freezing progress notifications from the old viewport.
        self._restoring = True
        if was_paged != self.is_paged():
            self.reader_scroll.set_child(self.document_canvas if self.is_paged() else self.text_view)
        # Managed filenames are hashes; keep the metadata from the original import.
        title = record["title"]
        author = record["author"]
        if len(book.chapters) == 1 and book.chapters[0].title == Path(record["path"]).stem:
            book.chapters[0].title = title
        bind(self.reader_title, label=title + (f" — {author}" if author else ""))
        bind(self.reader_title, tooltip_text=title + (f" — {author}" if author else ""))
        self.set_title(f"{title} — {APP_NAME}")
        self._chapter_switch = True
        self.rebuild_outline()
        self._chapter_switch = False
        self._internal_navigation = True
        self.stack.set_visible_child_name("reader")
        self._internal_navigation = False
        self.display_chapter(int(record.get("chapter", 0)), int(record.get("offset", 0)), save=False)
        self.refresh_bookmarks()
        self.update_header()
        self.focus_reading_surface()
        if not self.is_paged():
            self.set_status(_("Книга открыта. Позиция чтения сохраняется автоматически."))

    def reader_iter_at_offset(self, offset, *, after_images=False):
        """Translate stable book positions to the buffer's image-anchor positions."""
        return self.buffer.get_iter_at_offset(
            self._reader_image_offsets.to_buffer(offset, after_images=after_images))

    def reader_text_offset(self, iterator):
        """Keep image anchors out of bookmarks, search, speech and page numbers."""
        return self._reader_image_offsets.to_text(iterator.get_offset())

    def set_reader_text(self, text):
        """Style paragraphs without adding controls or changing text offsets."""
        self.clear_chapter_illustrations()
        self.buffer.set_text(text)
        self._reader_image_offsets = TextImageOffsets(len(text), ())
        for start, end, direction in paragraph_runs(text):
            self.buffer.apply_tag(
                self._reader_direction_tags[direction],
                self.buffer.get_iter_at_offset(start),
                self.buffer.get_iter_at_offset(end),
            )

    def display_chapter(self, index, offset=0, save=True, autoplay=False):
        if self.book is None:
            return
        self.cancel_mouse_gesture()
        pending_match = self._book_search_pending
        if pending_match is not None and pending_match[1].chapter != index:
            self._book_search_pending = None
        if save:
            self.save_progress()
        if not autoplay:
            self._speech_intent += 1
        self.speech.stop()
        self._speech_offset = None
        self.chapter_index = max(0, min(index, len(self.book.chapters) - 1))
        self._chapter_switch = True
        self.select_outline_position(self.chapter_index, offset)
        self._chapter_switch = False
        chapter = self.book.chapters[self.chapter_index]
        if self.is_paged():
            self.render_document_page(offset, autoplay=autoplay)
            self.refresh_bookmarks()
            self.update_page_number()
            return
        self.set_reader_text(chapter.text)
        self.set_chapter_illustrations(chapter.images)
        offset = max(0, min(offset, len(chapter.text)))
        self.restore_position(offset)
        self.update_page_number()
        self.refresh_bookmarks()
        if autoplay:
            self.start_speech(0)

    def is_paged(self):
        return self.page_document is not None

    def render_document_page(self, offset=0, autoplay=False, image_only=False):
        """Rasterize only the requested page off the GTK thread; discard stale work."""
        image_only = bool(image_only and self._document_ready)
        if image_only:
            # Hold before changing the paintable: either GTK allocation or the
            # replacement's temporary scroll range can otherwise erase it.
            self.document_position.hold(self.document_geometry(), self.current_offset())
        if not image_only:
            if not autoplay:
                self._speech_intent += 1
            self.speech.stop()
            self._speech_offset = None
            self.cancel_restore()
            self._pending_offset = max(0, min(100000, int(offset)))
            self.document_position.reset(self._pending_offset)
            self._restoring = True
            self._document_ready = False
            self.update_accessibility_state()
        speech_intent = self._speech_intent
        self._document_serial += 1
        serial = self._document_serial
        self._document_render_pending = True
        if self._document_future is not None:
            self.cancel_task(self._document_future)
        document = self.page_document
        index = self.chapter_index
        chapter = self.book.chapters[index]
        if not image_only:
            self.set_reader_text("")
            # Keep only the selected page's text layer in memory.
            for item in self.book.chapters:
                item.text = ""
            self.document_picture.set_paintable(None)
            self.document_picture.set_size_request(-1, -1)
            bind(self.document_picture, alternative_text=_("Загрузка страницы {page}").format(page=index + 1))
            bind(self.document_notice, label=_("Загрузка страницы {page}…").format(page=index + 1))
            self.document_notice.set_visible(True)
            self.speech_play.set_sensitive(False)
        self.document_retry.set_visible(False)
        self._document_view_width = self.reader_scroll.get_width()
        self._document_view_height = self.reader_scroll.get_height()
        self._document_view_scale = self.reader_scroll.get_scale_factor()
        monitor_scale = self._document_view_scale
        width = max(240, self._document_view_width - 32) if self._document_view_width > 0 else 700
        scale = self.document_zoom.get_value() / 100

        render_token = OperationToken()

        def render():
            render_token.check()
            layout = page_layout(*document.page_size(index), fit_width=width,
                                 zoom=scale, device_scale=monitor_scale)
            with tempfile.TemporaryDirectory(prefix="reader-page-") as temporary:
                output = document.render_page(index, Path(temporary) / "page.png",
                                              fit_width=layout.raster_fit_width, scale=layout.raster_scale)
                pixels = output.read_bytes()
            render_token.check()
            # GdkTexture is immutable and new_from_bytes() is explicitly
            # threadsafe. Decode the generated, bounded page PNG here; only
            # attach the completed texture to GTK widgets in ready().
            texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(pixels))
            render_token.check()
            if image_only:
                return texture, None, "", layout
            try:
                text, warning = document.page_text(index), ""
            except (PdfError, DjvuError, CbzError) as error:
                # A missing/forbidden text layer must not prevent page viewing.
                text, warning = "", str(error)
            render_token.check()
            return texture, text, warning, layout

        def ready(result):
            texture, text, warning, layout = result
            restored_offset = self.current_offset() if image_only else self._pending_offset
            if image_only:
                # A user may have superseded the first hold while rendering.
                # Protect their newer choice during paintable publication too.
                self.document_position.hold(self.document_geometry(), restored_offset)
            self._document_render_pending = False
            self.document_picture.set_paintable(DocumentPaintable(texture, layout.logical_width, layout.logical_height))
            self.document_picture.set_size_request(layout.logical_width, layout.logical_height)
            bind(self.document_picture, alternative_text=_("Страница {page} из {pages}").format(page=index + 1, pages=document.page_count))
            self.document_notice.set_visible(False)
            if image_only:
                self.restore_position(restored_offset)
                self.set_status(_("Поиск и озвучка доступны в тексте страницы.") if chapter.text.strip()
                                else _("Страница без текстового слоя. Скан доступен для просмотра; OCR пока не поддерживается."),
                                announce=False)
                return
            chapter.text = text
            self.set_reader_text(text)
            self._document_ready = True
            self.update_accessibility_state()
            self.speech_play.set_sensitive(True)
            self.restore_position(self._pending_offset)
            self.after_book_search_page_ready()
            self.set_status(warning or (_("Поиск и озвучка доступны в тексте страницы.") if text.strip()
                                       else _("Страница без текстового слоя. Скан доступен для просмотра; OCR пока не поддерживается.")))
            if autoplay and speech_intent == self._speech_intent and self.stack.get_visible_child_name() == "reader":
                self.start_speech(0)

        def failed(_error):
            self._document_render_pending = False
            if not image_only:
                bind(self.document_picture, alternative_text=_("Не удалось загрузить страницу {page}").format(page=index + 1))
                bind(self.document_notice, label=_("Не удалось загрузить страницу. Нажмите «Повторить» или выберите другую страницу."))
            self.speech_play.set_sensitive(True)
            self.document_retry.set_visible(True)
            self.update_accessibility_state()

        self._document_future = self.run_task(
            render, ready, _("Загрузка страницы {page}…").format(page=index + 1),
            relevant=lambda: serial == self._document_serial and self.page_document is document,
            on_error=failed,
            on_cancel=lambda: failed(None) if serial == self._document_serial and self.page_document is document else None,
            token=render_token,
            retry=lambda: self.render_document_page(self.current_offset()),
        )

    def document_zoom_changed(self, *_args):
        if self.is_paged() and self.book:
            self.render_document_page(self.current_offset(), image_only=self._document_ready)

    def document_view_tick(self, _widget, _clock):
        if self._closing:
            return GLib.SOURCE_REMOVE
        if self.is_paged() and self._document_ready:
            width, height, density = self.document_geometry()
            # Observe every stable frame, before a subsequent resize can clamp
            # its adjustment. current_offset also guards synchronous saves
            # arriving between reallocation and this tick.
            if not self._restoring:
                self.current_offset()
            if width > 0 and height > 0 and (
                width != self._document_view_width
                or height != self._document_view_height
                or density != self._document_view_scale
            ):
                self._document_view_width = width
                self._document_view_height = height
                self._document_view_scale = density
                if self._document_resize_source is not None:
                    GLib.source_remove(self._document_resize_source)
                self._document_resize_source = GLib.timeout_add(250, self.document_resize)
        return GLib.SOURCE_CONTINUE

    def document_geometry(self):
        return (self.reader_scroll.get_width(), self.reader_scroll.get_height(),
                self.reader_scroll.get_scale_factor())

    def document_resize(self):
        self._document_resize_source = None
        if not self._closing and self.is_paged():
            self.render_document_page(self.current_offset(), image_only=self._document_ready)
        return GLib.SOURCE_REMOVE

    def cancel_restore(self):
        self._restore_serial += 1
        self._restoring = False
        if self._restore_mark is not None and not self._restore_mark.get_deleted():
            self.buffer.delete_mark(self._restore_mark)
        self._restore_mark = None

    def restore_position(self, offset):
        self.cancel_restore()
        if self.is_paged():
            self._pending_offset = max(0, min(100000, int(offset)))
            self._restoring = True
            serial = self._restore_serial
            frames = 0

            def restore_document(widget, _clock):
                nonlocal frames
                if self._closing or serial != self._restore_serial:
                    return GLib.SOURCE_REMOVE
                if not widget.get_mapped() or not self._document_ready:
                    return GLib.SOURCE_CONTINUE
                adjustment = self.reader_scroll.get_vadjustment()
                distance = max(0, adjustment.get_upper() - adjustment.get_page_size())
                adjustment.set_value(distance * self._pending_offset / 100000)
                frames += 1
                if frames < 3:
                    return GLib.SOURCE_CONTINUE
                self._restoring = False
                if not self._document_render_pending:
                    # A style/language change may restore the old image while
                    # its replacement is still rendering. Keep that hold until
                    # the replacement's own restoration has completed.
                    self.document_position.restored(self.document_geometry(), self.visible_offset())
                self.update_progress_label(self._pending_offset)
                return GLib.SOURCE_REMOVE

            self.reader_scroll.add_tick_callback(restore_document)
            return
        self._pending_offset = max(0, min(offset, self._reader_image_offsets.text_length))
        self._restoring = True
        serial = self._restore_serial
        mark = self.buffer.create_mark(None, self.reader_iter_at_offset(self._pending_offset), True)
        self._restore_mark = mark
        frames = 0

        def restore(widget, _clock):
            nonlocal frames
            if self._closing or serial != self._restore_serial:
                return GLib.SOURCE_REMOVE
            if not widget.get_mapped():
                return GLib.SOURCE_CONTINUE
            if frames == 0:
                # Text marks retain the requested position while GTK validates layout.
                widget.scroll_to_mark(mark, 0, True, 0, 0)
            frames += 1
            if frames < 3:
                return GLib.SOURCE_CONTINUE
            self._restoring = False
            if not mark.get_deleted():
                self.buffer.delete_mark(mark)
            self._restore_mark = None
            self.update_progress_label(self._pending_offset)
            return GLib.SOURCE_REMOVE

        self.text_view.add_tick_callback(restore)

    def current_offset(self):
        if not self.is_paged() and self._speech_offset is not None:
            return self._speech_offset
        if self._restoring:
            return self._pending_offset
        offset = self.visible_offset()
        if self.is_paged():
            return self.document_position.current(self.document_geometry(), offset)
        return offset

    def change_chapter(self, delta):
        if self.book:
            if not self.is_paged() and self.book.outline:
                self.select_outline_position(self.chapter_index, self.current_offset())
                if self.current_outline_entry is not None:
                    # Navigation is indexed independently of lazy sidebar rows;
                    # shared part/chapter anchors are visited only once.
                    position = self.adjacent_outline_position(delta)
                    if position is not None:
                        self.display_chapter(*position)
                    return
            new_index = self.chapter_index + delta
            if 0 <= new_index < len(self.book.chapters):
                self.display_chapter(new_index)

    def visible_offset(self):
        if not self.book:
            return 0
        if self.is_paged():
            adjustment = self.reader_scroll.get_vadjustment()
            distance = max(0, adjustment.get_upper() - adjustment.get_page_size())
            return max(0, min(100000, round(100000 * adjustment.get_value() / distance))) if distance else 0
        rectangle = self.text_view.get_visible_rect()
        # A physical left edge can hit the logical end of an RTL line. Use a
        # character hit rather than a cursor hit: its trailing edge can already
        # be the next wrapped line's first offset. Then select the logical start
        # of this display line, preserving wraps within a single paragraph.
        _found, iterator, _trailing = self.text_view.get_iter_at_position(rectangle.x, rectangle.y)
        if not self.text_view.starts_display_line(iterator):
            self.text_view.backward_display_line_start(iterator)
        return self.reader_text_offset(iterator)

    def reader_layout_tick(self, _widget, _clock):
        if self._closing:
            return GLib.SOURCE_REMOVE
        if self.is_paged():
            return GLib.SOURCE_CONTINUE
        width = self.text_view.get_width()
        if width <= 0:
            return GLib.SOURCE_CONTINUE
        limit = self.library.settings["reader_width"]
        key = (width, limit)
        if key != self._reader_layout_key:
            self._reader_layout_key = key
            offset = self.current_offset() if self.book else 0
            padding = max(20, (width - limit) // 2)
            if self.text_view.get_left_margin() != padding or self.text_view.get_right_margin() != padding:
                self.text_view.set_left_margin(padding)
                self.text_view.set_right_margin(padding)
                if self.book:
                    self.restore_position(offset)
        self.update_illustration_layout()
        return GLib.SOURCE_CONTINUE

    def scroll_changed(self, _adjustment):
        if self.book is None or self._restoring or self._closing:
            return
        self.update_progress_label(self.current_offset())
        self.queue_progress_save()

    def queue_progress_save(self):
        if self._save_source:
            GLib.source_remove(self._save_source)
        self._save_source = GLib.timeout_add(700, self.save_progress)

    def save_progress(self):
        if self._save_source:
            GLib.source_remove(self._save_source)
            self._save_source = None
        if self.record and self.book:
            try:
                offset = self.current_offset()
                self.library.update_reading_progress(self.record["id"], self.chapter_index, offset,
                                                     self._reading_progress_index.percent(self.chapter_index, offset))
            except OSError as error:
                self.show_error(_("Не удалось сохранить место чтения"), error)
        return GLib.SOURCE_REMOVE

    def update_progress_label(self, offset):
        self.update_page_number()
        self.select_outline_position(self.chapter_index, offset)
        self.refresh_reading_progress(offset)

    def refresh_reading_progress(self, offset=None):
        """Keep the header in sync with page ranges after scrolling or reflow."""
        if self.book is None or self._current_page_span is None:
            return
        if offset is None:
            offset = self.current_offset()
        if self.is_paged():
            percent = int(self._reading_progress_index.percent(self.chapter_index, offset))
            bind(self.reading_progress, label=_("Страница {page} из {pages}  ·  {percent}% книги").format(
                page=self._current_page_span.first, pages=self._current_page_span.pages, percent=percent,
            ))
            return
        progress = _("{percent}% прочитано").format(
            percent=int(self._reading_progress_index.percent(self.chapter_index, offset)),
        )
        bind(self.reading_progress, label=localized_join(" · ", (
            self.page_number_text(self._current_page_span), progress,
        )))





    def build_catalogs(self):
        manager = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        manager.append(label(_("Сетевые библиотеки OPDS"), "heading"))
        hint = label(_("Подключите публичный OPDS 1.x каталог или каталог Calibre в локальной сети."), "dim-label", True)
        hint.set_max_width_chars(38)
        manager.append(hint)
        connect_row = Gtk.Box(spacing=8)
        self.catalog_selector = translated_dropdown([_("Добавьте каталог")])
        self.catalog_selector.set_hexpand(True)
        connect_row.append(self.catalog_selector)
        connect_row.append(button(_("Подключиться"), self.connect_selected_catalog))
        connect_row.append(button("＋", self.add_catalog_dialog, _("Добавить каталог")))
        connect_row.append(button("−", self.remove_catalog, _("Удалить каталог из списка")))
        manager.append(connect_row)
        self.catalog_popover = Gtk.Popover(child=margins(manager, 12))
        self.catalog_manager_button = translated(Gtk.MenuButton, icon_name="network-server-symbolic", tooltip_text=_("Подключиться"))
        accessible_label(self.catalog_manager_button, _("Подключиться"))
        self.catalog_manager_button.set_popover(self.catalog_popover)
        self.catalog_navigation = Gtk.Box(spacing=2)
        self.catalog_navigation.append(self.catalog_manager_button)
        self.catalog_back = button(_("Назад"), self.catalog_go_back, compact=True)
        self.catalog_back.set_sensitive(False)
        self.catalog_navigation.append(self.catalog_back)
        self.catalog_heading = label(_("Каталог не открыт"), "heading")
        self.catalog_heading.set_max_width_chars(30)
        self.catalog_heading.set_ellipsize(Pango.EllipsizeMode.END)
        self.header_titles.add_named(self.catalog_heading, "catalogs")
        self.catalog_next = button(_("Далее"), self.catalog_next_page, compact=True)
        self.catalog_next.set_sensitive(False)
        self.catalog_navigation.append(self.catalog_next)
        search = Gtk.Box(spacing=8)
        self.catalog_search = translated(Gtk.SearchEntry, placeholder_text=_("Поиск (если каталог его поддерживает)"), hexpand=True)
        self.catalog_search.set_sensitive(False)
        self.catalog_search.connect("activate", self.search_catalog)
        search.append(self.catalog_search)
        self.catalog_search_button = button(_("Найти"), self.search_catalog)
        self.catalog_search_button.set_sensitive(False)
        search.append(self.catalog_search_button)
        self.search_stack.add_named(search, "catalogs")
        self.catalog_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.catalog_list.add_css_class("boxed-list")
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_child(self.catalog_list)
        self.catalog_content = Gtk.Stack(vexpand=True)
        self.catalog_content.add_named(margins(scroll, 8), "entries")
        self.catalog_content.add_named(translated(Adw.StatusPage,
            icon_name="network-server-symbolic", title=_("Сетевые библиотеки OPDS"),
            description=_("Подключите публичный OPDS 1.x каталог или каталог Calibre в локальной сети.")), "empty")
        self.catalog_content.set_visible_child_name("empty")
        hint = label(_("Поддерживаются прямые загрузки EPUB, FB2, TXT, PDF, DjVu, HTML, Markdown и CBZ. Каталоги с авторизацией и DRM пока не поддерживаются."), "dim-label", True)
        hint.set_max_width_chars(38)
        manager.append(hint)
        return self.catalog_content

    def refresh_catalogs(self):
        self.catalog_selector.set_model(translated_strings([item["name"] for item in self.library.catalogs] or [_("Добавьте каталог")]))

    def add_catalog_dialog(self, _button):
        dialog = translated(Gtk.Dialog, title=_("Добавить OPDS-каталог"), transient_for=self, modal=True)
        translated_dialog_button(dialog, _("Отмена"), Gtk.ResponseType.CANCEL)
        translated_dialog_button(dialog, _("Добавить"), Gtk.ResponseType.ACCEPT)
        box = margins(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8))
        box.set_size_request(440, -1)
        box.append(label(_("Название")))
        name = translated(Gtk.Entry, placeholder_text=_("Моя библиотека"))
        box.append(name)
        box.append(label(_("Адрес OPDS-каталога")))
        address = translated(Gtk.Entry, placeholder_text="https://example.org/opds")
        address.set_direction(Gtk.TextDirection.LTR)
        box.append(address)
        box.append(label(_("Для локального Calibre: http://адрес:8080/opds"), "dim-label"))
        dialog.get_content_area().append(box)

        def response(widget, result):
            if result == Gtk.ResponseType.ACCEPT:
                try:
                    self.library.add_catalog(name.get_text().strip() or "OPDS", address.get_text().strip())
                    self.refresh_catalogs()
                    self.catalog_selector.set_selected(len(self.library.catalogs) - 1)
                except (ValueError, OSError) as error:
                    self.show_error(_("Не удалось добавить каталог"), error)
                    return
            widget.destroy()

        dialog.connect("response", response)
        dialog.present()

    def remove_catalog(self, _button):
        index = self.catalog_selector.get_selected()
        if index < len(self.library.catalogs):
            try:
                self.library.remove_catalog(index)
                self.refresh_catalogs()
                self.set_status(_("Каталог удалён из списка."))
            except OSError as error:
                self.show_error(_("Не удалось сохранить список каталогов"), error)

    def connect_selected_catalog(self, _button=None):
        index = self.catalog_selector.get_selected()
        if index < len(self.library.catalogs):
            self.open_catalog(self.library.catalogs[index]["url"], remember=False, reset_history=True)
        else:
            self.add_catalog_dialog(None)

    def open_catalog(self, url, remember=True, going_back=False, reset_history=False):
        if getattr(self, "_catalog_token", None) is not None:
            self._catalog_token.cancel()
        self._catalog_token = token = OperationToken()
        self._catalog_serial += 1
        serial = self._catalog_serial
        previous = self.catalog_url

        def loaded(page):
            if serial != self._catalog_serial:
                return
            if reset_history:
                self.catalog_history.clear()
            if remember and previous:
                self.catalog_history.append(previous)
            if going_back and self.catalog_history and self.catalog_history[-1] == url:
                self.catalog_history.pop()
            self.catalog_url = url
            self.catalog_page = page
            self.render_catalog(page)

        self.run_task(lambda: fetch_catalog(url, cancel=token), loaded, _("Загрузка каталога…"),
                      relevant=lambda: serial == self._catalog_serial, token=token,
                      retry=lambda: self.open_catalog(url, remember, going_back, reset_history))

    def render_catalog(self, page):
        bind(self.catalog_heading, label=page.title or _("OPDS-каталог"))
        bind(self.catalog_heading, tooltip_text=page.title or _("OPDS-каталог"))
        self.catalog_content.set_visible_child_name("entries")
        self.catalog_popover.popdown()
        self.catalog_back.set_sensitive(bool(self.catalog_history))
        self.catalog_next.set_sensitive(bool(page.next_url))
        self.catalog_search.set_sensitive(bool(page.search_url))
        self.catalog_search_button.set_sensitive(bool(page.search_url))
        self.update_header()
        self.clear_list(self.catalog_list)
        for entry in page.entries:
            row = Gtk.ListBoxRow(activatable=False)
            horizontal = margins(Gtk.Box(spacing=12))
            if entry.downloads or getattr(entry, "cover_url", None):
                horizontal.append(self.catalog_cover_widget(entry))
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
            box.append(label(entry.title, "heading", True))
            if entry.author:
                box.append(label(entry.author, "dim-label", True))
            if entry.summary:
                box.append(label(entry.summary[:500], wrap=True))
            actions = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=False,
                                  min_children_per_line=1, max_children_per_line=4,
                                  column_spacing=6, row_spacing=6)
            if entry.catalog_url:
                actions.append(button(_("Открыть раздел"), lambda _b, url=entry.catalog_url: self.open_catalog(url)))
            for acquisition in entry.downloads:
                actions.append(button(_("Скачать {format}").format(format=acquisition.label),
                    lambda _b, item=acquisition, cover=getattr(entry, "cover_url", None): self.acquire_book(item, cover),
                    icon="document-save-symbolic"))
            if not entry.catalog_url and not entry.downloads:
                actions.append(label(_("Нет поддерживаемой прямой загрузки"), "dim-label", True))
            box.append(actions)
            horizontal.append(box)
            row.set_child(horizontal)
            self.catalog_list.append(row)
        if not page.entries:
            self.catalog_list.append(margins(label(_("В этом разделе книг нет.")), 24))
        self.set_status(_("Каталог загружен. Записей: {count}.").format(count=len(page.entries)))

    def catalog_go_back(self, _button):
        if self.catalog_history:
            self.open_catalog(self.catalog_history[-1], remember=False, going_back=True)

    def catalog_next_page(self, _button):
        if self.catalog_page and self.catalog_page.next_url:
            self.open_catalog(self.catalog_page.next_url)

    def search_catalog(self, _entry):
        query = self.catalog_search.get_text().strip()
        if query and self.catalog_page and self.catalog_page.search_url:
            url = self.catalog_page.search_url.replace("{searchTerms}", quote(query, safe=""))
            self.open_catalog(url)

    def acquire_book(self, acquisition, cover_url=None):
        token, serial, navigation = self.begin_book_operation()
        known_ids = {item["id"] for item in self.library.books}

        def download_and_import():
            path = download_book(acquisition, self.library.downloads_dir, cancel=token)
            try:
                item, book = self.library.import_book_with_content(path, cancel=token)
            finally:
                path.unlink(missing_ok=True)
            return item, book, item["id"] in known_ids

        def ready(result):
            item, book, duplicate = result
            if cover_url and book.cover is None:
                self.remember_catalog_cover(item, cover_url)
            self.refresh_library()
            if serial == self._book_serial:
                if duplicate:
                    self.confirm_duplicate(item, book, navigation)
                else:
                    self.complete_book(item, book, navigation)

        self.run_task(download_and_import, ready, _("Скачивание книги…"),
                      relevant=lambda: serial == self._book_serial, on_stale=self.refresh_library,
                      on_cancel=self.refresh_library, token=token,
                      retry=lambda: self.acquire_book(acquisition, cover_url))

    def on_key(self, _controller, key, _code, state):
        modifiers = frozenset(
            name for name, flag in (
                ("control", Gdk.ModifierType.CONTROL_MASK),
                ("shift", Gdk.ModifierType.SHIFT_MASK),
                ("alt", Gdk.ModifierType.ALT_MASK),
                ("super", Gdk.ModifierType.SUPER_MASK),
                ("hyper", Gdk.ModifierType.HYPER_MASK),
                ("meta", Gdk.ModifierType.META_MASK),
            ) if state & flag
        )
        if key == Gdk.KEY_Escape and not modifiers:
            if self._accessibility_popup_tick is not None:
                self.accessibility_button.remove_tick_callback(self._accessibility_popup_tick)
                self._accessibility_popup_tick = None
                return True
            if self._mouse_active:
                self.cancel_mouse_gesture()
                return True
            focus_ancestor = self.get_focus()
            while focus_ancestor is not None:
                if isinstance(focus_ancestor, Gtk.Popover) and focus_ancestor.get_visible():
                    focus_ancestor.popdown()
                    return True
                focus_ancestor = focus_ancestor.get_parent()
            for popover in (self.reading_context_popover, self.search_popover, self.reader_tools_popover,
                            self.catalog_popover, self.operation_popover,
                            self.library_controls.get_popover(),
                            self.bookmarks_button.get_popover(),
                            self.main_menu_button.get_popover(), self.accessibility_button.get_popover()):
                if popover is not None and popover.get_visible():
                    popover.popdown()
                    return True
            if self.is_fullscreen():
                self.unfullscreen()
                return True
        reading = self.stack.get_visible_child_name() == "reader"
        focus = self.get_focus()
        reading_focus = focus in (self.text_view, self.document_text_view, self.reader_scroll,
                                  self.document_picture, self.document_canvas)
        action = shortcut_for(Gdk.keyval_name(key), modifiers, reading=reading,
                              has_book=self.book is not None, reading_focus=reading_focus,
                              settings=self.library.settings)
        if action is None and self.handle_reader_navigation(Gdk.keyval_name(key), modifiers):
            return True
        # Ctrl+Up/Down still move the native text cursor by paragraphs. Observe
        # that manual movement without taking over its selection semantics.
        if (action is None and modifiers == {"control"}
                and key in (Gdk.KEY_Up, Gdk.KEY_Down, Gdk.KEY_KP_Up, Gdk.KEY_KP_Down)
                and self.reading_navigation_has_focus()):
            self.manual_scroll()
        callbacks = {
            "open": self.choose_files,
            "search": self.open_search,
            "preferences": self.preferences_window.present,
            "accessibility": self.open_accessibility_menu,
            "library": lambda: self.stack.set_visible_child_name("library"),
            "reader": lambda: self.stack.set_visible_child_name("reader"),
            "catalogs": lambda: self.stack.set_visible_child_name("catalogs"),
            "fullscreen": self.toggle_fullscreen,
            "day-night": self.toggle_day_night,
            "toolbar": self.reveal_header_for_keyboard,
            "manual": self.show_manual,
            "shortcuts": self.show_shortcuts,
            "quit": self.close,
            "larger": lambda: self.adjust_text_size(1),
            "smaller": lambda: self.adjust_text_size(-1),
            "reset-size": lambda: self.adjust_text_size(0),
            "previous": lambda: self.change_chapter(-1),
            "next": lambda: self.change_chapter(1),
            "contents": lambda: self.reader_split.set_show_sidebar(not self.reader_split.get_show_sidebar()),
            "bookmark": self.add_bookmark,
            "speech": self.toggle_speech,
            "stop-speech": self.stop_speech,
        }
        if action is None:
            return False
        callbacks[action]()
        return True

    def on_close(self, _window):
        self.cancel_mouse_gesture()
        self.reading_context_popover.popdown()
        if self.reading_context_popover.get_parent() is not None:
            self.reading_context_popover.unparent()
        self.save_progress()
        self.safe_save()
        if self._status_toast is not None:
            self._status_toast.dismiss()
        self._closing = True
        self.close_narration_ui()
        self.close_shortcut_ui()
        self.close_outline_ui()
        self.close_library_ui()
        self.close_cover_ui()
        self.close_illustration_ui()
        if self._accessibility_popup_tick is not None:
            self.accessibility_button.remove_tick_callback(self._accessibility_popup_tick)
            self._accessibility_popup_tick = None
        self.close_accessibility_ui()
        self.close_page_numbers()
        self.close_immersive()
        self.reset_book_search()
        self.close_tasks()
        if self._portal_chooser is not None:
            self._portal_chooser.cancel()
        if self._native_chooser is not None:
            self._native_chooser.destroy()
            self._native_chooser = None
        if self.desktop_appearance is not None:
            self.desktop_appearance.close()
        self.close_bookmark_dialogs()
        self.preferences_window.destroy()
        for window in (self.manual_window, self.shortcuts_window):
            if window is not None:
                window.destroy()
        if self._document_resize_source is not None:
            GLib.source_remove(self._document_resize_source)
            self._document_resize_source = None
        self.cancel_restore()
        self.speech.close()
        if self._style_handler is not None:
            self.style_manager.disconnect(self._style_handler)
        if self._style_support_handler is not None:
            self.style_manager.disconnect(self._style_support_handler)
        if self._style_contrast_handler is not None:
            self.style_manager.disconnect(self._style_contrast_handler)
        Gtk.StyleContext.remove_provider_for_display(self.get_display(), self.css)
        self.executor.shutdown(wait=False, cancel_futures=True)
        return False
