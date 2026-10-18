"""Conservative, display-scale independent mouse navigation recognition.

Coordinates are GTK logical coordinates.  The caller owns mouse-button and
widget-boundary handling; this recognizer never consumes a click or selects
text.  It returns a navigation step only after the user releases the button.
"""

from math import hypot, isfinite


class GestureNavigation:
    """Recognize one deliberate horizontal drag per press/release sequence."""

    def __init__(self, threshold: float = 80.0, axis_ratio: float = 1.5):
        if not isfinite(threshold) or threshold <= 0:
            raise ValueError("The drag threshold must be finite and positive")
        if not isfinite(axis_ratio) or axis_ratio < 1:
            raise ValueError("The horizontal axis ratio must be finite and at least one")
        self.threshold = threshold
        self.axis_ratio = axis_ratio
        self._origin: tuple[float, float] | None = None

    def begin(self, x: float, y: float) -> None:
        self.cancel()
        if isfinite(x) and isfinite(y):
            self._origin = (x, y)

    def update(self, x: float, y: float) -> None:
        if self._origin is None:
            return
        if not isfinite(x) or not isfinite(y):
            self.cancel()
            return
        dx, dy = x - self._origin[0], y - self._origin[1]
        # Once a substantial vertical or diagonal motion has established a
        # different intention, returning toward the horizontal cannot turn it
        # into a page change at release.
        if hypot(dx, dy) >= self.threshold and abs(dx) < self.axis_ratio * abs(dy):
            self.cancel()

    def finish(self, x: float, y: float) -> int:
        self.update(x, y)
        if self._origin is None:
            return 0
        dx, dy = x - self._origin[0], y - self._origin[1]
        self.cancel()
        if abs(dx) < self.threshold or abs(dx) < self.axis_ratio * abs(dy):
            return 0
        return 1 if dx < 0 else -1

    def cancel(self) -> None:
        self._origin = None
