"""Real cancellation and observer behavior without a GTK dependency.

SPDX-License-Identifier: GPL-3.0-or-later
"""

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import URLError

from malferma_libro.native_process import native_process_cancellation, run_native_command
from malferma_libro.tasks import OperationToken, TaskCancelled, check_cancel, error_category


class OperationTokenTests(unittest.TestCase):
    def test_cancel_is_idempotent_and_late_observers_are_not_lost(self):
        token = OperationToken()
        observed = []
        token.add_cancel_callback(lambda: observed.append("first"))
        self.assertTrue(token.cancel())
        self.assertFalse(token.cancel())
        token.add_cancel_callback(lambda: observed.append("late"))
        self.assertEqual(observed, ["first", "late"])
        with self.assertRaises(TaskCancelled):
            token.check()

    def test_detached_and_failed_observers_do_not_break_operations(self):
        token = OperationToken()
        observed = []
        detach = token.add_progress_callback(lambda *value: observed.append(value))
        detach()
        detach()

        def failed_observer(*_value):
            raise RuntimeError("The observer has been destroyed")

        token.add_progress_callback(failed_observer)
        token.add_progress_callback(lambda *value: observed.append(value))
        token.progress(3, 5)
        self.assertEqual(observed, [(3, 5)])
        self.assertEqual(token.progress_value, (3, 5))
        token.cancel()
        token.progress(5, 5)
        self.assertEqual(token.progress_value, (3, 5))

    def test_observers_may_unsubscribe_and_read_token_without_deadlocking(self):
        token = OperationToken()
        observed = []

        def observer():
            observed.append(token.progress_value)
            detach()

        detach = token.add_cancel_callback(observer)
        token.progress(1, 2)
        with ThreadPoolExecutor(max_workers=1) as workers:
            self.assertTrue(workers.submit(token.cancel).result(timeout=2))
        self.assertEqual(observed, [(1, 2)])

    def test_token_raising_checkpoint_and_boolean_probe_share_cancellation(self):
        token = OperationToken()
        for cancel in (None, token, token.check, lambda: False):
            check_cancel(cancel)
        token.cancel()
        for cancel in (token, token.check, lambda: True):
            with self.subTest(cancel=cancel), self.assertRaises(TaskCancelled):
                check_cancel(cancel)

    def test_error_classification_handles_wrappers_and_cause_cycles(self):
        wrapped = ValueError("Could not import")
        wrapped.__cause__ = PermissionError("Access denied")
        self.assertEqual(error_category(wrapped), "permission")
        wrapped.__cause__ = FileNotFoundError("Missing book")
        self.assertEqual(error_category(wrapped), "missing")
        wrapped.__cause__ = URLError("Offline")
        self.assertEqual(error_category(wrapped), "network")
        wrapped.__cause__ = wrapped
        self.assertEqual(error_category(wrapped), "other")


class NativeProcessTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.pid_file = Path(temporary.name) / "helper.pid"
        self.command = [sys.executable, "-c", (
            "import os, pathlib, sys, time; "
            "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); "
            "time.sleep(30)"
        ), str(self.pid_file)]

    def run_helper(self, token, timeout=5):
        with native_process_cancellation(token):
            return run_native_command(self.command, timeout=timeout, stdin=subprocess.DEVNULL,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def wait_for_pid(self):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if self.pid_file.exists() and (value := self.pid_file.read_text()):
                return int(value)
            time.sleep(0.01)
        self.fail("The real helper process did not start")

    def assert_reaped(self, pid):
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_cancelled_operation_never_starts_helper(self):
        token = OperationToken()
        token.cancel()
        with self.assertRaises(TaskCancelled):
            self.run_helper(token)
        self.assertFalse(self.pid_file.exists())

    def test_cancellation_stops_and_reaps_running_helper(self):
        token = OperationToken()
        with ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(self.run_helper, token)
            try:
                pid = self.wait_for_pid()
            finally:
                token.cancel()
            with self.assertRaises(TaskCancelled):
                future.result(timeout=2)
        self.assert_reaped(pid)

    def test_timeout_stops_and_reaps_running_helper(self):
        token = OperationToken()
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_helper(token, timeout=1)
        self.assert_reaped(int(self.pid_file.read_text()))

    def test_scope_restores_cancellation_after_exception(self):
        token = OperationToken()
        with self.assertRaises(RuntimeError):
            with native_process_cancellation(token):
                raise RuntimeError("Operation failed")
        token.cancel()
        result = run_native_command([sys.executable, "-c", "pass"], timeout=2, check=True)
        self.assertEqual(result.returncode, 0)

    def test_scoped_helpers_reject_unread_pipes_and_preserve_exit_status(self):
        with native_process_cancellation(OperationToken()):
            with self.assertRaises(ValueError):
                run_native_command(self.command, timeout=2, stdout=subprocess.PIPE)
            with self.assertRaises(subprocess.CalledProcessError) as caught:
                run_native_command([sys.executable, "-c", "raise SystemExit(7)"],
                                   timeout=2, check=True)
        self.assertEqual(caught.exception.returncode, 7)
        self.assertFalse(self.pid_file.exists())


if __name__ == "__main__":
    unittest.main()
