"""Toolkit-independent reading keys and logical-pixel scroll calculations.

SPDX-License-Identifier: GPL-3.0-or-later
"""

from dataclasses import dataclass
import math
from typing import Iterable

from .shortcuts import N_


@dataclass(frozen=True)
class NavigationShortcut:
    action: str
    accelerator: str
    title: str
    key_name: str
    modifiers: frozenset[str] = frozenset()


NAVIGATION_SHORTCUTS = (
    NavigationShortcut("line-up", "Up", N_("Прокрутить вверх"), "Up"),
    NavigationShortcut("line-down", "Down", N_("Прокрутить вниз"), "Down"),
    NavigationShortcut("page-up", "Page_Up", N_("На экран вверх"), "Page_Up"),
    NavigationShortcut("page-down", "Page_Down", N_("На экран вниз"), "Page_Down"),
    NavigationShortcut("turn-previous", "Left", N_("Предыдущая страница"), "Left"),
    NavigationShortcut("turn-next", "Right", N_("Следующая страница"), "Right"),
    NavigationShortcut("start", "Home", N_("Начало главы или страницы"), "Home"),
    NavigationShortcut("end", "End", N_("Конец главы или страницы"), "End"),
    NavigationShortcut("book-start", "<Control>Home", N_("Начало книги"),
                       "Home", frozenset({"control"})),
    NavigationShortcut("book-end", "<Control>End", N_("Конец книги"),
                       "End", frozenset({"control"})),
)

_ALIASES = {
    "Prior": "Page_Up",
    "Next": "Page_Down",
    "KP_Up": "Up",
    "KP_Down": "Down",
    "KP_Left": "Left",
    "KP_Right": "Right",
    "KP_Prior": "Page_Up",
    "KP_Next": "Page_Down",
    "KP_Page_Up": "Page_Up",
    "KP_Page_Down": "Page_Down",
    "KP_Home": "Home",
    "KP_End": "End",
}
_ACTIONS = {
    (shortcut.key_name, shortcut.modifiers): shortcut.action
    for shortcut in NAVIGATION_SHORTCUTS
}


def navigation_for(key_name: str, modifiers: Iterable[str] = ()) -> str | None:
    """Resolve only reading navigation keys, preserving modified native input.

    The GTK adapter is responsible for reading focus and for removing lock
    modifiers. Shift, Alt, Super and other active modifiers are not ignored.
    Numeric keypad digits with Num Lock enabled remain ordinary input.
    """
    return _ACTIONS.get((_ALIASES.get(key_name, key_name), frozenset(modifiers)))


def _finite(value: float, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    return number if math.isfinite(number) else fallback


def scroll_target(action: str, value: float, lower: float, upper: float,
                  page_size: float, step_increment: float) -> float:
    """Return a valid Gtk.Adjustment value without applying a monitor scale.

    Page movement keeps ten percent of the viewport visible for orientation.
    Before layout has measured a viewport, page movement falls back to one
    line step. Invalid or transient geometry cannot produce NaN or infinity.
    Chapter/book transitions are deliberately left to the caller.
    """
    if action not in {"line-up", "line-down", "page-up", "page-down", "start", "end"}:
        raise ValueError(f"Unsupported scroll action: {action}")

    minimum = _finite(lower, 0.0)
    maximum = max(minimum, _finite(upper, minimum))
    viewport = max(0.0, _finite(page_size, 0.0))
    maximum = max(minimum, maximum - viewport)
    current = min(maximum, max(minimum, _finite(value, minimum)))
    step = _finite(step_increment, 40.0)
    if step <= 0.0:
        step = 40.0
    page = viewport * 0.9 if viewport > 0.0 else step

    if action == "start":
        return minimum
    if action == "end":
        return maximum
    distance = step if action.startswith("line-") else page
    target = current + (-distance if action.endswith("-up") else distance)
    return min(maximum, max(minimum, target))
