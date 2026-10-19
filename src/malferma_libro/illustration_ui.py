"""Lazy inline book illustrations and a native, keyboard-accessible viewer.

Only nearby images are decoded. The worker pool, resident pixel budget and
generation checks keep large books and rapid chapter changes inexpensive.

SPDX-License-Identifier: GPL-3.0-or-later
"""

from bisect import bisect_left, bisect_right
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import weakref

from .illustrations import TextImageOffsets, decode_illustration
from .live_i18n import localized as _


_picture_type = None


def _sized_picture(**properties):
    """Keep device pixels from becoming a GTK widget's logical natural size."""
    from gi.repository import Gtk

    global _picture_type
    if _picture_type is None:
        class IllustrationPicture(Gtk.Picture):
            __gtype_name__ = "MalfermaIllustrationPicture"

            def do_measure(self, orientation, _for_size):
                width, height = getattr(self, "display_size", (1, 1))
                size = width if orientation == Gtk.Orientation.HORIZONTAL else height
                return size, size, -1, -1

            def set_display_size(self, width, height):
                self.display_size = width, height
                self.queue_resize()

        _picture_type = IllustrationPicture
    return _picture_type(**properties)


@dataclass
class _InlineWidget:
    reference: object
    anchor: object
    button: object
    picture: object
    placeholder: object
    target: tuple = (0, 0)
    failed: bool = False


class IllustrationUIMixin:
    _ILLUSTRATION_WORKERS = 2
    _ILLUSTRATION_MEMORY_PIXELS = 12_000_000
    _ILLUSTRATION_RESIDENT_LIMIT = 8

    def init_illustration_ui(self):
        self._illustrations_closed = False
        self._illustration_generation = 0
        self._illustration_viewer_generation = 0
        self._illustration_items = []
        self._illustration_anchor_offsets = []
        self._illustration_resident = OrderedDict()
        self._illustration_running = {}
        self._illustration_scan_source = None
        self._illustration_layout_key = None
        self._illustration_viewer = None
        self._illustration_viewer_state = None
        self._reader_image_offsets = TextImageOffsets(0, ())
        self._illustration_executor = ThreadPoolExecutor(
            max_workers=self._ILLUSTRATION_WORKERS, thread_name_prefix="illustration")
        adjustment = self.reader_scroll.get_vadjustment()
        self._illustration_adjustment_handlers = [adjustment.connect(
            signal, self.schedule_illustration_scan) for signal in ("changed", "value-changed")]

    def clear_chapter_illustrations(self):
        """Release widgets before the caller replaces the chapter's buffer."""
        self._illustration_generation += 1
        self._close_illustration_viewer()
        for item in self._illustration_items:
            if item.button.get_parent() is self.text_view:
                self.text_view.remove(item.button)
        self._illustration_items.clear()
        self._illustration_anchor_offsets.clear()
        self._illustration_resident.clear()
        self._illustration_layout_key = None
        # Do not forget running futures: rapid navigation must not enqueue an
        # unbounded number of stale image decodes behind the two workers.
        self._reader_image_offsets = TextImageOffsets(0, ())

    def set_chapter_illustrations(self, images):
        from gi.repository import Gtk
        from .app import accessible_label, bind

        text_length = len(self.buffer.get_text(self.buffer.get_start_iter(),
                                              self.buffer.get_end_iter(), True))
        references = sorted((image for image in images
                             if 0 <= image.offset <= text_length), key=lambda image: image.offset)
        references = references[:2048]
        self._reader_image_offsets = TextImageOffsets(text_length,
                                                     [image.offset for image in references])
        for index, reference in enumerate(references):
            offset = reference.offset + index
            anchor = self.buffer.create_child_anchor(self.buffer.get_iter_at_offset(offset))
            picture = _sized_picture(can_shrink=True, content_fit=Gtk.ContentFit.CONTAIN)
            picture.set_can_target(False)
            placeholder = Gtk.Image.new_from_icon_name("image-x-generic-symbolic")
            placeholder.set_pixel_size(32)
            placeholder.add_css_class("dim-label")
            stack = Gtk.Stack()
            stack.add_named(placeholder, "placeholder")
            stack.add_named(picture, "picture")
            stack.set_visible_child_name("placeholder")
            control = Gtk.Button(child=stack, has_frame=False)
            control.add_css_class("flat")
            caption = reference.alt or _("Иллюстрация")
            accessible_label(control, caption)
            bind(control, tooltip_text=caption)
            bind(picture, alternative_text=caption)
            item = _InlineWidget(reference, anchor, control, picture, placeholder)
            control.connect("clicked", lambda _button, current=reference:
                            self.open_illustration(current))
            self.text_view.add_child_at_anchor(control, anchor)
            self._illustration_items.append(item)
            self._illustration_anchor_offsets.append(offset)
        self.update_illustration_layout()
        self.schedule_illustration_scan()

    def update_illustration_layout(self):
        if self._illustrations_closed or not self._illustration_items:
            return
        width = max(24, self.text_view.get_width() - self.text_view.get_left_margin()
                    - self.text_view.get_right_margin() - 24)
        scale = max(1, self.text_view.get_scale_factor())
        key = width, scale
        if key == self._illustration_layout_key:
            return
        self._illustration_layout_key = key
        self._illustration_resident.clear()
        for item in self._illustration_items:
            image = item.reference.image
            factor = min(1.0, width / max(1, image.width), 900 / max(1, image.height))
            logical_width = max(1, round(image.width * factor))
            logical_height = max(1, round(image.height * factor))
            item.picture.set_display_size(logical_width, logical_height)
            item.button.get_child().set_size_request(logical_width, logical_height)
            # Each thumbnail is at most 4 MP; the cache also has a total budget.
            pixel_factor = min(scale, 2048 / logical_width, 2048 / logical_height)
            item.target = (max(1, round(logical_width * pixel_factor)),
                           max(1, round(logical_height * pixel_factor)))
            item.picture.set_paintable(None)
            item.button.get_child().set_visible_child_name("placeholder")
        self.schedule_illustration_scan()

    def schedule_illustration_scan(self, *_args):
        from gi.repository import GLib

        if self._illustrations_closed or self._illustration_scan_source is not None:
            return
        self._illustration_scan_source = GLib.timeout_add(50, self._scan_illustrations)

    def _nearby_illustrations(self):
        if not self._illustration_items or not self.text_view.get_mapped():
            return []
        rectangle = self.text_view.get_visible_rect()
        positions = []
        for y in (max(0, rectangle.y - rectangle.height),
                  rectangle.y + rectangle.height * 2):
            _found, iterator, _trailing = self.text_view.get_iter_at_position(rectangle.x, y)
            positions.append(iterator.get_offset())
        first = max(0, bisect_left(self._illustration_anchor_offsets, positions[0]) - 1)
        last = min(len(self._illustration_items),
                   bisect_right(self._illustration_anchor_offsets, positions[1]) + 1)
        # Prefer the viewport's middle when tiny inline icons outnumber slots.
        _found, middle, _trailing = self.text_view.get_iter_at_position(
            rectangle.x, rectangle.y + rectangle.height // 2)
        candidates = sorted(range(first, last), key=lambda index:
                            abs(self._illustration_anchor_offsets[index] - middle.get_offset()))
        result, pixels = [], 0
        for index in candidates:
            width, height = self._illustration_items[index].target
            cost = width * height
            if pixels + cost <= self._ILLUSTRATION_MEMORY_PIXELS:
                result.append(index)
                pixels += cost
                if len(result) == self._ILLUSTRATION_RESIDENT_LIMIT:
                    break
        return result

    def _scan_illustrations(self):
        self._illustration_scan_source = None
        if self._illustrations_closed:
            return False
        nearby = self._nearby_illustrations()
        keep = set(nearby)
        for index in tuple(self._illustration_resident):
            if index not in keep:
                self._evict_illustration(index)
        state = self._illustration_viewer_state
        if state is not None and not state["requested"]:
            if len(self._illustration_running) < self._ILLUSTRATION_WORKERS:
                state["requested"] = True
                self._decode_illustration(("viewer", self._illustration_viewer_generation),
                                          state["image"], 4096, 4096)
        for index in nearby:
            if len(self._illustration_running) >= self._ILLUSTRATION_WORKERS:
                break
            item = self._illustration_items[index]
            request = ("inline", self._illustration_generation, index, item.target)
            if (item.failed or index in self._illustration_resident
                    or request in self._illustration_running.values()):
                continue
            self._decode_illustration(request, item.reference.image, *item.target)
        return False

    def _decode_illustration(self, request, image, width, height):
        from gi.repository import GLib

        future = self._illustration_executor.submit(decode_illustration, image, width, height)
        self._illustration_running[future] = request
        host = weakref.ref(self)

        def completed(result):
            owner = host()
            if owner is not None and not owner._illustrations_closed:
                GLib.idle_add(owner._finish_illustration, result)

        future.add_done_callback(completed)

    def _finish_illustration(self, future):
        from gi.repository import Gdk
        from .app import accessible_label, bind

        request = self._illustration_running.pop(future, None)
        if request is None or self._illustrations_closed:
            return False
        try:
            pixbuf = future.result()
        except Exception:
            pixbuf = None
        if request[0] == "viewer":
            if request[1] == self._illustration_viewer_generation:
                state = self._illustration_viewer_state
                if state is not None:
                    if pixbuf is not None:
                        state["picture"].set_paintable(Gdk.Texture.new_for_pixbuf(pixbuf))
                    else:
                        bind(self._illustration_viewer, title=_("Иллюстрация недоступна"))
        elif request[1] == self._illustration_generation:
            index, target = request[2:]
            item = self._illustration_items[index]
            if item.target == target:
                if pixbuf is None:
                    item.failed = True
                    item.placeholder.set_from_icon_name("image-missing-symbolic")
                    accessible_label(item.button, _("Иллюстрация недоступна"))
                    bind(item.button, tooltip_text=_("Иллюстрация недоступна"))
                elif index in self._nearby_illustrations():
                    pixels = pixbuf.get_width() * pixbuf.get_height()
                    while self._illustration_resident and (
                            sum(self._illustration_resident.values()) + pixels
                            > self._ILLUSTRATION_MEMORY_PIXELS):
                        self._evict_illustration(next(iter(self._illustration_resident)))
                    item.picture.set_paintable(Gdk.Texture.new_for_pixbuf(pixbuf))
                    item.button.get_child().set_visible_child_name("picture")
                    self._illustration_resident[index] = pixels
        self.schedule_illustration_scan()
        return False

    def _evict_illustration(self, index):
        self._illustration_resident.pop(index, None)
        item = self._illustration_items[index]
        item.picture.set_paintable(None)
        item.button.get_child().set_visible_child_name("placeholder")

    def open_illustration(self, reference):
        from gi.repository import Adw, Gdk, Gtk
        from .app import accessible_label, bind

        if self._illustrations_closed:
            return
        self._close_illustration_viewer()
        window = Adw.Window(transient_for=self, modal=True, default_width=960, default_height=720)
        bind(window, title=_("Иллюстрация"))
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)
        picture = _sized_picture(can_shrink=True, content_fit=Gtk.ContentFit.CONTAIN,
                                 halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        bind(picture, alternative_text=reference.alt or _("Иллюстрация"))
        scroller = Gtk.ScrolledWindow(has_frame=False)
        scroller.set_child(picture)
        toolbar.set_content(scroller)
        window.set_content(toolbar)
        percentage = Gtk.Label(label="100 %")
        header.pack_end(percentage)
        state = {"image": reference.image, "picture": picture, "scroller": scroller,
                 "zoom": 1.0, "fit": True, "size": None, "requested": False,
                 "percentage": percentage, "tick": None}
        self._illustration_viewer = window
        self._illustration_viewer_state = state
        for icon, caption, callback in (
                ("zoom-out-symbolic", _("Уменьшить"), lambda *_: self._zoom_illustration(1 / 1.25)),
                ("zoom-in-symbolic", _("Увеличить"), lambda *_: self._zoom_illustration(1.25)),
                ("zoom-fit-best-symbolic", _("По размеру окна"), self._fit_illustration)):
            control = Gtk.Button(icon_name=icon)
            bind(control, tooltip_text=caption)
            accessible_label(control, caption)
            control.connect("clicked", callback)
            header.pack_start(control)

        def key_pressed(_controller, keyval, _keycode, modifiers):
            if keyval == Gdk.KEY_Escape:
                window.close()
                return True
            if modifiers & (Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SUPER_MASK):
                return False
            if keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
                self._zoom_illustration(1.25)
            elif keyval in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
                self._zoom_illustration(1 / 1.25)
            elif keyval in (Gdk.KEY_0, Gdk.KEY_KP_0):
                self._fit_illustration()
            else:
                return False
            return True

        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", key_pressed)
        window.add_controller(controller)
        window.connect("close-request", self._illustration_viewer_closed)
        state["tick"] = scroller.add_tick_callback(self._illustration_viewer_tick)
        window.present()
        self.schedule_illustration_scan()

    def _zoom_illustration(self, factor):
        state = self._illustration_viewer_state
        if state is not None:
            state["fit"] = False
            state["zoom"] = min(8.0, max(0.02, state["zoom"] * factor))
            self._size_illustration_viewer()

    def _fit_illustration(self, *_args):
        if self._illustration_viewer_state is not None:
            self._illustration_viewer_state["fit"] = True
            self._size_illustration_viewer()

    def _illustration_viewer_tick(self, widget, _clock):
        state = self._illustration_viewer_state
        if state is None:
            return False
        size = widget.get_width(), widget.get_height()
        if size != state["size"]:
            state["size"] = size
            self._size_illustration_viewer()
        return True

    def _size_illustration_viewer(self):
        state = self._illustration_viewer_state
        if state is None:
            return
        image, scroller = state["image"], state["scroller"]
        if state["fit"]:
            state["zoom"] = min(1.0, max(1, scroller.get_width() - 24) / max(1, image.width),
                                max(1, scroller.get_height() - 24) / max(1, image.height))
        zoom = state["zoom"]
        state["picture"].set_display_size(min(32768, max(1, round(image.width * zoom))),
                                          min(32768, max(1, round(image.height * zoom))))
        state["percentage"].set_label(f"{round(zoom * 100)} %")

    def _illustration_viewer_closed(self, window):
        state = self._illustration_viewer_state
        if window is self._illustration_viewer:
            if state is not None and state["tick"] is not None:
                state["scroller"].remove_tick_callback(state["tick"])
            self._illustration_viewer_generation += 1
            self._illustration_viewer = None
            self._illustration_viewer_state = None
        return False

    def _close_illustration_viewer(self):
        window = self._illustration_viewer
        if window is not None:
            self._illustration_viewer_closed(window)
            window.destroy()

    def close_illustration_ui(self):
        from gi.repository import GLib

        self._illustrations_closed = True
        if self._illustration_scan_source is not None:
            GLib.source_remove(self._illustration_scan_source)
            self._illustration_scan_source = None
        adjustment = self.reader_scroll.get_vadjustment()
        for handler in self._illustration_adjustment_handlers:
            adjustment.disconnect(handler)
        self.clear_chapter_illustrations()
        for future in self._illustration_running:
            future.cancel()
        self._illustration_running.clear()
        self._illustration_executor.shutdown(wait=False, cancel_futures=True)
