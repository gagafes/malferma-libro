"""Fullscreen reading chrome policy and a lazily loaded GTK integration.

Coordinates and toolbar sizes are GTK logical units. Importing this module
does not initialize GTK, a display, fonts, or accessibility infrastructure.
"""

from dataclasses import dataclass, replace
import math
import time


@dataclass(frozen=True)
class HeaderContext:
    fullscreen: bool = False
    reading: bool = False
    has_book: bool = False
    enabled: bool = True
    toolbar_focus: bool = False
    popup: bool = False
    dialog: bool = False
    gesture: bool = False
    accessibility: bool = False

    @property
    def active(self):
        return (self.fullscreen and self.reading and self.has_book
                and self.enabled and not self.accessibility)

    @property
    def protected(self):
        return self.toolbar_focus or self.popup or self.dialog or self.gesture


class HeaderVisibility:
    """Hide idle reading chrome while preserving ways to reach its controls.

    Repeated pointer movement outside the header postpones hiding, but never
    reveals an already hidden header. Entering the top edge and keyboard
    navigation reveal it. A protected interaction cancels the old deadline,
    leaving a complete delay after that interaction finishes.
    """

    def __init__(self, delay=2.0, top_edge=24.0):
        if not math.isfinite(delay) or delay <= 0:
            raise ValueError("The header idle delay must be finite and positive")
        if not math.isfinite(top_edge) or top_edge <= 0:
            raise ValueError("The header edge must be finite and positive")
        self.delay = delay
        self.top_edge = top_edge
        self.revealed = True
        self.deadline = None
        self.pointer_at_edge = False
        self.pointer_in_header = False
        self._active = False

    def sync(self, context, now):
        active = context.active
        if (not active or context.protected or self.pointer_at_edge
                or self.pointer_in_header):
            self.revealed = True
            self.deadline = None
        elif not self._active:
            self.revealed = True
            self.deadline = now + self.delay
        elif self.revealed:
            if self.deadline is None:
                self.deadline = now + self.delay
            elif now >= self.deadline:
                self.revealed = False
                self.deadline = None
        self._active = active
        return self.revealed

    def motion(self, y, header_height, context, now):
        if not math.isfinite(y) or not math.isfinite(header_height):
            return self.sync(context, now)
        self.pointer_at_edge = 0 <= y <= self.top_edge
        self.pointer_in_header = self.revealed and 0 <= y <= max(0, header_height)
        if self.revealed and not self.pointer_at_edge and not self.pointer_in_header:
            self.deadline = now + self.delay
        return self.sync(context, now)

    def leave(self, context, now):
        self.pointer_at_edge = False
        self.pointer_in_header = False
        return self.sync(context, now)

    def keyboard(self, context, now):
        self.revealed = True
        self.deadline = now + self.delay
        return self.sync(context, now)


class ImmersiveMixin:
    """Add optional header hiding to a ReaderWindow without owning its UI.

    The host provides ``toolbar_view``, ``header``, ``stack``, ``book``,
    ``library.settings``, and its ordinary GTK Window methods. Call
    :meth:`sync_immersive` after fullscreen, section, or preference changes.
    """

    def init_immersive(self):
        from gi.repository import Gdk, GLib, Gtk

        self._immersive_gtk = (Gdk, GLib, Gtk)
        self._immersive_policy = HeaderVisibility()
        self._immersive_source = None
        self._immersive_focus_source = None
        self._immersive_focus_attempts = 0
        self._immersive_closed = False
        self._immersive_motion = Gtk.EventControllerMotion()
        self._immersive_motion.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self._immersive_motion.connect("motion", self._immersive_pointer_motion)
        self._immersive_motion.connect("leave", self._immersive_pointer_leave)
        self.add_controller(self._immersive_motion)
        self._immersive_keys = Gtk.EventControllerKey()
        self._immersive_keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self._immersive_keys.connect("key-pressed", self._immersive_key_pressed)
        self.add_controller(self._immersive_keys)
        self._immersive_focus_handler = self.connect("notify::focus-widget", self.sync_immersive)
        self._immersive_focus_visible_handler = self.connect("notify::focus-visible", self.sync_immersive)
        self._immersive_active_handler = self.connect("notify::is-active", self.sync_immersive)
        manager = getattr(self, "style_manager", None)
        self._immersive_contrast_handler = (manager.connect("notify::high-contrast", self.sync_immersive)
                                            if manager is not None else None)
        self.sync_immersive()

    @staticmethod
    def _immersive_descendant(widget, ancestor):
        return widget is not None and (widget is ancestor or widget.is_ancestor(ancestor))

    def _immersive_visible_popup(self):
        _gdk, _glib, Gtk = self._immersive_gtk
        pending = [self]
        while pending:
            widget = pending.pop()
            if isinstance(widget, Gtk.Popover) and widget.get_visible():
                return True
            child = widget.get_first_child()
            while child is not None:
                pending.append(child)
                child = child.get_next_sibling()
        return False

    def _immersive_visible_dialog(self):
        _gdk, _glib, Gtk = self._immersive_gtk
        windows = Gtk.Window.get_toplevels()
        for index in range(windows.get_n_items()):
            window = windows.get_item(index)
            if window is self or not window.get_visible():
                continue
            parent = window.get_transient_for()
            seen = set()
            while parent is not None and id(parent) not in seen:
                if parent is self:
                    return True
                seen.add(id(parent))
                parent = parent.get_transient_for()
        return False

    def _immersive_context(self):
        settings = self.library.settings
        manager = getattr(self, "style_manager", None)
        focus = self.get_focus()
        high_contrast = bool(settings.get("high_contrast", False))
        if manager is not None:
            high_contrast = high_contrast or manager.get_high_contrast()
        context = HeaderContext(
            fullscreen=self.is_fullscreen(),
            reading=self.stack.get_visible_child_name() == "reader",
            has_book=self.book is not None,
            enabled=settings.get("auto_hide_header", True),
            # Clicking the fullscreen button leaves ordinary input focus on
            # it after the pointer moves into the book. Only visible keyboard
            # focus should pin the header open for navigation.
            toolbar_focus=((self._immersive_descendant(focus, self.header)
                            and focus.has_visible_focus())
                           or self._immersive_focus_source is not None),
            gesture=bool(getattr(self, "_mouse_active", False)),
            accessibility=high_contrast,
        )
        # Pointer motion also reaches this method in ordinary windows and in
        # large libraries. Their header cannot hide, so walking every widget
        # for popovers and every toplevel for dialogs serves no purpose there.
        if not context.active:
            return context
        return replace(
            context,
            popup=self._immersive_visible_popup(),
            dialog=(self._immersive_visible_dialog()
                    or getattr(self, "_native_chooser", None) is not None
                    or bool(getattr(getattr(self, "_portal_chooser", None), "active", False))),
        )

    def _immersive_render(self, context):
        # Keep the reading surface's allocation fixed while the toolbar slides
        # over it. Normal windows continue to reserve ordinary header space.
        self.toolbar_view.set_extend_content_to_top_edge(context.active)
        self.toolbar_view.set_reveal_top_bars(self._immersive_policy.revealed)

    def sync_immersive(self, *_args):
        if not hasattr(self, "_immersive_policy") or self._immersive_closed:
            return
        context = self._immersive_context()
        self._immersive_policy.sync(context, time.monotonic())
        self._immersive_render(context)
        self._immersive_schedule(context)

    def _immersive_schedule(self, context):
        _gdk, GLib, _gtk = self._immersive_gtk
        if self._immersive_source is not None:
            GLib.source_remove(self._immersive_source)
            self._immersive_source = None
        if context.active and self._immersive_policy.revealed:
            # A short check while visible also notices a dialog/popover closing
            # without a focus-widget change. Hidden and normal windows do not
            # poll, and no callback accesses a closed window.
            self._immersive_source = GLib.timeout_add(250, self._immersive_tick)

    def _immersive_tick(self):
        _gdk, GLib, _gtk = self._immersive_gtk
        self._immersive_source = None
        self.sync_immersive()
        return GLib.SOURCE_REMOVE

    def _immersive_pointer_motion(self, _controller, _x, y):
        if self._immersive_closed:
            return
        context = self._immersive_context()
        self._immersive_policy.motion(y, self.header.get_height(), context, time.monotonic())
        self._immersive_render(context)
        self._immersive_schedule(context)

    def _immersive_pointer_leave(self, _controller):
        if self._immersive_closed:
            return
        context = self._immersive_context()
        self._immersive_policy.leave(context, time.monotonic())
        self._immersive_render(context)
        self._immersive_schedule(context)

    def _immersive_key_pressed(self, _controller, key, _code, state):
        Gdk, _glib, _gtk = self._immersive_gtk
        if key in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
            context = self._immersive_context()
            self._immersive_policy.keyboard(context, time.monotonic())
            self._immersive_render(context)
            self._immersive_schedule(context)
        return False

    def reveal_header_for_keyboard(self):
        if not hasattr(self, "_immersive_policy") or self._immersive_closed:
            return False
        _gdk, GLib, Gtk = self._immersive_gtk
        # F10 is handled before GTK's own keyboard bindings. Mark this explicit
        # keyboard navigation so it receives the usual visible focus rectangle.
        self.set_focus_visible(True)
        context = self._immersive_context()
        self._immersive_policy.keyboard(context, time.monotonic())
        self._immersive_render(context)
        # child_focus follows GTK's normal direction and skips hidden or
        # insensitive controls; F10 does not depend on a particular layout.
        if not self.header.child_focus(Gtk.DirectionType.TAB_FORWARD):
            # A native revealer may not map its controls until the next frame.
            # Keep the bar protected while keyboard focus waits for that frame.
            if self._immersive_focus_source is None:
                self._immersive_focus_attempts = 0
                self._immersive_focus_source = GLib.timeout_add(40, self._immersive_focus_header)
        self._immersive_schedule(self._immersive_context())
        return True

    def _immersive_focus_header(self):
        _gdk, GLib, Gtk = self._immersive_gtk
        if self._immersive_closed:
            self._immersive_focus_source = None
            return GLib.SOURCE_REMOVE
        self._immersive_focus_attempts += 1
        if self.header.child_focus(Gtk.DirectionType.TAB_FORWARD) or self._immersive_focus_attempts >= 10:
            self._immersive_focus_source = None
            self.sync_immersive()
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def close_immersive(self):
        if not hasattr(self, "_immersive_policy") or self._immersive_closed:
            return
        self._immersive_closed = True
        _gdk, GLib, _gtk = self._immersive_gtk
        if self._immersive_source is not None:
            GLib.source_remove(self._immersive_source)
            self._immersive_source = None
        if self._immersive_focus_source is not None:
            GLib.source_remove(self._immersive_focus_source)
            self._immersive_focus_source = None
        self.disconnect(self._immersive_focus_handler)
        self.disconnect(self._immersive_focus_visible_handler)
        self.disconnect(self._immersive_active_handler)
        if self._immersive_contrast_handler is not None:
            self.style_manager.disconnect(self._immersive_contrast_handler)
        self.remove_controller(self._immersive_motion)
        self.remove_controller(self._immersive_keys)
