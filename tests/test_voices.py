"""Piper installs and imports exercise filesystem transactions without network.

Toy bytes test transfer/receipt behavior; they are not validated neural models.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from malferma_libro.tasks import OperationToken, TaskCancelled
from malferma_libro.voices import LANGUAGES, VOICE_CATALOG, VoiceEntry, VoiceError, VoiceFile, VoiceManager


class Response(io.BytesIO):
    status = 200

    def __init__(self, data, url, headers=None):
        super().__init__(data)
        self.url = url
        self.headers = {"Content-Length": str(len(data)), **(headers or {})}

    def geturl(self):
        return self.url


class FixtureOpener:
    def __init__(self, files):
        self.files = files
        self.requests = []
        self.transform = lambda response: response

    def open(self, request, timeout):
        self.requests.append(request)
        return self.transform(Response(self.files[request.full_url], request.full_url))


class VoiceStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = self.root / "voices"
        self.model = b"\x08" + b"toy-protocol-model" * 8
        self.configuration = {"language": {"code": "en_US"}, "audio": {"sample_rate": 22050},
                              "phoneme_id_map": {"a": [1], "_": [0]}, "num_speakers": 1}
        config_bytes = json.dumps(self.configuration).encode()
        base = "https://huggingface.co/rhasspy/piper-voices/resolve/" + "a" * 40 + "/fixture/"
        self.data = {"model.onnx": self.model, "model.onnx.json": config_bytes, "MODEL_CARD": b"Test fixture: CC0-1.0\n"}
        self.entry = VoiceEntry("en-test", "en", "Fixture", "CC0-1.0",
                                tuple(VoiceFile(name, base + name, hashlib.sha256(data).hexdigest(), len(data))
                                      for name, data in self.data.items()))
        self.opener = FixtureOpener({base + name: data for name, data in self.data.items()})
        self.manager = VoiceManager(self.store, catalog=(self.entry,), opener=self.opener)

    def assert_no_partial_install(self):
        self.assertIsNone(self.manager.get_model("en", self.entry.id))
        self.assertFalse(self.store.joinpath(self.entry.id).exists())
        self.assertEqual(list(self.store.glob(".piper-*.partial")), [])

    def local_source(self, configuration=None):
        source = self.root / "Personal voice.onnx"
        source.write_bytes(self.model)
        source.with_name(source.name + ".json").write_text(json.dumps(configuration or self.configuration))
        return source

    def test_construction_and_selection_never_create_or_download(self):
        self.assertFalse(self.store.exists())
        self.assertEqual(self.manager.catalog, (self.entry,))
        self.assertIsNone(self.manager.get_model("en"))
        self.assertEqual(self.opener.requests, [])
        self.assertFalse(self.store.exists())

    def test_catalog_is_immutable_reviewed_and_limited_to_narration_languages(self):
        self.assertEqual(LANGUAGES, {"ru", "uk", "en", "de", "fr", "es", "it", "pt"})
        manager = VoiceManager(self.store)
        self.assertEqual(manager.catalog, VOICE_CATALOG)
        for entry in VOICE_CATALOG:
            with self.subTest(voice=entry.id):
                self.assertIn(entry.language, LANGUAGES)
                self.assertTrue(entry.license)
                self.assertTrue(entry.license_url.startswith("https://"))
                for file in entry.files:
                    self.assertRegex(file.url, r"/resolve/[a-f0-9]{40}/")

    def test_successful_install_receipt_survives_reopening_without_redownload(self):
        model = self.manager.install(self.entry.id)
        self.assertEqual(model.read_bytes(), self.model)
        reopened = VoiceManager(self.store, catalog=(self.entry,), opener=self.opener)
        self.assertEqual(reopened.get_model("en"), model)
        self.assertEqual(reopened.install(self.entry.id), model)
        self.assertEqual(len(self.opener.requests), 3)
        self.assertEqual(model.stat().st_mode & 0o222, 0)
        self.assertEqual(list(self.store.glob(".piper-*")), [])

    def test_digest_mismatch_does_not_publish(self):
        self.opener.files[self.entry.files[0].url] = b"x" * len(self.model)
        with self.assertRaises(VoiceError):
            self.manager.install(self.entry.id)
        self.assert_no_partial_install()

    def test_declared_size_and_redirect_destination_are_checked(self):
        def oversize(response):
            response.headers["Content-Length"] = str(999999999)
            return response

        def untrusted(response):
            response.url = "https://example.org/model.onnx"
            return response

        for transform in (oversize, untrusted):
            self.opener.transform = transform
            with self.subTest(transform=transform.__name__), self.assertRaises(VoiceError):
                self.manager.install(self.entry.id)
            self.assert_no_partial_install()

    def test_cancellation_during_transfer_removes_staged_bytes(self):
        token = OperationToken()
        token.add_progress_callback(lambda *_args: token.cancel())
        with self.assertRaises(TaskCancelled):
            self.manager.install(self.entry.id, cancel=token)
        self.assert_no_partial_install()

    def test_user_model_import_is_content_identified_private_and_idempotent(self):
        source = self.local_source()
        first = self.manager.import_model(source)
        renamed = self.root / "Other name.onnx"
        renamed.write_bytes(source.read_bytes())
        renamed.with_name(renamed.name + ".json").write_bytes(source.with_name(source.name + ".json").read_bytes())
        second = self.manager.import_model(renamed)
        self.assertEqual(first.id, second.id)
        self.assertEqual(first.name, second.name)
        self.assertTrue(first.local)
        self.assertIsNone(first.license)
        self.assertEqual(self.manager.get_model("en", first.id).read_bytes(), self.model)
        self.assertEqual(sum(entry.local for entry in self.manager.catalog), 1)
        card = (self.store / first.id / "MODEL_CARD").read_text()
        self.assertIn("No redistribution license", card)

    def test_model_mutation_even_with_restored_mtime_invalidates_receipt(self):
        model = self.manager.install(self.entry.id)
        old_stat = model.stat()
        model.chmod(0o600)
        model.write_bytes(b"x" * len(self.model))
        os.utime(model, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
        self.assertIsNone(self.manager.get_model("en", self.entry.id))

    def test_symlinked_model_or_metadata_cannot_be_selected(self):
        for filename in ("model.onnx", "installed.json"):
            model = self.manager.install(self.entry.id)
            target = model.parent / filename
            copy = self.root / (filename + ".copy")
            copy.write_bytes(target.read_bytes())
            target.unlink()
            target.symlink_to(copy)
            self.assertIsNone(self.manager.get_model("en", self.entry.id))

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO unavailable")
    def test_fifo_receipt_and_import_are_rejected_without_blocking(self):
        model = self.manager.install(self.entry.id)
        receipt = model.parent / "installed.json"
        receipt.unlink()
        os.mkfifo(receipt)
        started = time.monotonic()
        self.assertIsNone(self.manager.get_model("en", self.entry.id))
        source = self.root / "pipe.onnx"
        os.mkfifo(source)
        with self.assertRaises(VoiceError):
            self.manager.import_model(source)
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(list(self.store.glob(".piper-*.partial")), [])

    def test_unsupported_and_malformed_configuration_cannot_be_imported(self):
        for config in ({**self.configuration, "language": {"code": "ar"}},
                       {**self.configuration, "audio": {"sample_rate": True}},
                       {**self.configuration, "phoneme_id_map": {"a": [True]}},
                       {**self.configuration, "num_speakers": 0}):
            with self.subTest(configuration=config), self.assertRaises(VoiceError):
                self.manager.import_model(self.local_source(config))
            self.assertEqual(list(self.store.glob(".piper-*.partial")), [])

    def test_personal_voice_may_use_96khz_audio(self):
        config = {**self.configuration, "audio": {"sample_rate": 96000}}
        entry = self.manager.import_model(self.local_source(config))
        self.assertIsNotNone(self.manager.get_model("en", entry.id))

    def test_invalid_voice_identifier_cannot_escape_store(self):
        for identifier in ("../escape", "/absolute", "a/../b", "", 8):
            with self.subTest(identifier=identifier):
                self.assertIsNone(self.manager.get_model("en", identifier))

    def test_failed_repair_publish_restores_previous_voice_directory(self):
        model = self.manager.install(self.entry.id)
        model.chmod(0o600)
        model.write_bytes(b"old invalid file")
        original_replace = os.replace

        def fail_publish(source, destination):
            if str(source).endswith(".partial"):
                raise OSError("Simulated full filesystem")
            return original_replace(source, destination)

        with patch("malferma_libro.voices.os.replace", side_effect=fail_publish), self.assertRaises(VoiceError):
            self.manager.install(self.entry.id)
        self.assertEqual(model.read_bytes(), b"old invalid file")
        self.assertEqual(list(self.store.glob(".piper-*")), [])


if __name__ == "__main__":
    unittest.main()
