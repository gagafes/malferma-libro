"""Small, lazy cover images with a bounded background queue.

This module imports no GTK objects until a widget is requested. File access,
archive extraction, networking and image decoding stay off the GTK thread.
"""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import monotonic
import weakref

from .covers import CoverCache, extract_cover, load_thumbnail
from .live_i18n import localized as _, localized_join
from .tasks import OperationToken, TaskCancelled


@dataclass(frozen=True)
class _CoverRequest:
    key: tuple
    cache_key: str
    path: str = ""
    url: str = ""
    book_id: str = ""
    persistent: bool = False


class CoverUIMixin:
    COVER_WIDTH = 64
    COVER_HEIGHT = 88
    _COVER_WORKERS = 2
    _COVER_PENDING_LIMIT = 32
    _COVER_MEMORY_LIMIT = 64
    _COVER_NEGATIVE_LIMIT = 512

    def init_cover_ui(self):
        self._covers_closed = False
        self._cover_generation = 0
        self._cover_scan_source = None
        self._cover_scan_iterator = None
        self._cover_scan_visible = None
        self._cover_rescan_requested = False
        self._cover_targets = weakref.WeakKeyDictionary()
        self._cover_scrollers = weakref.WeakKeyDictionary()
        self._cover_pending = OrderedDict()
        self._cover_running = {}
        self._cover_memory = OrderedDict()
        self._cover_negative = OrderedDict()
        self._cover_remote_locks = OrderedDict()
        self._cover_lock = Lock()
        try:
            self._cover_cache = CoverCache(self.library.root / "covers")
        except (OSError, ValueError):
            self._cover_cache = None
        self._cover_executor = ThreadPoolExecutor(max_workers=self._COVER_WORKERS,
                                                  thread_name_prefix="book-cover")

    def cover_thumbnail(self, record=None):
        """Create one fixed-size placeholder; a mapped visible row loads lazily."""
        from gi.repository import Gio, Gtk

        stack = Gtk.Stack(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        stack.set_hexpand(False)
        stack.set_vexpand(False)
        stack.set_size_request(self.COVER_WIDTH, self.COVER_HEIGHT)
        stack.set_can_target(False)
        stack.set_focusable(False)
        icon = Gtk.Image.new_from_gicon(Gio.ThemedIcon.new_from_names([
            "accessories-dictionary-symbolic", "accessories-dictionary",
            "text-x-generic-symbolic"]))
        icon.set_pixel_size(28)
        icon.set_hexpand(True)
        icon.add_css_class("dim-label")
        placeholder = Gtk.Box(halign=Gtk.Align.FILL, valign=Gtk.Align.FILL)
        placeholder.set_size_request(self.COVER_WIDTH, self.COVER_HEIGHT)
        placeholder.set_halign(Gtk.Align.CENTER)
        placeholder.set_valign(Gtk.Align.CENTER)
        placeholder.append(icon)
        picture = Gtk.Picture(can_shrink=True, content_fit=Gtk.ContentFit.CONTAIN)
        picture.set_can_target(False)
        stack.add_named(placeholder, "placeholder")
        stack.add_named(picture, "cover")
        stack.set_visible_child_name("placeholder")
        stack.cover_picture = picture
        stack.cover_request = None
        stack.cover_loaded = False
        stack.cover_finished = False
        stack.cover_caption = None
        self._set_cover_accessibility(stack)
        host = weakref.ref(self)

        def mapped(widget):
            owner = host()
            if owner is not None and not owner._covers_closed:
                owner._watch_cover_scrollers(widget)
                owner.schedule_cover_scan()
                # The first map may precede the initial allocation. One frame
                # is enough; there is no permanent animation/polling callback.
                widget.add_tick_callback(lambda *_args: owner._cover_first_frame())

        stack.connect("map", mapped)
        if record is not None:
            self.set_cover_record(stack, record)
        return stack

    def set_cover_record(self, widget, record):
        book_id = str(record["id"])
        request = _CoverRequest(("book", book_id), book_id,
                                path=str(record.get("path", "")), book_id=book_id)
        self._set_cover_request(widget, request)
        title = record.get("title", "")
        widget.cover_caption = _("Обложка книги «{title}»").format(title=title)
        self._set_cover_accessibility(widget)

    def catalog_cover_widget(self, entry):
        widget = self.cover_thumbnail()
        url = getattr(entry, "cover_url", None)
        if url:
            self._set_cover_request(widget, _CoverRequest(("remote", url), "opds:" + url, url=url))
        widget.cover_caption = _("Обложка книги «{title}»").format(title=entry.title)
        self._set_cover_accessibility(widget)
        return widget

    @staticmethod
    def _set_cover_accessibility(widget):
        from .app import accessible_label, bind

        caption = widget.cover_caption
        if not widget.cover_loaded:
            unavailable = _("Обложка недоступна")
            caption = localized_join(" · ", (caption, unavailable)) if caption else unavailable
        accessible_label(widget, caption)
        bind(widget, tooltip_text=caption)

    def _set_cover_request(self, widget, request):
        if widget.cover_request == request:
            return
        widget.cover_request = request
        widget.cover_finished = False
        widget.cover_loaded = False
        widget.cover_picture.set_paintable(None)
        widget.set_visible_child_name("placeholder")
        self._set_cover_accessibility(widget)
        self._cover_targets[widget] = request
        cached = self._cover_memory.get(request.key)
        if cached is not None and self._cover_target_visible(widget):
            self._apply_cover(widget, request, cached)
        else:
            self.schedule_cover_scan()

    def _cover_first_frame(self):
        self.schedule_cover_scan()
        return False

    def _watch_cover_scrollers(self, widget):
        from gi.repository import Gtk

        ancestor = widget.get_parent()
        host = weakref.ref(self)
        while ancestor is not None:
            if isinstance(ancestor, Gtk.ScrolledWindow) and ancestor not in self._cover_scrollers:
                def changed(*_args):
                    owner = host()
                    if owner is not None:
                        owner.schedule_cover_scan()
                adjustment = ancestor.get_vadjustment()
                self._cover_scrollers[ancestor] = (adjustment,
                    adjustment.connect("value-changed", changed),
                    adjustment.connect("changed", changed))
            ancestor = ancestor.get_parent()

    def schedule_cover_scan(self, *_args):
        from gi.repository import GLib

        if self._covers_closed:
            return
        if self._cover_scan_source is not None or self._cover_scan_iterator is not None:
            self._cover_rescan_requested = True
            return
        self._cover_scan_source = GLib.idle_add(self._scan_visible_covers,
                                               priority=GLib.PRIORITY_DEFAULT_IDLE)

    @staticmethod
    def _cover_bounds(widget, relative_to):
        result = widget.compute_bounds(relative_to)
        if isinstance(result, tuple):
            return result[1] if result[0] else None
        return result

    def _cover_target_visible(self, widget):
        from gi.repository import Gtk

        if (not widget.get_mapped() or widget.get_root() is not self
                or widget.get_width() <= 0 or widget.get_height() <= 0):
            return False
        try:
            bounds = self._cover_bounds(widget, self)
            if bounds is None:
                return False
            left, top = bounds.get_x(), bounds.get_y()
            right, bottom = left + bounds.get_width(), top + bounds.get_height()
            if right <= 0 or bottom <= 0 or left >= self.get_width() or top >= self.get_height():
                return False
            ancestor = widget.get_parent()
            while ancestor is not None:
                if isinstance(ancestor, Gtk.ScrolledWindow):
                    clip = self._cover_bounds(ancestor, self)
                    if (clip is None or right <= clip.get_x() or bottom <= clip.get_y()
                            or left >= clip.get_x() + clip.get_width()
                            or top >= clip.get_y() + clip.get_height()):
                        return False
                ancestor = ancestor.get_parent()
            return True
        except (TypeError, RuntimeError):
            return False

    def _scan_visible_covers(self):
        from gi.repository import GLib

        self._cover_scan_source = None
        if self._covers_closed or self._cover_cache is None:
            return False
        if self._cover_scan_iterator is None:
            self._cover_scan_iterator = iter(list(self._cover_targets.items()))
            self._cover_scan_visible = OrderedDict()
            self._cover_rescan_requested = False
        started = monotonic()
        finished = False
        # A large library must not turn every scroll event into one long GTK
        # callback. Release offscreen textures and discover visible work in
        # short slices; each visible target is inspected/applied only once.
        for processed in range(64):
            if processed and monotonic() - started >= 0.004:
                break
            try:
                widget, request = next(self._cover_scan_iterator)
            except StopIteration:
                finished = True
                break
            if self._cover_targets.get(widget) != request:
                continue
            shown = self._cover_target_visible(widget)
            if not shown and widget.cover_loaded:
                widget.cover_picture.set_paintable(None)
                widget.set_visible_child_name("placeholder")
                widget.cover_loaded = False
                widget.cover_finished = False
                self._set_cover_accessibility(widget)
            if not widget.cover_finished and shown:
                self._cover_scan_visible[request.key] = request
                cached = self._cover_memory.get(request.key)
                if cached is not None:
                    self._apply_cover(widget, request, cached)
                elif (request.key not in self._cover_running and request.key not in self._cover_pending
                      and len(self._cover_pending) < self._COVER_PENDING_LIMIT):
                    self._cover_pending[request.key] = request
        if finished:
            for key, request in list(self._cover_pending.items()):
                if not request.persistent and key not in self._cover_scan_visible:
                    del self._cover_pending[key]
            self._cover_scan_iterator = None
            self._cover_scan_visible = None
        self._start_cover_jobs()
        if not finished:
            self._cover_scan_source = GLib.idle_add(self._scan_visible_covers,
                                                    priority=GLib.PRIORITY_DEFAULT_IDLE)
        elif self._cover_rescan_requested:
            self._cover_rescan_requested = False
            self.schedule_cover_scan()
        return False

    def _start_cover_jobs(self):
        from gi.repository import GLib

        while (not self._covers_closed and self._cover_pending
               and len(self._cover_running) < self._COVER_WORKERS):
            key, request = self._cover_pending.popitem(last=False)
            token = OperationToken()
            generation = self._cover_generation
            future = self._cover_executor.submit(self._load_cover_request, request, token)
            self._cover_running[key] = (token, future)
            host = weakref.ref(self)

            def finished(result, job=request, epoch=generation):
                owner = host()
                if owner is not None and not owner._covers_closed:
                    GLib.idle_add(owner._deliver_cover, job, epoch, result)
            future.add_done_callback(finished)

    def _negative_cover(self, key, signature):
        with self._cover_lock:
            self._cover_negative[key] = signature
            self._cover_negative.move_to_end(key)
            while len(self._cover_negative) > self._COVER_NEGATIVE_LIMIT:
                self._cover_negative.popitem(last=False)

    def _remote_cover(self, url, token):
        from .opds import download_cover

        key = "opds:" + url
        with self._cover_lock:
            lock = self._cover_remote_locks.setdefault(url, Lock())
            self._cover_remote_locks.move_to_end(url)
            while len(self._cover_remote_locks) > self._COVER_MEMORY_LIMIT:
                self._cover_remote_locks.popitem(last=False)
        with lock:
            token.check()
            cover = self._cover_cache.load(key)
            if cover is not None:
                return cover
            with self._cover_lock:
                if key in self._cover_negative:
                    return None
            try:
                cover = download_cover(url, token=token)
            except TaskCancelled:
                raise
            except Exception:
                cover = None
            token.check()
            if cover is not None:
                self._cover_cache.store(key, cover)
            else:
                self._negative_cover(key, None)
            return cover

    def _load_cover_request(self, request, token):
        token.check()
        cover = self._cover_cache.load(request.cache_key)
        if cover is None and request.url:
            cover = self._remote_cover(request.url, token)
            token.check()
            if cover is not None and request.book_id:
                # A concurrent import may have produced a better embedded
                # cover while the optional remote fallback was downloading.
                cover = self._cover_cache.load(request.book_id) or cover
                token.check()
                self._cover_cache.store(request.book_id, cover)
        elif cover is None and request.path:
            try:
                stat = Path(request.path).stat()
                signature = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                signature = None
            with self._cover_lock:
                seen = (request.cache_key in self._cover_negative
                        and self._cover_negative[request.cache_key] == signature)
            if not seen:
                token.check()
                cover = extract_cover(request.path)
                token.check()
                if cover is not None:
                    self._cover_cache.store(request.cache_key, cover)
                else:
                    self._negative_cover(request.cache_key, signature)
        token.check()
        return load_thumbnail(cover, self.COVER_WIDTH * 4, self.COVER_HEIGHT * 4) if cover else None

    def _deliver_cover(self, request, generation, future):
        if self._covers_closed or generation != self._cover_generation:
            return False
        self._cover_running.pop(request.key, None)
        try:
            thumbnail = future.result()
        except Exception:
            thumbnail = None
        # Association jobs have their own queue key so they cannot disappear
        # behind a running legacy extraction. Their result belongs to the
        # corresponding library-book widget/cache key.
        display_key = (("book", request.book_id) if request.persistent else request.key)
        if thumbnail is not None:
            self._cover_memory[display_key] = thumbnail
            self._cover_memory.move_to_end(display_key)
            while len(self._cover_memory) > self._COVER_MEMORY_LIMIT:
                self._cover_memory.popitem(last=False)
        for widget, target in list(self._cover_targets.items()):
            if target.key == display_key:
                image = self._cover_memory.get(display_key, thumbnail)
                if image is None or self._cover_target_visible(widget):
                    self._apply_cover(widget, target, image)
                else:
                    widget.cover_finished = False
        self._start_cover_jobs()
        self.schedule_cover_scan()
        return False

    def _apply_cover(self, widget, request, thumbnail):
        if self._covers_closed or widget.cover_request != request:
            return
        widget.cover_finished = True
        if thumbnail is None:
            self._set_cover_accessibility(widget)
            return
        from gi.repository import Gdk
        from .app import DocumentPaintable

        # Gtk.Picture otherwise requests the texture's physical width as its
        # natural logical width. Keep a 4x raster without growing the row.
        ratio = min(self.COVER_WIDTH / thumbnail.get_width(),
                    self.COVER_HEIGHT / thumbnail.get_height())
        width = max(1, round(thumbnail.get_width() * ratio))
        height = max(1, round(thumbnail.get_height() * ratio))
        texture = Gdk.Texture.new_for_pixbuf(thumbnail)
        widget.cover_picture.set_paintable(DocumentPaintable(texture, width, height))
        widget.set_visible_child_name("cover")
        widget.cover_loaded = True
        self._set_cover_accessibility(widget)

    def remember_catalog_cover(self, record, cover_url):
        """Associate an optional OPDS image without delaying opening the book."""
        if self._covers_closed or self._cover_cache is None or not cover_url:
            return
        book_id = str(record["id"])
        # Replace an unstarted local-extraction request. An already running
        # extraction is allowed to finish, then the association retries below.
        key = ("association", book_id)
        if key in self._cover_running or key in self._cover_pending:
            return
        request = _CoverRequest(key, book_id, url=cover_url,
                                book_id=book_id, persistent=True)
        if len(self._cover_pending) >= self._COVER_PENDING_LIMIT:
            for pending_key, pending in list(self._cover_pending.items())[::-1]:
                if not pending.persistent:
                    del self._cover_pending[pending_key]
                    break
            else:
                return
        self._cover_pending[key] = request
        self._start_cover_jobs()

    def close_cover_ui(self):
        from gi.repository import GLib

        if self._covers_closed:
            return
        self._covers_closed = True
        self._cover_generation += 1
        if self._cover_scan_source is not None:
            GLib.source_remove(self._cover_scan_source)
            self._cover_scan_source = None
        self._cover_scan_iterator = None
        self._cover_scan_visible = None
        self._cover_pending.clear()
        for token, future in self._cover_running.values():
            token.cancel()
            future.cancel()
        self._cover_running.clear()
        for adjustment, *handlers in list(self._cover_scrollers.values()):
            for handler in handlers:
                adjustment.disconnect(handler)
        self._cover_scrollers.clear()
        self._cover_targets.clear()
        self._cover_memory.clear()
        self._cover_executor.shutdown(wait=False, cancel_futures=True)
