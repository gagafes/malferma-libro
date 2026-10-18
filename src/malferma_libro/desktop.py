"""Desktop-native file selection through xdg-desktop-portal.

There are no GI imports at module load time, so URI and protocol handling can
also be checked without a display.  A caller supplies its existing GTK chooser
as a fallback for sessions without a working portal.
"""

from __future__ import annotations

import os
import importlib
from pathlib import Path
import re
import uuid
from urllib.parse import unquote_to_bytes, urlsplit

from .i18n import _


BOOK_EXTENSIONS = ("epub", "fb2", "fb2.zip", "txt", "pdf", "djvu", "djv", "html", "htm", "xhtml", "md", "markdown", "cbz")
BOOK_FILTER_NAME = "Книги (EPUB, FB2, FB2.ZIP, TXT, PDF, DjVu, HTML, Markdown, CBZ)"
BOOK_FILTERS = (
    (BOOK_FILTER_NAME, tuple((0, "*." + extension) for item in BOOK_EXTENSIONS for extension in (item, item.upper()))),
)


def book_filter_name() -> str:
    return _("Книги (EPUB, FB2, FB2.ZIP, TXT, PDF, DjVu, HTML, Markdown, CBZ)")


def book_filters() -> tuple:
    return ((book_filter_name(), BOOK_FILTERS[0][1]),)


_PORTAL_NAME = "org.freedesktop.portal.Desktop"
_PORTAL_PATH = "/org/freedesktop/portal/desktop"
_CHOOSER_INTERFACE = "org.freedesktop.portal.FileChooser"
_REQUEST_INTERFACE = "org.freedesktop.portal.Request"
_INVALID_ESCAPE = re.compile(r"%(?![0-9a-fA-F]{2})")


def file_uri_to_path(uri: str) -> Path | None:
    """Decode a local file URI once, retaining spaces and non-ASCII names.

    Remote hosts, URI fragments and query strings do not name local files.
    Existence and supported book contents are checked by the importer, so this
    function does not follow symlinks or change the selected filesystem object.
    """
    if not isinstance(uri, str) or any(ord(char) < 32 or ord(char) == 127 for char in uri) or _INVALID_ESCAPE.search(uri):
        return None
    try:
        parts = urlsplit(uri)
    except ValueError:
        return None
    if parts.scheme.casefold() != "file" or parts.netloc.casefold() not in ("", "localhost"):
        return None
    if parts.query or parts.fragment or not parts.path.startswith("/"):
        return None
    raw = unquote_to_bytes(parts.path)
    if b"\x00" in raw:
        return None
    return Path(os.fsdecode(raw))


def response_paths(response: int, results: dict) -> list[Path]:
    """Return only local selections from a successful portal response."""
    if type(response) is not int or response != 0 or not isinstance(results, dict):
        return []
    uris = results.get("uris", ())
    if not isinstance(uris, (list, tuple)):
        return []
    paths = []
    seen = set()
    for uri in uris:
        path = file_uri_to_path(uri)
        if path is not None and path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def request_path(unique_bus_name: str, token: str) -> str:
    """Predict the portal request path before calling OpenFile."""
    sender = unique_bus_name.removeprefix(":").replace(".", "_")
    if not re.fullmatch(r"[A-Za-z0-9_]+", sender) or not re.fullmatch(r"[A-Za-z0-9_]+", token):
        raise ValueError("Invalid D-Bus sender or request token")
    return f"{_PORTAL_PATH}/request/{sender}/{token}"


def _load_gi():
    from gi.repository import Gio, GLib

    return Gio, GLib


class PortalFileChooser:
    """One asynchronous, cancellable portal selection with a single fallback.

    ``on_files`` receives ``list[Path]`` on successful local selection;
    ``fallback`` opens the caller's Gtk.FileChooserNative if the service is
    unavailable or reports an error.  User cancellation never opens a second
    dialog.  Both callbacks run on the GLib main loop.
    """

    @property
    def active(self):
        """Whether a portal request still owns an interactive selection."""
        return self._opened and not self._finished

    def __init__(self, parent, on_files, fallback):
        self.parent = parent
        self.on_files = on_files
        self.fallback = fallback
        self._opened = False
        self._finished = False
        self._cancelled = False
        self._aborted = False
        self._connection = None
        self._subscription = None
        self._owner_subscription = None
        self._request_path = None
        self._expected_path = None
        self._early_responses = {}
        self._parent_ready = False
        self._parent_handle = ""
        self._parent_surface = None
        self._parent_export_handle = None
        self._parent_timeout = None
        self._ack_timeout = None
        self._cancellable = None
        self._token = "openbook_" + uuid.uuid4().hex

    def open(self):
        if self._opened or self._finished:
            return
        self._opened = True
        try:
            self._gio, self._glib = _load_gi()
            self._cancellable = self._gio.Cancellable()
            self._prepare_parent()
        except Exception:
            self._fail()

    def cancel(self):
        if self._finished:
            return
        self._cancelled = True
        self._aborted = True
        path = self._request_path or self._expected_path
        self._finish()
        if path:
            self._close_request(path)

    def _prepare_parent(self):
        """Export a Wayland handle where supported, without blocking GTK."""
        try:
            surface = self.parent.get_surface()
        except Exception:
            surface = None
        if surface is not None:
            # Importing a backend namespace exposes its surface methods in GI.
            # A session may only have one of these namespaces installed.
            for namespace in ("GdkX11", "GdkWayland"):
                try:
                    import gi

                    gi.require_version(namespace, "4.0")
                    importlib.import_module("gi.repository." + namespace)
                except (ImportError, AttributeError, ValueError):
                    pass
            get_xid = getattr(surface, "get_xid", None)
            if callable(get_xid):
                try:
                    xid = get_xid()
                    if xid:
                        self._parent_handle = f"x11:{xid:x}"
                        self._parent_prepared()
                        return
                except Exception:
                    pass
            export = getattr(surface, "export_handle", None)
            if callable(export):
                self._parent_surface = surface
                self._parent_timeout = self._glib.timeout_add(1500, self._parent_export_expired)
                try:
                    if export(self._parent_exported, None):
                        return
                except Exception:
                    pass
                self._release_parent()
        self._parent_prepared()

    def _parent_exported(self, surface, handle, _data=None):
        valid_handle = isinstance(handle, str) and bool(handle)
        if self._finished or self._parent_ready:
            # export_handle cannot be cancelled.  A timeout or window closure
            # can precede its callback, and the newly received token must still
            # be dropped instead of becoming an untracked Wayland resource.
            if valid_handle:
                self._drop_parent_handle(surface, handle)
            return
        if valid_handle:
            self._parent_export_handle = handle
            self._parent_handle = "wayland:" + handle
        self._parent_prepared()

    def _parent_export_expired(self):
        self._parent_timeout = None
        self._release_parent()
        self._parent_prepared()
        return False

    def _parent_prepared(self):
        if self._parent_ready or self._finished:
            return
        self._parent_ready = True
        self._remove_timeout("_parent_timeout")
        # A missing or stalled session bus must also fall back asynchronously.
        self._ack_timeout = self._glib.timeout_add(10000, self._portal_expired)
        self._gio.bus_get(self._gio.BusType.SESSION, self._cancellable, self._bus_ready, None)

    def _bus_ready(self, _source, result, _data=None):
        try:
            connection = self._gio.bus_get_finish(result)
        except Exception:
            self._fail()
            return
        if self._finished:
            return
        self._connection = connection
        try:
            self._expected_path = request_path(connection.get_unique_name(), self._token)
            # Subscribe before OpenFile: a portal can emit Response before its
            # method reply has reached us.  Legacy backends may return a path
            # other than the one predicted from handle_token.
            self._subscription = connection.signal_subscribe(
                _PORTAL_NAME, _REQUEST_INTERFACE, "Response", None, None,
                self._gio.DBusSignalFlags.NONE, self._response, None,
            )
            # Once OpenFile is acknowledged there is no deadline: the user
            # may keep the dialog open indefinitely. If the portal exits,
            # however, its outstanding request can never emit Response.
            self._owner_subscription = connection.signal_subscribe(
                "org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
                "/org/freedesktop/DBus", _PORTAL_NAME,
                self._gio.DBusSignalFlags.NONE, self._portal_owner_changed, None,
            )
            options = {
                "handle_token": self._glib.Variant("s", self._token),
                "multiple": self._glib.Variant("b", True),
                "modal": self._glib.Variant("b", True),
                "accept_label": self._glib.Variant("s", _("Добавить")),
                "filters": self._glib.Variant("a(sa(us))", book_filters()),
            }
            connection.call(
                _PORTAL_NAME, _PORTAL_PATH, _CHOOSER_INTERFACE, "OpenFile",
                self._glib.Variant("(ssa{sv})", (self._parent_handle, _("Открыть книги"), options)),
                self._glib.VariantType.new("(o)"), self._gio.DBusCallFlags.NONE,
                # Keep the short acknowledgement alive after window closure:
                # older portals can ignore handle_token, so its actual path
                # must still be received and closed by _opened_request.
                10000, None, self._opened_request, None,
            )
        except Exception:
            self._fail()

    def _opened_request(self, connection, result, _data=None):
        try:
            (path,) = connection.call_finish(result).unpack()
        except Exception:
            self._fail()
            return
        if self._finished:
            if self._aborted:
                self._close_request(path)
            return
        if not isinstance(path, str) or not path.startswith(_PORTAL_PATH + "/request/"):
            self._fail()
            return
        self._request_path = path
        self._remove_timeout("_ack_timeout")
        early = self._early_responses.pop(path, None)
        self._early_responses.clear()
        if early is not None:
            self._handle_response(early)

    def _response(self, _connection, _sender, path, _interface, _signal, parameters, _data=None):
        if self._finished:
            return
        if path in (self._expected_path, self._request_path):
            self._handle_response(parameters)
        elif self._request_path is None and len(self._early_responses) < 8:
            self._early_responses[path] = parameters

    def _portal_owner_changed(self, _connection, _sender, _path, _interface, _signal, parameters, _data=None):
        if self._finished:
            return
        name, previous, current = parameters.unpack()
        if name == _PORTAL_NAME and previous and previous != current:
            self._fail()

    def _handle_response(self, parameters):
        try:
            response, results = parameters.unpack()
            if type(response) is not int or not isinstance(results, dict):
                raise ValueError("Invalid FileChooser response")
        except Exception:
            self._fail()
            return
        if response == 0:
            paths = response_paths(response, results)
            self._finish()
            if paths:
                self.on_files(paths)
        elif response == 1:
            self._finish()
        else:
            self._fail()

    def _portal_expired(self):
        self._ack_timeout = None
        self._fail()
        return False

    def _close_request(self, path):
        if self._connection is None:
            return
        try:
            self._connection.call(
                _PORTAL_NAME, path, _REQUEST_INTERFACE, "Close", None, None,
                self._gio.DBusCallFlags.NO_AUTO_START, 1000, None, None, None,
            )
        except Exception:
            pass

    def _remove_timeout(self, attribute):
        source = getattr(self, attribute)
        if source is not None:
            setattr(self, attribute, None)
            self._glib.source_remove(source)

    def _release_parent(self):
        self._remove_timeout("_parent_timeout")
        handle = self._parent_export_handle
        self._parent_export_handle = None
        if handle is not None:
            self._drop_parent_handle(self._parent_surface, handle)

    @staticmethod
    def _drop_parent_handle(surface, handle):
        try:
            # Since GTK 4.12 each export has its own token.  unexport_handle()
            # is a no-op there; older GTK releases only have the legacy API.
            drop = getattr(surface, "drop_exported_handle", None)
            if callable(drop):
                drop(handle)
            else:
                surface.unexport_handle()
        except Exception:
            pass

    def _finish(self):
        if self._finished:
            return
        self._finished = True
        if self._subscription is not None:
            self._connection.signal_unsubscribe(self._subscription)
            self._subscription = None
        if self._owner_subscription is not None:
            self._connection.signal_unsubscribe(self._owner_subscription)
            self._owner_subscription = None
        if self._cancellable is not None:
            self._cancellable.cancel()
        self._remove_timeout("_ack_timeout")
        self._release_parent()
        self._early_responses.clear()

    def _fail(self):
        if self._finished:
            return
        self._aborted = True
        path = self._request_path or self._expected_path
        self._finish()
        if path:
            self._close_request(path)
        if not self._cancelled:
            self.fallback()
