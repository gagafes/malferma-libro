"""Cooperative background cancellation and progress without a GUI dependency.

Cancellation prevents future work; it cannot undo an already published file or
library transaction. Callers check at their own safe transaction boundaries.
"""

from __future__ import annotations

import logging
import math
from threading import Event, Lock
from urllib.error import URLError


LOG = logging.getLogger(__name__)


def error_category(error):
    """Classify wrapped file/network failures without following cause cycles."""
    chain, seen = [], set()
    while isinstance(error, BaseException) and id(error) not in seen and len(chain) < 16:
        chain.append(error)
        seen.add(id(error))
        error = error.__cause__
    for category, kinds in (("network", (URLError, TimeoutError, ConnectionError)),
                            ("missing", (FileNotFoundError,)),
                            ("permission", (PermissionError,))):
        if any(isinstance(item, kinds) for item in chain):
            return category
    return "other"


class TaskCancelled(Exception):
    """The caller requested cancellation at a cooperative checkpoint."""


class OperationToken:
    """Thread-safe cancellation and latest progress for one operation.

Observers run in the publishing thread, outside the token lock. A GUI observer
must marshal its updates to the main loop. Registering a cancel observer after
cancellation still notifies it, so a fast worker cannot lose that notification.
"""

    def __init__(self):
        self._cancelled = Event()
        self._lock = Lock()
        self._progress = (0, None)
        self._cancel_callbacks = []
        self._progress_callbacks = []

    @property
    def cancelled(self):
        return self._cancelled.is_set()

    @property
    def progress_value(self):
        with self._lock:
            return self._progress

    def check(self):
        if self.cancelled:
            raise TaskCancelled()

    @staticmethod
    def _notify(callbacks, *arguments):
        for callback in callbacks:
            try:
                callback(*arguments)
            except Exception:
                # A detached UI observer cannot fail the underlying operation
                # or prevent the remaining observers from seeing cancellation.
                LOG.debug("Background-operation observer failed", exc_info=True)

    def cancel(self):
        with self._lock:
            if self._cancelled.is_set():
                return False
            self._cancelled.set()
            callbacks = tuple(self._cancel_callbacks)
        self._notify(callbacks)
        return True

    def progress(self, done, total=None):
        """Publish nonnegative work units; ``None`` means an unknown total."""
        if not isinstance(done, (int, float)) or not math.isfinite(done) or done < 0:
            raise ValueError("Progress must be a finite, nonnegative number")
        if total is not None and (
            not isinstance(total, (int, float)) or not math.isfinite(total) or total < 0
        ):
            raise ValueError("Progress total must be finite and nonnegative")
        with self._lock:
            if self._cancelled.is_set():
                return
            self._progress = (done, total)
            callbacks = tuple(self._progress_callbacks)
        self._notify(callbacks, done, total)

    def _subscribe(self, callbacks, callback):
        with self._lock:
            callbacks.append(callback)
        def unsubscribe():
            with self._lock:
                if callback in callbacks:
                    callbacks.remove(callback)
        return unsubscribe

    def add_progress_callback(self, callback):
        return self._subscribe(self._progress_callbacks, callback)

    def add_cancel_callback(self, callback):
        with self._lock:
            cancelled = self._cancelled.is_set()
            if not cancelled:
                self._cancel_callbacks.append(callback)
        if cancelled:
            self._notify((callback,))
        def unsubscribe():
            with self._lock:
                if callback in self._cancel_callbacks:
                    self._cancel_callbacks.remove(callback)
        return unsubscribe


def check_cancel(cancel):
    """Accept a token, a raising checkpoint, or a boolean cancellation probe."""
    if cancel is None:
        return
    checker = getattr(cancel, "check", None)
    if checker is not None:
        checker()
    elif cancel():
        raise TaskCancelled()


def report_progress(cancel, done, total=None):
    publisher = getattr(cancel, "progress", None)
    if publisher is not None:
        publisher(done, total)
