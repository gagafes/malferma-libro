"""Observe desktop appearance without deriving it from a forced Adwaita theme.

Gio is imported only when a monitor starts, so helpers and fallback behaviour
remain usable without GTK, a display, or a session bus.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Callable


LOG = logging.getLogger(__name__)
_NAMESPACE = "org.freedesktop.appearance"
_KEY = "color-scheme"
_PORTAL_NAME = "org.freedesktop.portal.Desktop"
_PORTAL_PATH = "/org/freedesktop/portal/desktop"
_PORTAL_INTERFACE = "org.freedesktop.portal.Settings"
_XFCONF_NAME = "org.xfce.Xfconf"
_XFCONF_PATH = "/org/xfce/Xfconf"
_XFCONF_CHANNEL = "xsettings"
_XFCONF_THEME = "/Net/ThemeName"
_GNOME_SESSIONS = frozenset(("gnome", "gnome-classic", "gnome-flashback", "unity", "pantheon"))


def uses_gnome_desktop_settings(current_desktop: object) -> bool:
    """Whether this session actually owns GNOME's desktop preference.

Having GNOME schemas installed is insufficient on KDE, Xfce or Cinnamon:
their values can belong to another login session and must not override GTK.
    """
    if not isinstance(current_desktop, str):
        return False
    tokens = {token.strip().casefold() for token in current_desktop.split(":")}
    return bool(tokens & _GNOME_SESSIONS)


def theme_dark_preference(value: object) -> bool | None:
    """Read a native theme name, including a D-Bus variant GetProperty reply."""
    for _ in range(8):
        if isinstance(value, (tuple, list)) and len(value) == 1:
            value = value[0]
        elif hasattr(value, "unpack"):
            try:
                value = value.unpack()
            except (TypeError, ValueError, AttributeError):
                return None
        else:
            break
    if not isinstance(value, str) or not value.strip():
        return None
    name = value.strip().casefold()
    if name.startswith("adwaita-empty"):
        return None
    return bool(re.search(r"(?:^|[-_\s])(?:dark|black|night)(?:$|[-_\s])", name)) or name in (
        "highcontrastinverse", "highcontrast-inverse",
    )


def portal_dark_preference(value: object) -> bool | None:
    """Decode a portal Read reply or variant; 0 means no preference.

Read returns ``(v)``, while SettingChanged supplies the inner variant. Reject
booleans, unknown values and malformed replies instead of guessing a theme.
    """
    for _ in range(8):
        if isinstance(value, (tuple, list)) and len(value) == 1:
            value = value[0]
        elif hasattr(value, "unpack"):
            try:
                value = value.unpack()
            except (TypeError, ValueError, AttributeError):
                return None
        else:
            break
    if type(value) is int:
        return {1: True, 2: False}.get(value)
    return None


def _load_gio():
    from gi.repository import Gio, GLib

    return Gio, GLib


class DesktopAppearance:
    """Watch the portal, then session-appropriate GSettings and GTK settings.

The caller must create this before forcing its own interface colour scheme.
``initial_dark`` is the initial system Adwaita preference, used where a desktop
does not expose an independent setting. Internal ``Adwaita-empty`` changes are
ignored because they describe libadwaita's styling, not the desktop theme.
Cinnamon's native theme comes from its own GSettings schema, and Xfce's from
an asynchronous Xfconf observer; neither depends on GTK's overwritten name.
Callbacks run on the Gio/GTK main context and only when the preference changes.
    """

    def __init__(self, settings: object, on_change: Callable[[bool], None], *, initial_dark: bool = False):
        self._settings = settings
        self._on_change = on_change
        self._closed = False
        self._gio = self._glib = None
        self._cancellable = None
        self._portal = None
        self._portal_handlers: list[int] = []
        self._xfconf = None
        self._xfconf_handlers: list[int] = []
        self._xfconf_serial = 0
        self._settings_handlers: list[int] = []
        self._gsettings = None
        self._gsettings_schema_name: str | None = None
        self._gsettings_handlers: list[int] = []
        self._gsettings_keys: tuple[str, ...] = ()
        self._portal_dark: bool | None = None
        self._desktop_dark: bool | None = None
        self._gtk_dark = bool(initial_dark)
        self._portal_serial = 0
        self._capture_gtk()
        self.dark = self._gtk_dark
        for name in ("gtk-theme-name", "gtk-application-prefer-dark-theme"):
            try:
                self._settings_handlers.append(settings.connect(f"notify::{name}", self._gtk_changed))
            except (AttributeError, TypeError, ValueError, RuntimeError):
                pass
        try:
            self._gio, self._glib = _load_gio()
            self._cancellable = self._gio.Cancellable()
        except (ImportError, ValueError, AttributeError):
            return
        self._start_gsettings()
        # Construction never calls back before the caller can retain us.
        self.dark = self._resolve()
        self._start_portal()
        self._start_xfconf()

    def _property(self, name: str, default=None):
        try:
            return self._settings.get_property(name)
        except (AttributeError, TypeError, ValueError, RuntimeError):
            return default

    def _capture_gtk(self):
        name = self._property("gtk-theme-name", "")
        name = name.casefold() if isinstance(name, str) else ""
        if name.startswith("adwaita-empty"):
            return
        preferred = self._property("gtk-application-prefer-dark-theme", False)
        dark_name = theme_dark_preference(name)
        if name or preferred is True:
            self._gtk_dark = preferred is True or dark_name

    def _resolve(self) -> bool:
        if self._portal_dark is not None:
            return self._portal_dark
        if self._desktop_dark is not None:
            return self._desktop_dark
        return self._gtk_dark

    def _publish(self):
        if self._closed:
            return
        dark = self._resolve()
        if self.dark != dark:
            self.dark = dark
            self._on_change(dark)

    def _gtk_changed(self, *_args):
        if not self._closed:
            self._capture_gtk()
            self._publish()

    def _start_gsettings(self):
        session = os.environ.get("XDG_CURRENT_DESKTOP", "")
        tokens = {token.strip().casefold() for token in session.split(":")}
        if tokens & {"cinnamon", "x-cinnamon"}:
            schema_name, keys = "org.cinnamon.desktop.interface", (_KEY, "gtk-theme")
        elif uses_gnome_desktop_settings(session):
            schema_name, keys = "org.gnome.desktop.interface", (_KEY,)
        else:
            return
        try:
            source = self._gio.SettingsSchemaSource.get_default()
            schema = source.lookup(schema_name, True) if source else None
            self._gsettings_keys = tuple(key for key in keys if schema is not None and schema.has_key(key))
            if not self._gsettings_keys:
                return
            self._gsettings = self._gio.Settings.new_full(schema, None, None)
            self._gsettings_schema_name = schema_name
            for key in self._gsettings_keys:
                self._gsettings_handlers.append(self._gsettings.connect(f"changed::{key}", self._desktop_changed))
            self._read_desktop()
        except (AttributeError, TypeError, ValueError, RuntimeError):
            LOG.debug("Desktop GSettings appearance is unavailable", exc_info=True)

    def _read_desktop(self):
        self._desktop_dark = None
        for key in self._gsettings_keys:
            try:
                value = self._gsettings.get_string(key)
            except (AttributeError, TypeError, ValueError, RuntimeError):
                continue
            preference = (
                {"prefer-dark": True, "prefer-light": False}.get(value)
                if key == _KEY else theme_dark_preference(value)
            )
            # GNOME's default tile selects the ordinary light appearance.
            # It must not retain a dark value captured before libadwaita
            # replaced Gtk.Settings with Adwaita-empty. Cinnamon's default
            # still defers to its native gtk-theme key below.
            if key == _KEY and value == "default" and self._gsettings_schema_name == "org.gnome.desktop.interface":
                preference = False
            if preference is not None:
                self._desktop_dark = preference
                return

    def _desktop_changed(self, *_args):
        if not self._closed:
            self._read_desktop()
            self._publish()

    def _start_portal(self):
        try:
            self._gio.DBusProxy.new_for_bus(
                self._gio.BusType.SESSION,
                self._gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES,
                None, _PORTAL_NAME, _PORTAL_PATH, _PORTAL_INTERFACE,
                self._cancellable, self._portal_ready,
            )
        except (AttributeError, TypeError, ValueError, RuntimeError):
            LOG.debug("Desktop settings portal is unavailable", exc_info=True)

    def _portal_ready(self, _source, result, *_args):
        try:
            portal = self._gio.DBusProxy.new_for_bus_finish(result)
        except Exception:
            # GLib.Error is optional here, and cancellation is an ordinary close.
            return
        if self._closed:
            return
        self._portal = portal
        self._portal_handlers.append(portal.connect("g-signal", self._portal_signal))
        self._portal_handlers.append(portal.connect("notify::g-name-owner", self._portal_owner_changed))
        self._read_portal()

    def _read_portal(self):
        self._portal_serial += 1
        serial = self._portal_serial
        try:
            self._portal.call(
                "Read", self._glib.Variant("(ss)", (_NAMESPACE, _KEY)),
                self._gio.DBusCallFlags.NONE, 1500, self._cancellable,
                lambda proxy, result, *_args: self._portal_read(proxy, result, serial),
            )
        except Exception:
            self._portal_dark = None
            self._publish()

    def _portal_read(self, proxy, result, serial: int):
        try:
            value = proxy.call_finish(result)
        except Exception:
            value = None
        if self._closed or serial != self._portal_serial:
            return
        self._portal_dark = portal_dark_preference(value)
        self._publish()

    def _portal_owner_changed(self, proxy, *_args):
        if self._closed:
            return
        if proxy.get_name_owner():
            self._read_portal()
        else:
            self._portal_serial += 1
            self._portal_dark = None
            self._publish()

    def _portal_signal(self, _proxy, _sender_name, signal_name, parameters):
        if self._closed or signal_name != "SettingChanged":
            return
        try:
            values = parameters.unpack()
            if not isinstance(values, (tuple, list)) or len(values) != 3:
                return
            namespace, key, value = values
            if namespace != _NAMESPACE or key != _KEY:
                return
        except (AttributeError, TypeError, ValueError):
            return
        # An in-flight initial Read must not overwrite a newer change signal.
        self._portal_serial += 1
        self._portal_dark = portal_dark_preference(value)
        self._publish()

    def _start_xfconf(self):
        # libadwaita changes Gtk.Settings to Adwaita-empty during startup, so
        # Xfce's actual theme must come from its own configuration service.
        tokens = {token.strip().casefold() for token in os.environ.get("XDG_CURRENT_DESKTOP", "").split(":")}
        if "xfce" not in tokens:
            return
        try:
            self._gio.DBusProxy.new_for_bus(
                self._gio.BusType.SESSION, self._gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES,
                None, _XFCONF_NAME, _XFCONF_PATH, _XFCONF_NAME,
                self._cancellable, self._xfconf_ready,
            )
        except (AttributeError, TypeError, ValueError, RuntimeError):
            LOG.debug("Xfce appearance service is unavailable", exc_info=True)

    def _xfconf_ready(self, _source, result, *_args):
        try:
            proxy = self._gio.DBusProxy.new_for_bus_finish(result)
        except Exception:
            return
        if self._closed:
            return
        self._xfconf = proxy
        self._xfconf_handlers.append(proxy.connect("g-signal", self._xfconf_signal))
        self._xfconf_handlers.append(proxy.connect("notify::g-name-owner", self._xfconf_owner_changed))
        self._read_xfconf()

    def _read_xfconf(self):
        self._xfconf_serial += 1
        serial = self._xfconf_serial
        try:
            self._xfconf.call(
                "GetProperty", self._glib.Variant("(ss)", (_XFCONF_CHANNEL, _XFCONF_THEME)),
                self._gio.DBusCallFlags.NONE, 1500, self._cancellable,
                lambda proxy, result, *_args: self._xfconf_read(proxy, result, serial),
            )
        except Exception:
            self._desktop_dark = None
            self._publish()

    def _xfconf_read(self, proxy, result, serial: int):
        try:
            value = proxy.call_finish(result)
        except Exception:
            value = None
        if self._closed or serial != self._xfconf_serial:
            return
        self._desktop_dark = theme_dark_preference(value)
        self._publish()

    def _xfconf_owner_changed(self, proxy, *_args):
        if self._closed:
            return
        if proxy.get_name_owner():
            self._read_xfconf()
        else:
            self._xfconf_serial += 1
            self._desktop_dark = None
            self._publish()

    def _xfconf_signal(self, _proxy, _sender_name, signal_name, parameters):
        if self._closed or signal_name not in ("PropertyChanged", "PropertyRemoved"):
            return
        try:
            values = parameters.unpack()
            length = 3 if signal_name == "PropertyChanged" else 2
            if not isinstance(values, (tuple, list)) or len(values) != length:
                return
            channel, key = values[:2]
            if channel != _XFCONF_CHANNEL or key != _XFCONF_THEME:
                return
        except (AttributeError, TypeError, ValueError):
            return
        self._xfconf_serial += 1
        self._desktop_dark = theme_dark_preference(values[2]) if length == 3 else None
        self._publish()

    def close(self):
        """Disconnect all observers and cancel pending D-Bus work, idempotently."""
        if self._closed:
            return
        self._closed = True
        if self._cancellable is not None:
            self._cancellable.cancel()
        connections = [(self._settings, handle) for handle in self._settings_handlers]
        connections += [(self._portal, handle) for handle in self._portal_handlers]
        connections += [(self._xfconf, handle) for handle in self._xfconf_handlers]
        connections += [(self._gsettings, handle) for handle in self._gsettings_handlers]
        for source, handle in connections:
            try:
                source.disconnect(handle)
            except (AttributeError, TypeError, ValueError, RuntimeError):
                pass
        self._settings_handlers.clear()
        self._portal_handlers.clear()
        self._xfconf_handlers.clear()
        self._gsettings_handlers.clear()
