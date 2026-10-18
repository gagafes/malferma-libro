"""Reader colours and bundled fonts, usable without GTK or a display."""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import math
import os
from pathlib import Path

from .i18n import N_


LOG = logging.getLogger(__name__)

# Both labels and CSS values come from this closed list: saved settings never
# become arbitrary CSS. The default generic face remains available on systems
# where fontconfig cannot register the bundled fonts.
FONT_FAMILIES = {
    # Translators: shared by font and interface-language choices; keep it neutral.
    "system": (N_("Системный"), "serif"),
    "notoserif": ("Noto Serif", '"Noto Serif", "Noto Naskh Arabic", "Noto Serif Hebrew", "Noto Serif Ethiopic", serif'),
    "notosans": ("Noto Sans", '"Noto Sans", "Noto Sans Arabic", "Noto Sans Hebrew", "Noto Sans Ethiopic", sans-serif'),
    "liberationserif": ("Liberation Serif", '"Liberation Serif", "Noto Naskh Arabic", "Noto Serif Hebrew", "Noto Serif Ethiopic", serif'),
}

_PALETTES = {
    "light": ("#faf9f6", "#242424"),
    "sepia": ("#f1e4cc", "#493b2c"),
    "dark": ("#24282d", "#e8e5df"),
}
_FONT_DIRECTORY = Path(__file__).parent / "assets" / "fonts"
_LATIN_FONT_FILES = ("NotoSerif-Regular.ttf", "NotoSans-Regular.ttf", "LiberationSerif-Regular.ttf")
_SCRIPT_FONT_FILES = ("NotoNaskhArabic-Regular.ttf", "NotoSansArabic-Regular.ttf",
                      "NotoSerifHebrew-Regular.ttf", "NotoSansHebrew-Regular.ttf",
                      "NotoSerifEthiopic-Regular.ttf", "NotoSansEthiopic-Regular.ttf")
_FONT_FILES = _LATIN_FONT_FILES + _SCRIPT_FONT_FILES


def font_css(key: str) -> str:
    """Return a trusted CSS font-family value, falling back to Noto Serif."""
    if not isinstance(key, str) or key not in FONT_FAMILIES:
        key = "notoserif"
    return FONT_FAMILIES[key][1]


def reader_theme(key: str, desktop_dark: bool) -> str:
    """Resolve the book page palette without changing the application theme.

    The desktop preference is supplied by the caller independently of a forced
    light or dark application window. A saved page choice therefore survives
    changes to the surrounding interface.
    """
    if isinstance(key, str) and key in _PALETTES:
        return key
    return "dark" if desktop_dark else "light"


def _brightness(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 1.0
    try:
        result = float(value)
    except OverflowError:
        return 1.0
    if not math.isfinite(result):
        return 1.0
    return max(0.3, min(1.0, result))


def _dim(colour: str, brightness: float) -> str:
    # Work in linear light instead of scaling sRGB bytes: 50% brightness means
    # half the emitted luminance and retains the intended colour balance.
    channels = []
    for offset in (1, 3, 5):
        encoded = int(colour[offset : offset + 2], 16) / 255.0
        linear = encoded / 12.92 if encoded <= 0.04045 else ((encoded + 0.055) / 1.055) ** 2.4
        linear *= brightness
        encoded = 12.92 * linear if linear <= 0.0031308 else 1.055 * linear ** (1 / 2.4) - 0.055
        channels.append(round(encoded * 255))
    return "#" + "".join(f"{channel:02x}" for channel in channels)


def reader_colors(theme: str, brightness: float, high_contrast: bool = False) -> tuple[str, str]:
    """Return page background and text colours at a clamped page brightness.

    The caller resolves the system theme to light or dark. Unknown theme keys
    use the light palette. This changes the reader only, never hardware screen
    brightness or colours in other applications. High contrast uses pure white
    and black, independent of page dimming, to retain maximum text contrast.
    The saved palette and brightness remain available when it is disabled.
    """
    if high_contrast is True:
        return ("#000000", "#ffffff") if theme == "dark" else ("#ffffff", "#000000")
    palette = _PALETTES.get(theme, _PALETTES["light"]) if isinstance(theme, str) else _PALETTES["light"]
    amount = _brightness(brightness)
    return _dim(palette[0], amount), _dim(palette[1], amount)


def register_fonts() -> bool:
    """Register packaged fonts with the current process before Pango starts.

    Fontconfig application fonts are process-local. No files are installed in
    the user's font directory and no system font cache is modified. Missing
    fontconfig or font files leave GTK's ordinary font fallback available.
    """
    try:
        library_path = ctypes.util.find_library("fontconfig")
        if not library_path:
            LOG.warning("Fontconfig is unavailable; using system font fallbacks")
            return False
        fontconfig = ctypes.CDLL(library_path)
        fontconfig.FcConfigGetCurrent.argtypes = []
        fontconfig.FcConfigGetCurrent.restype = ctypes.c_void_p
        fontconfig.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        fontconfig.FcConfigAppFontAddFile.restype = ctypes.c_int
        fontconfig.FcConfigBuildFonts.argtypes = [ctypes.c_void_p]
        fontconfig.FcConfigBuildFonts.restype = ctypes.c_int
        config = fontconfig.FcConfigGetCurrent()
        if not config:
            LOG.warning("Fontconfig could not open its current configuration")
            return False
        success = True
        for filename in _FONT_FILES:
            path = _FONT_DIRECTORY / filename
            if not path.is_file() or not fontconfig.FcConfigAppFontAddFile(config, os.fsencode(path)):
                LOG.warning("Could not register bundled reader font: %s", path)
                success = False
        if not fontconfig.FcConfigBuildFonts(config):
            LOG.warning("Fontconfig could not rebuild application fonts")
            return False
        return success
    except (AttributeError, OSError, ValueError):
        LOG.warning("Bundled fonts could not be registered; using system font fallbacks", exc_info=True)
        return False
