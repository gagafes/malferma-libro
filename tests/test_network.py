"""Real loopback transfers remain bounded while DNS/headers/body may block.

SPDX-License-Identifier: GPL-3.0-or-later
"""

from contextlib import contextmanager
from http.client import IncompleteRead
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

from malferma_libro import network, opds
from malferma_libro.network import fetch_response
from malferma_libro.tasks import OperationToken, TaskCancelled


PAYLOAD = bytes(range(256)) * 400


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.started.set()
        if self.path == "/headers":
            self.server.stop.wait(5)
            return
        if self.path in {"/redirect", "/unsafe"}:
            self.send_response(302)
            self.send_header("Location", "/data" if self.path == "/redirect" else "ftp://example.org/book.txt")
            self.end_headers()
            return
        self.send_response(404 if self.path == "/error" else 200)
        self.send_header("Content-Type", "application/atom+xml" if self.path == "/feed" else "text/plain")
        if self.path == "/feed":
            data = b'<feed xmlns="http://www.w3.org/2005/Atom"><title>Loopback</title></feed>'
        elif self.path == "/short":
            data = b"short"
        elif self.path == "/error":
            data = b""
        else:
            data = PAYLOAD
        if self.path not in {"/trickle", "/unknown"}:
            length = len(data) + 100 if self.path == "/short" else len(data)
            self.send_header("Content-Length", str(length))
        self.end_headers()
        try:
            if self.path == "/trickle":
                while not self.server.stop.wait(0.02):
                    self.wfile.write(b"x")
                    self.wfile.flush()
            else:
                self.wfile.write(data)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


@contextmanager
def local_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    server.started, server.stop = threading.Event(), threading.Event()
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02), daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.stop.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def consume(response):
    parts = []
    while chunk := response.read(65536):
        parts.append(chunk)
    return b"".join(parts)


class NetworkTests(unittest.TestCase):
    def open(self, url, **kwargs):
        options = {"policy": "opds", "limit": len(PAYLOAD), "total_timeout": 5}
        options.update(kwargs)
        return fetch_response(Request(url), **options)

    def test_streamed_body_redirect_and_http_errors(self):
        with local_server() as (_server, base):
            for path in ("/data", "/redirect"):
                with self.open(base + path) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.geturl(), base + "/data")
                    self.assertEqual(consume(response), PAYLOAD)
                    process = response._process
                self.assertEqual(process.returncode, 0)
                self.assertTrue(process.stdout.closed)
            with self.assertRaises(HTTPError) as caught:
                self.open(base + "/error")
            self.assertEqual(caught.exception.code, 404)
            caught.exception.close()
            with self.assertRaises(URLError):
                self.open(base + "/unsafe")

    def test_byte_limit_with_and_without_length_and_truncated_body(self):
        with local_server() as (_server, base):
            for path in ("/data", "/unknown"):
                with self.subTest(path=path), self.assertRaises(URLError):
                    with self.open(base + path, limit=64) as response:
                        consume(response)
            with self.assertRaises(IncompleteRead):
                with self.open(base + "/short") as response:
                    consume(response)

    def test_absolute_deadline_covers_headers_and_continuous_trickle(self):
        with local_server() as (_server, base):
            for path in ("/headers", "/trickle"):
                start = time.monotonic()
                real_popen = subprocess.Popen
                processes = []
                def launch(*args, **kwargs):
                    process = real_popen(*args, **kwargs)
                    processes.append(process)
                    return process
                with self.subTest(path=path), patch.object(network.subprocess, "Popen", side_effect=launch):
                    with self.assertRaises(TimeoutError):
                        with self.open(base + path, total_timeout=0.35, socket_timeout=2) as response:
                            consume(response)
                self.assertLess(time.monotonic() - start, 1.5)
                self.assertEqual(len(processes), 1)
                self.assertIsNotNone(processes[0].poll())
                self.assertTrue(processes[0].stdout.closed)

    def test_cancellation_during_headers_or_trickle_reaps_child(self):
        for path in ("/headers", "/trickle"):
            with self.subTest(path=path), local_server() as (server, base):
                token, processes, outcome = OperationToken(), [], []
                real_popen = subprocess.Popen
                def launch(*args, **kwargs):
                    process = real_popen(*args, **kwargs)
                    processes.append(process)
                    return process
                def transfer():
                    try:
                        with self.open(base + path, cancel=token) as response:
                            consume(response)
                    except BaseException as error:
                        outcome.append(error)
                with patch.object(network.subprocess, "Popen", side_effect=launch):
                    worker = threading.Thread(target=transfer, daemon=True)
                    worker.start()
                    try:
                        self.assertTrue(server.started.wait(3))
                        start = time.monotonic()
                        token.cancel()
                        worker.join(timeout=1.5)
                        self.assertFalse(worker.is_alive())
                        self.assertLess(time.monotonic() - start, 1.5)
                    finally:
                        token.cancel()
                        worker.join(timeout=2)
                self.assertEqual(len(outcome), 1)
                self.assertIsInstance(outcome[0], TaskCancelled)
                self.assertEqual(len(processes), 1)
                self.assertIsNotNone(processes[0].poll())
                self.assertTrue(processes[0].stdout.closed)

    def test_cancelled_before_open_never_starts_a_resolver(self):
        token = OperationToken()
        token.cancel()
        with patch.object(network.subprocess, "Popen") as spawn, self.assertRaises(TaskCancelled):
            self.open("https://example.invalid/", cancel=token)
        spawn.assert_not_called()

    def test_voice_policy_is_preserved_inside_isolated_worker(self):
        with local_server() as (server, base), self.assertRaises(URLError):
            self.open(base + "/data", policy="voice")
        self.assertFalse(server.started.is_set())

    def test_early_close_reaps_child_and_clears_pipe(self):
        with local_server() as (_server, base):
            response = self.open(base + "/trickle")
            process = response._process
            response.close()
            response.close()
            self.assertIsNotNone(process.poll())
            self.assertTrue(process.stdout.closed)

    def test_opds_fetch_and_atomic_book_download_use_real_transport(self):
        with local_server() as (_server, base), tempfile.TemporaryDirectory() as directory:
            self.assertEqual(opds.fetch_catalog(base + "/feed").title, "Loopback")
            acquisition = opds.Acquisition(base + "/book.txt", "text/plain", "Book")
            first = opds.download_book(acquisition, Path(directory))
            second = opds.download_book(acquisition, Path(directory))
            self.assertNotEqual(first, second)
            self.assertEqual(first.read_bytes(), PAYLOAD)
            self.assertEqual(second.read_bytes(), PAYLOAD)
            with patch.object(opds, "BOOK_TRANSFER_TIMEOUT", 0.35), self.assertRaises(opds.OPDSError):
                opds.download_book(opds.Acquisition(base + "/trickle", "text/plain", "Slow"), Path(directory))
            self.assertEqual(sorted(path.name for path in Path(directory).iterdir()),
                             sorted((first.name, second.name)))

    def test_deadline_also_stops_a_worker_before_metadata_without_network(self):
        # A blocked DNS resolver produces no metadata, just like this local
        # helper. Its lifetime must not depend on socket timeouts or urllib.
        with tempfile.TemporaryDirectory() as directory:
            helper = Path(directory) / "blocked.py"
            helper.write_text("import time\ntime.sleep(10)\n", encoding="utf-8")
            with patch.object(network, "_WORKER", helper), self.assertRaises(TimeoutError):
                self.open("https://example.invalid/", total_timeout=0.2)
