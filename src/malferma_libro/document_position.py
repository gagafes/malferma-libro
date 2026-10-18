"""Retain a document position while GTK reallocates an older page image.

An allocation can clamp the old scrollbar to zero before the new raster is
ready. Keep the last stable fraction until restoration finishes, unless the
reader deliberately scrolls in the meantime. This state is independent of GTK
so the resize and input ordering can be checked without a display.
"""


class DocumentPosition:
    def __init__(self):
        self.reset()

    def reset(self, offset: int = 0) -> None:
        self._geometry = None
        self._offset = offset
        self._pending = False

    def current(self, geometry: tuple[int, int, int], visible_offset: int) -> int:
        if self._geometry is None:
            self._geometry = geometry
        elif geometry != self._geometry:
            # The scrollbar may already have been clamped for this allocation.
            # Never replace a valid old fraction with that temporary value.
            self._pending = True
        if not self._pending:
            self._offset = visible_offset
        return self._offset

    def hold(self, geometry: tuple[int, int, int], visible_offset: int) -> int:
        offset = self.current(geometry, visible_offset)
        self._pending = True
        return offset

    def user_input(self, geometry: tuple[int, int, int], visible_offset: int) -> None:
        """Let intentional scrolling supersede any older resize snapshot."""
        self.restored(geometry, visible_offset)

    def restored(self, geometry: tuple[int, int, int], visible_offset: int) -> None:
        """Accept the stable allocation after the replacement was positioned."""
        self._geometry = geometry
        self._offset = visible_offset
        self._pending = False
