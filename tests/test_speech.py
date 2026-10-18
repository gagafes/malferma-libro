"""Narration lifecycle with real worker processes and a synthetic Piper API.

These tests create short PCM samples, not neural speech or an audio-device test.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from malferma_libro import piper_worker
from malferma_libro.speech import SpeechReader, detect_language, piper_python, split_chunks


class ChunkAndLanguageTests(unittest.TestCase):
    def test_unicode_chunks_are_contiguous_bounded_and_lossless(self):
        text = ("Гетьте, думи! Українська мова. 🙂\n\n" * 50) + "x" * 1300
        chunks = list(split_chunks(text, 7))
        self.assertEqual(chunks[0][0], 7)
        self.assertEqual(chunks[-1][1], len(text))
        self.assertTrue(all(0 < end - start <= 600 for start, end in chunks))
        self.assertTrue(all(left[1] == right[0] for left, right in zip(chunks, chunks[1:])))
        self.assertEqual("".join(text[start:end] for start, end in chunks), text[7:])

    def test_chunk_offsets_clamp_and_zero_limit_is_rejected(self):
        self.assertEqual(list(split_chunks("abc", -9, 2)), [(0, 2), (2, 3)])
        self.assertEqual(list(split_chunks("abc", 100)), [])
        with self.assertRaises(ValueError):
            list(split_chunks("abc", limit=0))

    def test_supported_languages_and_unavailable_scripts(self):
        samples = {"ru": "Это русская книга, она была написана для чтения.",
                   "uk": "Це українська книга, її написано для читання.",
                   "en": "This is the old book and the text is in English.",
                   "de": "Das ist ein deutsches Buch und die Geschichte ist für sie.",
                   "fr": "Ceci est un livre écrit en français pour les enfants.",
                   "es": "Este libro está escrito en español para los niños.",
                   "it": "Questo è un libro scritto in italiano per gli amici.",
                   "pt": "Este é um livro escrito em português para os amigos."}
        for language, sample in samples.items():
            with self.subTest(language=language):
                self.assertEqual(detect_language(sample), language)
        for text in ("العربية", "עברית", "Қазақ тілі", "Esperanta ĉapitro"):
            with self.subTest(text=text):
                self.assertIsNone(detect_language(text))

    def test_explicit_runtime_must_be_an_absolute_executable(self):
        with patch.dict(os.environ, {"PIPER_PYTHON": sys.executable}):
            self.assertEqual(piper_python(), sys.executable)
        with patch.dict(os.environ, {"PIPER_PYTHON": "python3"}):
            self.assertIsNone(piper_python())


class PiperProcessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.model = self.root / "voice.onnx"
        self.model.write_bytes(b"toy model for protocol tests only")
        self.config = self.root / "voice.onnx.json"
        self.config.write_text('{"sample_rate":22050}', encoding="utf-8")
        self.trace = self.root / "events.jsonl"
        package = self.root / "piper"
        package.mkdir()
        (package / "__init__.py").write_text('''
import json, os, signal, sys, time
from pathlib import Path
from types import SimpleNamespace

def event(kind, **details):
    with open(os.environ["TEST_PIPER_TRACE"], "a", encoding="utf-8") as stream:
        stream.write(json.dumps({"kind":kind, **details}) + "\\n")

class SynthesisConfig:
    def __init__(self, length_scale):
        self.length_scale = length_scale

class PiperVoice:
    @staticmethod
    def load(model, config_path, use_cuda):
        event("load", pid=os.getpid())
        voice = PiperVoice()
        voice.rate = json.loads(Path(config_path).read_text())["sample_rate"]
        voice.config = SimpleNamespace(length_scale=1.0)
        return voice

    def synthesize_wav(self, text, output, syn_config):
        if os.environ.get("TEST_PIPER_IGNORE_TERM"):
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        event("synthesis", text=text, scale=syn_config.length_scale)
        print("Synthetic API diagnostic")
        sys.stderr.write("x" * int(os.environ.get("TEST_PIPER_DIAGNOSTIC_BYTES", "0")))
        sys.stderr.flush()
        if os.environ.get("TEST_PIPER_HANG"):
            while True:
                time.sleep(0.01)
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(self.rate)
        output.writeframes(b"\\0\\0" * 64)
''', encoding="utf-8")
        self.player = self.root / "paplay"
        self.player.write_text("#!" + sys.executable + '''
import json, os, sys
from pathlib import Path
with open(os.environ["TEST_PIPER_TRACE"], "a") as stream:
    stream.write(json.dumps({"kind":"play", "path":sys.argv[1], "exists":Path(sys.argv[1]).is_file()}) + "\\n")
raise SystemExit(int(os.environ.get("TEST_PIPER_PLAYER_EXIT", "0")))
''', encoding="utf-8")
        self.player.chmod(0o755)
        self.environment = patch.dict(os.environ, {"PYTHONPATH": str(self.root), "TEST_PIPER_TRACE": str(self.trace)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.readers = []
        self.original_threads = set(threading.enumerate())
        self.addCleanup(self.cleanup_readers)

    def cleanup_readers(self):
        for reader in self.readers:
            reader.close()
        for thread in set(threading.enumerate()) - self.original_threads:
            if thread.name == "book-narrator":
                thread.join(3)
                self.assertFalse(thread.is_alive(), "Narration worker did not finish cleanup")

    def events(self):
        if not self.trace.exists():
            return []
        return [json.loads(line) for line in self.trace.read_text().splitlines()]

    def until(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            threading.Event().wait(0.01)
        self.fail("Timed out waiting for the narration lifecycle")

    def reader(self, dispatch=None):
        states, ranges, finished = [], [], threading.Event()
        with patch("malferma_libro.speech.piper_python", return_value=sys.executable), patch("malferma_libro.speech.shutil.which", return_value=str(self.player)):
            reader = SpeechReader(dispatch or (lambda function: function()), lambda *args: states.append(args),
                                  lambda *args: ranges.append(args), finished.set,
                                  voices=SimpleNamespace(get_model=lambda *_args, **_kwargs: self.model))
        self.readers.append(reader)
        return reader, states, ranges, finished

    def worker(self, data):
        output = self.root / "worker.wav"
        result = subprocess.run([sys.executable, piper_worker.__file__, "--model", str(self.model), "--config", str(self.config),
                                 "--length-scale", "1", "--player", str(self.player), "--output-file", str(output), "--stream"],
                                input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=4)
        self.assertFalse(output.exists())
        return result

    def test_persistent_model_reused_and_offset_advances_after_playback(self):
        reader, states, ranges, finished = self.reader()
        text = "A passage with Unicode: Україна 🙂. " * 50
        reader.start(text, offset=4, language="en", rate=90)
        self.assertTrue(finished.wait(4), states)
        self.assertEqual(reader.state, "idle")
        self.assertEqual(reader.offset, len(text))
        self.assertEqual(ranges, list(split_chunks(text, 4)))
        events = self.events()
        self.assertEqual(sum(event["kind"] == "load" for event in events), 1)
        spoken = [event for event in events if event["kind"] == "synthesis"]
        self.assertEqual("".join(event["text"] for event in spoken), text[4:])
        self.assertTrue(all(event["scale"] == 2.0 for event in spoken))
        played = [event for event in events if event["kind"] == "play"]
        self.assertEqual(len(played), len(spoken))
        self.assertTrue(all(event["exists"] and not Path(event["path"]).exists() for event in played))

    def test_failed_player_does_not_advance_or_finish(self):
        os.environ["TEST_PIPER_PLAYER_EXIT"] = "1"
        reader, states, _ranges, finished = self.reader()
        reader.start("A short passage.", offset=2, language="en")
        self.until(lambda: reader.state == "error")
        self.assertEqual(reader.offset, 2)
        self.assertFalse(finished.is_set())
        self.assertTrue(states[-1][1])

    def test_large_engine_diagnostics_cannot_block_the_protocol(self):
        os.environ["TEST_PIPER_DIAGNOSTIC_BYTES"] = "200000"
        reader, states, _ranges, finished = self.reader()
        reader.start("A short passage.", language="en")
        self.assertTrue(finished.wait(4), states)
        self.assertEqual(reader.offset, len("A short passage."))

    def test_stop_reaps_a_paused_worker_and_removes_private_audio(self):
        os.environ["TEST_PIPER_HANG"] = "1"
        reader, _states, _ranges, finished = self.reader()
        reader.start("A short passage.", language="en")
        self.until(lambda: any(event["kind"] == "synthesis" for event in self.events()))
        process = reader._session.process
        reader.pause()
        self.assertEqual(reader.state, "paused")
        before = time.monotonic()
        reader.stop()
        self.assertLess(time.monotonic() - before, 0.5)
        self.until(lambda: process.poll() is not None)
        self.cleanup_readers()
        self.assertEqual(reader.offset, 0)
        self.assertFalse(finished.is_set())
        with self.assertRaises(ProcessLookupError):
            os.killpg(process.pid, 0)

    def test_cancellation_kills_and_reaps_an_engine_ignoring_termination(self):
        os.environ["TEST_PIPER_HANG"] = "1"
        os.environ["TEST_PIPER_IGNORE_TERM"] = "1"
        reader, _states, _ranges, finished = self.reader()
        reader.start("A short passage.", language="en")
        self.until(lambda: any(event["kind"] == "synthesis" for event in self.events()))
        process = reader._session.process
        reader.stop()
        self.until(lambda: process.poll() is not None)
        self.cleanup_readers()
        self.assertFalse(finished.is_set())
        self.assertEqual(reader.offset, 0)
        self.assertEqual(process.returncode, -9)

    def test_existing_audio_path_is_never_truncated(self):
        output = self.root / "worker.wav"
        output.write_bytes(b"Existing user data")
        result = subprocess.run([sys.executable, piper_worker.__file__, "--model", str(self.model), "--config", str(self.config),
                                 "--length-scale", "1", "--player", str(self.player), "--output-file", str(output), "--stream"],
                                input=b'{"text":"Sample."}\n', stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=4)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output.read_bytes(), b"Existing user data")

    def test_callbacks_queued_before_stop_do_not_update_the_new_session(self):
        queue = []
        reader, states, ranges, finished = self.reader(dispatch=queue.append)
        reader.start("A short passage.", language="en")
        self.until(lambda: reader.state == "idle")
        reader.stop()
        for callback in queue:
            callback()
        self.assertEqual(states, [("idle", "")])
        self.assertEqual(ranges, [])
        self.assertFalse(finished.is_set())

    def test_worker_rejects_malformed_or_unbounded_requests(self):
        for data in (b'{"text":5}\n', b'{"text":"abc","extra":1}\n', b'{"text":"a\\u0000b"}\n', b"x" * 65537):
            with self.subTest(data=data[:40]):
                result = self.worker(data)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(b"PIPER_DONE", result.stdout)

    def test_importable_96khz_voice_can_play(self):
        self.config.write_text('{"sample_rate":96000}', encoding="utf-8")
        result = self.worker(b'{"text":"High rate sample."}\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"PIPER_DONE\n")


if __name__ == "__main__":
    unittest.main()
