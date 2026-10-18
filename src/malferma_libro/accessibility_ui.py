"""A compact accessibility menu and a local, permission-free reading lens.

The preferences window owns the persisted controls. Menu controls mirror those
widgets, including their rollback after a failed save, instead of maintaining
a second settings path. The magnifier is a session-only overlay and snapshots
the reader widget, never the desktop or its own overlay.
"""

from __future__ import annotations

import logging
import math

from gi.repository import Gdk, Graphene, Gtk, Pango

from .live_i18n import localized as _


LOG = logging.getLogger(__name__)


def _rectangle(x, y, width, height):
    rectangle = Graphene.Rect()
    rectangle.init(float(x), float(y), float(width), float(height))
    return rectangle


def _point(x, y):
    point = Graphene.Point()
    point.init(float(x), float(y))
    return point


class ReadingMagnifier(Gtk.Widget):
    """Draw a movable lens without receiving input or changing reader layout."""

    __gtype_name__ = "MalfermaReadingMagnifier"

    def __init__(self, target):
        super().__init__(hexpand=True, vexpand=True, halign=Gtk.Align.FILL, valign=Gtk.Align.FILL)
        self.set_can_target(False)
        self.set_focusable(False)
        self.target = target
        self.zoom = 2.0
        self.pointer = None
        self.paintable = Gtk.WidgetPaintable.new(target)
        self._paintable_handlers = [
            self.paintable.connect("invalidate-contents", self._invalidated),
            self.paintable.connect("invalidate-size", self._invalidated),
        ]
        self._black = Gdk.RGBA()
        self._black.parse("#000000")
        self._white = Gdk.RGBA()
        self._white.parse("#ffffff")

    def do_measure(self, _orientation, _for_size):
        # The overlay fills its parent's allocation and never requests a larger
        # reading viewport or imposes a minimum window size.
        return 0, 0, -1, -1

    def _invalidated(self, *_args):
        if self.get_visible():
            self.queue_draw()

    def set_zoom(self, value):
        try:
            value = float(value)
        except (TypeError, ValueError, OverflowError):
            return
        if math.isfinite(value):
            self.zoom = max(2.0, min(4.0, value))
            self.queue_draw()

    def set_pointer(self, x, y):
        if math.isfinite(x) and math.isfinite(y):
            self.pointer = (float(x), float(y))
            self.queue_draw()

    def center_pointer(self):
        self.pointer = None
        self.queue_draw()

    def lens_geometry(self):
        """Return lens bounds and source centre in GTK logical coordinates."""
        if self.target is None:
            return None
        width, height = self.target.get_width(), self.target.get_height()
        if width < 64 or height < 64:
            return None
        pointer_x, pointer_y = self.pointer or (width / 2, height / 2)
        pointer_x = max(0, min(width, pointer_x))
        pointer_y = max(0, min(height, pointer_y))
        # Keeping the lens below half the viewport width leaves room beside the
        # source point even with a narrow reading area and a visible sidebar.
        lens_width = min(320, max(48, (width - 48) / 2))
        lens_height = min(200, height - 24)
        left = pointer_x + 20
        if left + lens_width > width - 8:
            left = pointer_x - lens_width - 20
        left = max(8, min(width - lens_width - 8, left))
        top = max(8, min(height - lens_height - 8, pointer_y - lens_height / 2))
        # Near an edge keep the sampled region inside the reading viewport.
        half_width, half_height = lens_width / (2 * self.zoom), lens_height / (2 * self.zoom)
        source_x = max(half_width, min(width - half_width, pointer_x))
        source_y = max(half_height, min(height - half_height, pointer_y))
        return left, top, lens_width, lens_height, source_x, source_y

    def do_snapshot(self, snapshot):
        if self.target is None or not self.target.get_mapped():
            return
        geometry = self.lens_geometry()
        if geometry is None:
            return
        left, top, width, height, source_x, source_y = geometry
        # A two-colour frame remains visible over both light and dark pages.
        snapshot.append_color(self._black, _rectangle(left - 3, top - 3, width + 6, height + 6))
        snapshot.append_color(self._white, _rectangle(left - 1, top - 1, width + 2, height + 2))
        snapshot.save()
        snapshot.push_clip(_rectangle(left, top, width, height))
        snapshot.translate(_point(left + width / 2 - source_x * self.zoom,
                                  top + height / 2 - source_y * self.zoom))
        snapshot.scale(self.zoom, self.zoom)
        # WidgetPaintable sees only reader_scroll. The lens is its sibling in
        # Gtk.Overlay, so this snapshot cannot recursively include the lens.
        self.paintable.snapshot(snapshot, self.target.get_width(), self.target.get_height())
        snapshot.pop()
        snapshot.restore()

    def close(self):
        if self.target is None:
            return
        self.set_visible(False)
        for handler in self._paintable_handlers:
            self.paintable.disconnect(handler)
        self._paintable_handlers.clear()
        self.paintable.set_widget(None)
        self.target = None


class AccessibilityMixin:
    """ReaderWindow integration for mirrored controls and the reading lens."""

    def _accessibility_connect(self, widget, signal, callback):
        handler = widget.connect(signal, callback)
        self._accessibility_handlers.append((widget, handler))
        return handler

    def _mirror_accessibility_value(self, canonical, clone, signal, getter, setter, sensitive=True):
        busy = False

        def canonical_changed(*_args):
            nonlocal busy
            if busy or self._accessibility_closed:
                return
            busy = True
            try:
                getattr(clone, setter)(getattr(canonical, getter)())
            finally:
                busy = False

        def clone_changed(*_args):
            nonlocal busy
            if (busy or self._accessibility_closed or self._syncing_preferences
                    or self._accessibility_model_syncing):
                return
            busy = True
            try:
                getattr(canonical, setter)(getattr(clone, getter)())
                # Canonical save callbacks may synchronously roll their widget
                # back. Re-read it after callbacks finish, rather than hiding a
                # failed preference save behind a stale mirrored selection.
                getattr(clone, setter)(getattr(canonical, getter)())
            finally:
                busy = False

        self._accessibility_connect(canonical, signal, canonical_changed)
        self._accessibility_connect(clone, signal, clone_changed)
        canonical_changed()
        if sensitive:
            def sensitivity_changed(*_args):
                clone.set_sensitive(canonical.get_sensitive())
            self._accessibility_connect(canonical, "notify::sensitive", sensitivity_changed)
            sensitivity_changed()
        return clone

    def init_reading_magnifier(self, reader_overlay):
        self._accessibility_closed = False
        self._accessibility_model_syncing = False
        self._accessibility_handlers = []
        self._accessibility_resize_tick = None
        self._accessibility_allocation = None
        self._magnifier_overlay = reader_overlay
        self.reading_magnifier = ReadingMagnifier(self.reader_scroll)
        self.reading_magnifier.set_visible(False)
        reader_overlay.add_overlay(self.reading_magnifier)
        reader_overlay.set_measure_overlay(self.reading_magnifier, False)
        reader_overlay.set_clip_overlay(self.reading_magnifier, True)
        self._magnifier_motion = Gtk.EventControllerMotion()
        self._magnifier_motion.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self._accessibility_connect(self._magnifier_motion, "motion", self._reading_magnifier_motion)
        self._accessibility_connect(self._magnifier_motion, "leave", self._reading_magnifier_leave)
        self.reader_scroll.add_controller(self._magnifier_motion)

    def _reading_magnifier_motion(self, _controller, x, y):
        if not self._accessibility_closed and self.reading_magnifier.get_visible():
            self.reading_magnifier.set_pointer(x, y)

    def _reading_magnifier_leave(self, *_args):
        if not self._accessibility_closed:
            self.reading_magnifier.center_pointer()

    def build_accessibility_menu(self):
        # Import the application's shared binding helpers only at construction
        # time, after app.py has defined them, to avoid an import cycle.
        from .app import accessible_label, button, label, margins, translated

        content = margins(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12), 8)
        self.accessibility_content = content

        def row(title, widget, stacked=False):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if stacked else Gtk.Orientation.HORIZONTAL,
                          spacing=6 if stacked else 12)
            title_label = label(title, wrap=True)
            # A long word must not force the row past the viewport and under
            # its reserved scrollbar when the menu is constrained by a screen.
            title_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            title_label.set_max_width_chars(24)
            title_label.set_hexpand(True)
            widget.set_hexpand(stacked)
            widget.set_valign(Gtk.Align.CENTER)
            accessible_label(widget, title)
            box.append(title_label)
            box.append(widget)
            content.append(box)
            return widget

        content.append(label(_("Озвучка"), "heading", wrap=True))
        transport = Gtk.Box(spacing=6)
        self.speech_play.set_hexpand(True)
        transport.append(self.speech_play)
        self.accessibility_speech_stop = button(_("Стоп"), self.stop_speech)
        transport.append(self.accessibility_speech_stop)
        content.append(transport)
        self.speech_status.set_wrap(True)
        self.speech_status.set_max_width_chars(28)
        content.append(self.speech_status)

        self.accessibility_speech_language = Gtk.DropDown(model=self.speech_language.get_model())
        self._mirror_accessibility_value(self.speech_language, self.accessibility_speech_language,
                                         "notify::selected", "get_selected", "set_selected", sensitive=False)

        def language_model_changed(*_args):
            self._accessibility_model_syncing = True
            try:
                self.accessibility_speech_language.set_model(self.speech_language.get_model())
                self.accessibility_speech_language.set_selected(self.speech_language.get_selected())
            finally:
                self._accessibility_model_syncing = False

        self._accessibility_connect(self.speech_language, "notify::model", language_model_changed)
        row(_("Язык"), self.accessibility_speech_language, stacked=True)
        self.accessibility_speech_rate = Gtk.SpinButton.new_with_range(44, 250, 10)
        self._mirror_accessibility_value(self.speech_rate, self.accessibility_speech_rate,
                                         "value-changed", "get_value", "set_value", sensitive=False)
        row(_("Скорость, %"), self.accessibility_speech_rate)
        self.accessibility_voices_button = button(_("Голоса Piper"), self.show_voice_settings)
        content.append(self.accessibility_voices_button)

        content.append(Gtk.Separator())
        content.append(label(_("Специальные возможности"), "heading", wrap=True))
        # Reuse the canonical controls, with one widget and one handler per
        # action. Header and compact-menu copies are unnecessary here.
        self.text_size_actions.set_homogeneous(True)
        for control in (self.text_size_decrease, self.text_size_reset, self.text_size_increase):
            control.set_hexpand(True)
        row(_("Размер текста"), self.text_size_actions, stacked=True)

        for name, title, canonical in (
            ("accessibility_high_contrast", _("Высокая контрастность"), self.high_contrast_switch),
            ("accessibility_bold_text", _("Полужирный текст"), self.bold_text_switch),
        ):
            control = Gtk.Switch()
            setattr(self, name, control)
            self._mirror_accessibility_value(canonical, control, "notify::active", "get_active", "set_active")
            row(title, control)
        self.accessibility_line_spacing = Gtk.SpinButton.new_with_range(1.0, 2.0, 0.1)
        self.accessibility_line_spacing.set_digits(1)
        self._mirror_accessibility_value(self.line_spacing, self.accessibility_line_spacing,
                                         "value-changed", "get_value", "set_value")
        row(_("Межстрочный интервал"), self.accessibility_line_spacing)
        row(_("Режим для слабовидящих"), button(_("Применить"), self.low_vision_preset))

        content.append(Gtk.Separator())
        self.magnifier_switch = Gtk.Switch()
        self.magnifier_factor = Gtk.SpinButton.new_with_range(2.0, 4.0, 0.5)
        self.magnifier_factor.set_digits(1)
        self.magnifier_factor.set_value(2.0)
        row(_("Лупа области чтения"), self.magnifier_switch)
        row(_("Увеличение лупы"), self.magnifier_factor)
        self._accessibility_connect(self.magnifier_switch, "notify::active", self._magnifier_enabled_changed)
        self._accessibility_connect(self.magnifier_factor, "value-changed",
                                    lambda control: self.reading_magnifier.set_zoom(control.get_value()))

        self.accessibility_scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER, vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            min_content_width=320, max_content_width=360, max_content_height=324,
            propagate_natural_width=True, propagate_natural_height=True,
        )
        # Native scrollbars reserve their own allocation. Inner logical margins
        # keep labels and controls clear of the scrollbar in both LTR and RTL.
        self.accessibility_scroll.set_overlay_scrolling(False)
        self.accessibility_scroll.set_child(content)
        self.accessibility_popover = Gtk.Popover(child=self.accessibility_scroll)
        self._accessibility_connect(self.accessibility_popover, "notify::visible", self._accessibility_popover_changed)
        self._accessibility_connect(self.accessibility_popover, "map", self._accessibility_mapped)
        self._accessibility_connect(self.accessibility_popover, "unmap", self._accessibility_unmapped)
        menu_button = translated(Gtk.MenuButton, icon_name="preferences-desktop-accessibility-symbolic",
                                 tooltip_text=_("Специальные возможности"))
        accessible_label(menu_button, _("Специальные возможности"))
        menu_button.set_popover(self.accessibility_popover)
        self._accessibility_connect(self.stack, "notify::visible-child-name", lambda *_args: self.update_accessibility_state())
        self.update_accessibility_state()
        return menu_button

    def _magnifier_enabled_changed(self, control, *_args):
        if self._accessibility_closed:
            return
        self.reading_magnifier.center_pointer()
        self.reading_magnifier.set_visible(control.get_active())

    def _accessibility_popover_changed(self, *_args):
        if self._accessibility_closed or not self.accessibility_popover.get_visible():
            return
        self._accessibility_allocation = self.get_width(), self.get_height()
        available_width = max(160, self.get_width() - 64)
        maximum_width = min(360, available_width)
        minimum_width = min(320, maximum_width)
        # Lower the old minimum before narrowing, and raise the maximum before
        # widening, so GTK never observes an invalid min/max pair.
        if minimum_width < self.accessibility_scroll.get_min_content_width():
            self.accessibility_scroll.set_min_content_width(minimum_width)
        self.accessibility_scroll.set_max_content_width(maximum_width)
        self.accessibility_scroll.set_min_content_width(minimum_width)
        # With horizontal scrolling disabled, min-content-width alone does not
        # protect the viewport from a popover allocating less than its content.
        self.accessibility_scroll.set_size_request(minimum_width, -1)
        self.accessibility_scroll.set_max_content_height(max(120, min(560, self.get_height() - 96)))
        self.update_accessibility_state()

    def _accessibility_mapped(self, *_args):
        if self._accessibility_resize_tick is None and not self._accessibility_closed:
            # Window default-size properties do not change when the user
            # resizes it. Observe actual allocations only while this menu is
            # mapped, and avoid requesting layout again for unchanged frames.
            self._accessibility_resize_tick = self.accessibility_popover.add_tick_callback(
                self._accessibility_allocation_tick)

    def _accessibility_allocation_tick(self, _widget, _clock):
        if self._accessibility_closed:
            self._accessibility_resize_tick = None
            return False
        if (self.get_width(), self.get_height()) != self._accessibility_allocation:
            self._accessibility_popover_changed()
        return True

    def _accessibility_unmapped(self, *_args):
        if self._accessibility_resize_tick is not None:
            self.accessibility_popover.remove_tick_callback(self._accessibility_resize_tick)
            self._accessibility_resize_tick = None

    def update_accessibility_state(self):
        if getattr(self, "_accessibility_closed", True) or not hasattr(self, "accessibility_speech_language"):
            return
        ready = self.book is not None and (not self.is_paged() or self._document_ready)
        for control in (self.speech_play, self.accessibility_speech_stop,
                        self.accessibility_speech_language, self.accessibility_speech_rate):
            control.set_sensitive(ready)

    def close_accessibility_ui(self):
        if getattr(self, "_accessibility_closed", True):
            return
        self._accessibility_closed = True
        self.accessibility_popover.popdown()
        self._accessibility_unmapped()
        for widget, handler in self._accessibility_handlers:
            try:
                widget.disconnect(handler)
            except (TypeError, RuntimeError):
                LOG.debug("Accessibility control was already disposed", exc_info=True)
        self._accessibility_handlers.clear()
        self.reader_scroll.remove_controller(self._magnifier_motion)
        self.reading_magnifier.close()
        if self.reading_magnifier.get_parent() is self._magnifier_overlay:
            self._magnifier_overlay.remove_overlay(self.reading_magnifier)
