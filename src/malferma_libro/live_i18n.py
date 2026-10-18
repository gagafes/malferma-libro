"""Source-aware live translations without depending on a GUI toolkit.

Only text explicitly marked by ``localized`` is translated. Book metadata,
search input and server-provided text remain ordinary strings, even when they
happen to equal a translated application message.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any
from weakref import WeakKeyDictionary, WeakSet

from .i18n import _ as gettext


def render(value: Any) -> Any:
    return value.render() if isinstance(value, (LocalizedText, _LocalizedSequence)) else value


class LocalizedText(str):
    """A normal string that also retains the recipe for its next translation."""

    def __new__(cls, recipe: Callable[[], str]):
        item = super().__new__(cls, recipe())
        item._recipe = recipe
        return item

    def render(self) -> str:
        return self._recipe()

    def format(self, *args, **kwargs) -> LocalizedText:
        return LocalizedText(lambda: self.render().format(
            *(render(item) for item in args),
            **{key: render(item) for key, item in kwargs.items()},
        ))

    def __add__(self, other: str) -> LocalizedText:
        if not isinstance(other, str):
            return NotImplemented
        return LocalizedText(lambda: self.render() + render(other))

    def __radd__(self, other: str) -> LocalizedText:
        if not isinstance(other, str):
            return NotImplemented
        return LocalizedText(lambda: render(other) + self.render())


def localized(source: str) -> LocalizedText:
    return LocalizedText(lambda: gettext(source))


def localized_join(separator: str, values: Iterable[str]) -> LocalizedText:
    values = tuple(values)
    return LocalizedText(lambda: separator.join(render(value) for value in values))


class _LocalizedSequence:
    def __init__(self, values):
        self.values = tuple(values)

    def render(self):
        return tuple(render(value) for value in self.values)


class TranslationBindings:
    """Weak bindings keep removed library/catalog rows eligible for collection.

Setters receive the widget as their first argument; they must not close over
it. This also works with non-widget models such as Gtk.StringList and Gio.Menu.
"""

    def __init__(self):
        self._bindings: WeakKeyDictionary[Any, dict[str, tuple[Any, Any]]] = WeakKeyDictionary()
        self._leading_labels: WeakSet[Any] = WeakSet()

    @staticmethod
    def _set_property(target, name, value):
        target.set_property(name.replace("_", "-"), value)

    def bind(self, target, **properties):
        for name, value in properties.items():
            self.bind_value(target, name, value,
                            lambda item, text, prop=name: self._set_property(item, prop, text))
        return target

    def bind_value(self, target, name, value, setter):
        """Replace or clear a binding, including when content becomes plain text."""
        # PyGObject uses toggle references to retain wrappers with Python state
        # while the native parent owns the object. This matters for models and
        # for labels that are otherwise referenced only by their GTK parent.
        target._reader_live_translation = True
        bindings = self._bindings.setdefault(target, {})
        if isinstance(value, (LocalizedText, _LocalizedSequence)):
            bindings[name] = (value, setter)
        else:
            bindings.pop(name, None)
        setter(target, render(value))
        if not bindings:
            self._bindings.pop(target, None)
        return target

    def bind_sequence(self, target, name, values, setter):
        values = tuple(values)
        if any(isinstance(item, LocalizedText) for item in values):
            # A sequence is intentionally rendered by its setter, rather than
            # flattened into a string and losing individual source messages.
            return self.bind_value(target, name, _LocalizedSequence(values), setter)
        return self.bind_value(target, name, values, setter)

    def leading_label(self, target):
        target._reader_leading_label = True
        self._leading_labels.add(target)
        return target

    def refresh(self, rtl=False):
        for target, bindings in list(self._bindings.items()):
            for value, setter in tuple(bindings.values()):
                setter(target, render(value))
        for target in list(self._leading_labels):
            target.set_xalign(1 if rtl else 0)
