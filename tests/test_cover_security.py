"""Regression tests for background OPDS cover requests and disk quotas."""

from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import socket
import ssl
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from malferma_libro import covers, network_worker, opds
from malferma_libro.cover_ui import CoverUIMixin, _CoverRequest
from malferma_libro.tasks import OperationToken
from test_book_images import JPEG


def address(ip, port=80):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    endpoint = (ip, port, 0, 0) if family == socket.AF_INET6 else (ip, port)
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", endpoint)


class CoverNetworkTests(unittest.TestCase):
    def transfer(self, url, *, policy="opds-cover"):
        request = {"url": url, "policy": policy, "headers": {}, "limit": 1024, "timeout": 1}
        stdin = SimpleNamespace(buffer=io.BytesIO(json.dumps(request).encode()))
        stdout = SimpleNamespace(buffer=io.BytesIO())
        with patch.object(network_worker.sys, "stdin", stdin), patch.object(network_worker.sys, "stdout", stdout):
            network_worker._transfer()
        return stdout.buffer.getvalue().split(b"\n", 1)[1]

    def test_cover_selects_public_only_policy(self):
        with patch.object(opds, "_open_url") as opened:
            opened.return_value.__enter__.return_value.geturl.return_value = "https://books.example/cover.jpg"
            opened.return_value.__enter__.return_value.headers = {}
            opened.return_value.__enter__.return_value.read.return_value = b""
            opds.download_cover("https://books.example/cover.jpg")
        self.assertEqual(opened.call_args.kwargs["policy"], "opds-cover")

    def test_nonpublic_addresses_never_open_a_socket(self):
        with patch.object(network_worker.socket, "getaddrinfo") as resolve, patch.object(
            network_worker.socket, "socket"
        ) as create_socket:
            for ip in ("127.0.0.1", "192.168.1.20", "100.64.0.3", "169.254.1.2", "224.0.0.1",
                       "::1", "::ffff:127.0.0.1", "fe80::1", "fd00::1"):
                with self.subTest(ip=ip), self.assertRaises(OSError):
                    resolve.return_value = [address(ip)]
                    network_worker._connect_public(("books.example", 80), 1)
            create_socket.assert_not_called()

    def test_public_https_keeps_hostname_and_connects_to_checked_address(self):
        public = address("93.184.215.14", 443)
        reply = io.BytesIO(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")
        with patch.object(network_worker.socket, "getaddrinfo", return_value=[
            address("192.168.1.20", 443), public,
        ]) as resolve, patch.object(network_worker.socket, "socket") as create_socket, patch.object(
            ssl.SSLContext, "wrap_socket"
        ) as wrap, patch.dict(os.environ, {"https_proxy": "http://proxy.invalid:8080"}):
            wrap.return_value.makefile.return_value = reply
            self.assertEqual(self.transfer("https://books.example/cover.jpg"), b"OK")
        resolve.assert_called_once()
        self.assertEqual(resolve.call_args.args, ("books.example", 443))
        create_socket.return_value.connect.assert_called_once_with(public[4])
        self.assertEqual(wrap.call_args.kwargs["server_hostname"], "books.example")
        self.assertIn(b"Host: books.example", wrap.return_value.sendall.call_args.args[0])

    def test_redirect_gets_its_own_address_check(self):
        public = address("93.184.215.14")
        reply = (b"HTTP/1.1 302 Found\r\nContent-Length: 0\r\n"
                 b"Location: http://local.example/cover.jpg\r\n\r\n")
        with patch.object(network_worker.socket, "getaddrinfo", side_effect=[
            [public], [address("192.168.1.20")],
        ]) as resolve, patch.object(network_worker.socket, "socket") as create_socket:
            create_socket.return_value.makefile.return_value = io.BytesIO(reply)
            with self.assertRaises(URLError):
                self.transfer("http://books.example/cover.jpg")
        self.assertEqual([call.args[0] for call in resolve.call_args_list], ["books.example", "local.example"])
        create_socket.return_value.connect.assert_called_once_with(public[4])

    def test_explicit_catalog_keeps_standard_connection_policy(self):
        connection = MagicMock()
        connection.makefile.return_value = io.BytesIO(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")
        with patch.object(socket, "create_connection", return_value=connection) as connect, patch.dict(
            os.environ, {"no_proxy": "*"}
        ):
            self.assertEqual(self.transfer("http://192.168.1.20/catalog", policy="opds"), b"OK")
        self.assertEqual(connect.call_args.args[0], ("192.168.1.20", 80))


class CoverCacheQuotaTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cache = covers.CoverCache(self.root)
        self.cover = covers.CoverData(JPEG, "image/jpeg")

    def seed(self, key, timestamp):
        path = self.cache.path_for(key)
        path.write_bytes(JPEG)
        os.utime(path, (timestamp, timestamp))
        return path

    def test_existing_cache_prunes_old_entries_and_interrupted_writes(self):
        oldest, recent = self.seed("older", 1), self.seed("recent", 2)
        interrupted = self.root / ".cover-aaaaaaaa"
        interrupted.write_bytes(b"partial")
        unrelated = self.root / "keep.txt"
        unrelated.write_text("keep", encoding="utf-8")
        with patch.object(covers, "MAX_COVER_CACHE_BYTES", len(JPEG)):
            self.cache.prune()
        self.assertFalse(oldest.exists())
        self.assertFalse(interrupted.exists())
        self.assertTrue(recent.exists())
        self.assertTrue(unrelated.exists())
        self.assertEqual(self.cache.load("recent"), self.cover)

    def test_parallel_cache_instances_keep_both_quotas(self):
        with patch.object(covers, "MAX_COVER_CACHE_ENTRIES", 3), patch.object(
            covers, "MAX_COVER_CACHE_BYTES", 2 * len(JPEG)
        ), ThreadPoolExecutor(max_workers=4) as pool:
            paths = list(pool.map(lambda i: covers.CoverCache(self.root).store(str(i), self.cover), range(12)))
        self.assertTrue(all(paths))
        remaining = list(self.root.glob("*.cover"))
        self.assertEqual(len(remaining), 2)
        self.assertEqual(sum(path.stat().st_size for path in remaining), 2 * len(JPEG))
        self.assertEqual(list(self.root.glob(".cover-*")), [])

    def test_entry_quota_allows_replacement_and_evicts_for_new_key(self):
        older, recent = self.seed("older", 1), self.seed("recent", 2)
        with patch.object(covers, "MAX_COVER_CACHE_ENTRIES", 2):
            self.assertEqual(self.cache.store("recent", self.cover), recent)
            self.assertTrue(older.exists())
            self.assertIsNotNone(self.cache.store("new", self.cover))
        self.assertFalse(older.exists())
        self.assertEqual(self.cache.load("new"), self.cover)

    def test_thumbnail_can_be_shown_when_disk_write_is_skipped(self):
        ui = CoverUIMixin()
        ui.library = SimpleNamespace(root=self.root)
        ui.init_cover_ui()
        self.addCleanup(ui._cover_executor.shutdown)
        url = "https://books.example/cover.jpg"
        request = _CoverRequest(("remote", url), "opds:" + url, url=url)
        with patch.object(opds, "download_cover", return_value=self.cover), patch.object(
            covers, "MAX_COVER_CACHE_BYTES", 0
        ), patch(
            "malferma_libro.cover_ui.load_thumbnail"
        ) as thumbnail:
            self.assertIs(ui._load_cover_request(request, OperationToken()), thumbnail.return_value)
        thumbnail.assert_called_once_with(self.cover, ui.COVER_WIDTH * 4, ui.COVER_HEIGHT * 4)
        self.assertFalse(ui._cover_cache.path_for(request.cache_key).exists())
