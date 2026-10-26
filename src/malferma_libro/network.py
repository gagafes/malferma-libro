"""Streaming HTTP with a cancellable lifetime, including DNS and headers.

urllib's socket timeout is an inactivity timeout, not a transfer deadline.
Keep blocking resolver/socket work in a disposable process; the owning worker
polls its pipe and reaps it on cancellation, timeout, or early response close.
"""

from __future__ import annotations

from http.client import IncompleteRead
import json
import math
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError

from .native_process import _stop_process_group
from .tasks import check_cancel


_POLL_SECONDS = 0.05
_MAX_METADATA_BYTES = 16 * 1024
_MAX_TRANSFER_BYTES = 512 * 1024 * 1024
_WORKER = Path(__file__).with_name("network_worker.py")


class _NetworkResponse:
    def __init__(self, request, *, policy, limit, cancel, socket_timeout, total_timeout):
        if (policy not in {"opds", "voice"} or type(limit) is not int
                or not 0 < limit <= _MAX_TRANSFER_BYTES
                or not math.isfinite(socket_timeout) or not 0 < socket_timeout <= 60
                or not math.isfinite(total_timeout) or not 0 < total_timeout <= 3600):
            raise ValueError("Invalid HTTP transfer budget")
        self._cancel, self._limit = cancel, limit
        self._deadline = time.monotonic() + total_timeout
        self._process = self._errors = self._selector = None
        self._buffer = b""
        self._received = 0
        self._eof = self._closed = False
        self._url = request.full_url
        try:
            self._checkpoint()
            # URLs may contain private query parameters. Keep request metadata
            # out of argv, environment variables and world-readable files.
            with tempfile.TemporaryFile() as source:
                source.write(json.dumps({
                    "url": request.full_url, "headers": dict(request.header_items()),
                    "policy": policy, "limit": limit, "timeout": socket_timeout,
                }).encode("utf-8"))
                source.seek(0)
                self._errors = tempfile.TemporaryFile()
                self._process = subprocess.Popen(
                    [sys.executable, "-I", str(_WORKER)], stdin=source,
                    stdout=subprocess.PIPE, stderr=self._errors, start_new_session=True,
                )
            os.set_blocking(self._process.stdout.fileno(), False)
            self._selector = selectors.DefaultSelector()
            self._selector.register(self._process.stdout, selectors.EVENT_READ)
            metadata = bytearray()
            while b"\n" not in metadata:
                chunk = self._read_pipe()
                if not chunk:
                    raise URLError("Missing HTTP response metadata")
                metadata.extend(chunk)
                if len(metadata.split(b"\n", 1)[0]) > _MAX_METADATA_BYTES:
                    raise URLError("HTTP response metadata exceeded its bounds")
            line, self._buffer = bytes(metadata).split(b"\n", 1)
            result = json.loads(line)
            self._url = result["url"]
            self.headers = result["headers"]
            self.status = result["status"]
        except BaseException:
            self.close()
            raise

    def _checkpoint(self):
        check_cancel(self._cancel)
        if time.monotonic() >= self._deadline:
            raise TimeoutError("HTTP transfer deadline exceeded")

    def _finish(self):
        while self._process.poll() is None:
            self._checkpoint()
            try:
                self._process.wait(timeout=min(_POLL_SECONDS, max(0, self._deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                pass
        self._checkpoint()
        if self._process.returncode:
            self._errors.seek(0)
            try:
                error = json.loads(self._errors.read(4096))
            except (ValueError, UnicodeError):
                error = {}
            if error.get("kind") == "http":
                raise HTTPError(self._url, error["code"], "HTTP error", {}, None)
            if error.get("kind") == "incomplete":
                raise IncompleteRead(b"")
            if error.get("kind") == "timeout":
                raise TimeoutError("HTTP socket timeout")
            raise URLError(error.get("message", "HTTP worker failed"))
        self._eof = True

    def _read_pipe(self):
        while not self._eof:
            self._checkpoint()
            remaining = self._deadline - time.monotonic()
            if not self._selector.select(min(_POLL_SECONDS, max(0, remaining))):
                continue
            chunk = os.read(self._process.stdout.fileno(), 65536)
            self._checkpoint()
            if not chunk:
                self._finish()
            return chunk
        return b""

    def read(self, size=65536):
        """Return at most one available chunk, without waiting to fill a buffer."""
        if self._closed:
            raise ValueError("Read from closed HTTP response")
        try:
            self._checkpoint()
            if size == 0:
                return b""
            if size < 0:
                raise ValueError("HTTP reads must specify a bounded size")
            if not self._buffer:
                self._buffer = self._read_pipe()
            chunk, self._buffer = self._buffer[:size], self._buffer[size:]
            self._received += len(chunk)
            if self._received > self._limit:
                raise URLError("HTTP response exceeded its byte limit")
            return chunk
        except BaseException:
            self.close()
            raise

    def geturl(self):
        return self._url

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self._process is not None:
                if self._process.poll() is None:
                    _stop_process_group(self._process)
                self._process.stdout.close()
        finally:
            if self._selector is not None:
                self._selector.close()
            if self._errors is not None:
                self._errors.close()
            self._buffer = b""

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        self.close()


def fetch_response(request, *, policy, limit, cancel=None, socket_timeout=20, total_timeout=30):
    """Open a policy-checked GET; callers must close the returned response."""
    return _NetworkResponse(request, policy=policy, limit=limit, cancel=cancel,
                            socket_timeout=socket_timeout, total_timeout=total_timeout)
