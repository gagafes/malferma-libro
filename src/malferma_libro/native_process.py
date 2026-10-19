"""Bounded, cancellable document helpers without a dependency on GTK.

An operation scope follows the current worker thread, so lazy document metadata,
text and raster calls observe the same cancellation as their owning task. No
signal handler or process wait runs in the thread which requests cancellation.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from .tasks import check_cancel


_CURRENT_CANCELLATION = ContextVar("document_process_cancellation", default=None)
_POLL_SECONDS = 0.05


@contextmanager
def native_process_cancellation(cancel):
    """Apply a task's cancellation to native helpers in this worker only."""
    previous = _CURRENT_CANCELLATION.set(cancel)
    try:
        check_cancel(cancel)
        yield
    finally:
        _CURRENT_CANCELLATION.reset(previous)


def _stop_process_group(process):
    # Helpers are isolated in their own session. Kill descendants too: waiting
    # on only the leader can leave a decoder running after the window closes.
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass
    finally:
        process.wait()


def run_native_command(command, *, timeout, **kwargs):
    """Run a file-backed document helper, stopping it when its task is cancelled.

    Callers must direct stdout/stderr to files or DEVNULL rather than PIPE;
    polling a process with unread pipes could deadlock on a full pipe buffer.
    POSIX helpers run with inherited file-size/address-space limits. A private
    launcher applies those limits without unsafe preexec_fn calls in GTK.
    Calls outside an operation scope keep subprocess.run's usual contract.
    """
    cancel = _CURRENT_CANCELLATION.get()
    if kwargs.get("shell"):
        raise ValueError("Document helpers must run without a shell")
    original_command = command
    if os.name == "posix":
        command = [sys.executable, "-I", str(Path(__file__).with_name("native_limits.py")),
                   *command]
    if cancel is None:
        try:
            result = subprocess.run(command, timeout=timeout, **kwargs)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            error.cmd = original_command
            raise
        return subprocess.CompletedProcess(original_command, result.returncode,
                                           result.stdout, result.stderr)
    check_cancel(cancel)
    if any(kwargs.get(name) == subprocess.PIPE for name in ("stdin", "stdout", "stderr")):
        raise ValueError("Document helper streams must be file-backed")
    check = kwargs.pop("check", False)
    kwargs["start_new_session"] = True
    process = subprocess.Popen(command, **kwargs)
    deadline = time.monotonic() + timeout
    try:
        while True:
            check_cancel(cancel)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(original_command, timeout)
            try:
                result = process.wait(timeout=min(_POLL_SECONDS, remaining))
            except subprocess.TimeoutExpired:
                continue
            check_cancel(cancel)
            if check and result:
                raise subprocess.CalledProcessError(result, original_command)
            return subprocess.CompletedProcess(original_command, result)
    except BaseException:
        _stop_process_group(process)
        raise
