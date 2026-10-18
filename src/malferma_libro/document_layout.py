"""Separate document layout in GTK units from bounded raster resolution.

PDF and DjVu renderers already limit each decoded page to 4096 pixels on its
longest edge and 12 MiPixels.  Those limits must not change the size of the
page in the reader: an 8K viewport can display a bounded raster over a larger
logical area.  GTK's monitor scale affects raster density, never reading zoom.
This module knows neither GTK nor a particular document backend.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


# This bounds GTK allocations and scroll adjustments for pathological page
# shapes, rather than decoded image memory. It is far above desktop sizes,
# including an 8K viewport at the reader's maximum 300% reading zoom.
MAX_LOGICAL_DIMENSION = 1_000_000


@dataclass(frozen=True)
class PageLayout:
    logical_width: int
    logical_height: int
    raster_fit_width: int
    raster_scale: float


def _positive_number(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite positive number")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"{name} must be a finite positive number") from error
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return result


def page_layout(
    page_width: float,
    page_height: float,
    *,
    fit_width: int,
    zoom: float = 1.0,
    device_scale: float = 1.0,
) -> PageLayout:
    """Plan one page without allocating its raster or consulting the display.

    ``fit_width`` is the available width in GTK logical units before reading
    zoom. The returned ``raster_*`` fields can be passed directly to either
    backend's ``render_page`` method. Display the resulting image through a
    paintable whose intrinsic dimensions are ``logical_*``; using the PNG's
    pixel dimensions for layout would apply monitor scaling twice.

    Device scale may be fractional for callers with a fractional-scale API;
    Gtk.Widget.get_scale_factor() currently supplies integer scale factors.
    Backend raster caps remain authoritative, even when the physical request
    exceeds them. Extremely elongated pages are uniformly reduced to the
    logical allocation limit, while still retaining the same bounded raster
    request.
    """
    width = _positive_number(page_width, "page_width")
    height = _positive_number(page_height, "page_height")
    if isinstance(fit_width, bool) or not isinstance(fit_width, int) or fit_width <= 0:
        raise ValueError("fit_width must be a positive integer")
    reading_zoom = _positive_number(zoom, "zoom")
    density = _positive_number(device_scale, "device_scale")
    raster_scale = reading_zoom * density
    if not math.isfinite(raster_scale) or raster_scale <= 0:
        raise ValueError("zoom multiplied by device_scale must be finite and positive")

    # Normalize first: an otherwise valid PDF can contain finite dimensions
    # with an aspect ratio that overflows ordinary width/height multiplication.
    longest = max(width, height)
    normalized_width, normalized_height = width / longest, height / longest
    try:
        requested_width = fit_width * reading_zoom
    except OverflowError:
        requested_width = math.inf
    desired_longest = (
        requested_width / normalized_width if normalized_width > 0 else math.inf
    )
    logical_longest = min(MAX_LOGICAL_DIMENSION, desired_longest)
    return PageLayout(
        logical_width=max(1, round(logical_longest * normalized_width)),
        logical_height=max(1, round(logical_longest * normalized_height)),
        raster_fit_width=fit_width,
        raster_scale=raster_scale,
    )
