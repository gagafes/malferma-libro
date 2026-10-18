"""Private Piper Python API worker; no GTK, downloads or runtime installation.

One worker keeps its neural model loaded for a reading session. Bounded
passages arrive over stdin; each is acknowledged only after successful playback,
so a failed synthesis or player never advances the reading offset.
"""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import wave


MAX_INPUT_BYTES = 64 * 1024
MAX_CONFIG_BYTES = 2 * 1024 * 1024


class WorkerError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class PiperSession:
    """Load one CPU model lazily, then reuse it for bounded private passages."""

    def __init__(self, model: Path, config: Path, length_scale: float,
                 player: str, output_file: Path):
        self.model, self.config = model, config
        self.length_scale, self.player, self.output_file = length_scale, player, output_file
        self.voice = None

    def _load(self) -> None:
        if not math.isfinite(self.length_scale) or not 0.4 <= self.length_scale <= 2.25:
            raise WorkerError("input")
        if (not self.model.is_file() or not self.config.is_file()
                or self.config.stat().st_size > MAX_CONFIG_BYTES):
            raise WorkerError("model")
        try:
            with self.config.open(encoding="utf-8") as stream:
                if not isinstance(json.load(stream), dict):
                    raise ValueError("Invalid model configuration")
        except (OSError, UnicodeError, ValueError) as error:
            raise WorkerError("model") from error
        try:
            from piper import PiperVoice, SynthesisConfig
        except (ImportError, OSError) as error:
            raise WorkerError("runtime") from error
        try:
            self.voice = PiperVoice.load(str(self.model), config_path=str(self.config), use_cuda=False)
            self.base_scale = float(self.voice.config.length_scale)
            if not math.isfinite(self.base_scale) or self.base_scale <= 0:
                raise ValueError("Invalid configured speech rate")
            self.config_class = SynthesisConfig
        except Exception as error:
            raise WorkerError("model") from error

    def play(self, text: str) -> None:
        if not text.strip():
            return
        if self.voice is None:
            self._load()
        created = False
        try:
            try:
                # Never truncate a caller's existing file or follow a symlink.
                descriptor = os.open(self.output_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                created = True
                with os.fdopen(descriptor, "wb") as stream:
                    with wave.open(stream, "wb") as wav_file:
                        self.voice.synthesize_wav(text, wav_file,
                                                  syn_config=self.config_class(length_scale=self.base_scale * self.length_scale))
            except Exception as error:
                raise WorkerError("synthesis") from error
            try:
                with wave.open(str(self.output_file), "rb") as audio:
                    if (audio.getnframes() < 1 or audio.getnchannels() not in {1, 2}
                            or audio.getsampwidth() != 2 or not 8000 <= audio.getframerate() <= 96000):
                        raise ValueError("Invalid synthesized audio")
                name = Path(self.player).name
                if name not in {"paplay", "aplay"}:
                    raise ValueError("Unsupported audio player")
                command = [self.player, str(self.output_file)] if name == "paplay" else [self.player, "-q", str(self.output_file)]
                result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, check=False)
                if result.returncode != 0:
                    raise ValueError("Audio playback failed")
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                raise WorkerError("playback") from error
        finally:
            if created:
                self.output_file.unlink(missing_ok=True)


def synthesize_and_play(text: str, model: Path, config: Path, length_scale: float,
                        player: str, output_file: Path) -> None:
    """Compatibility entry point for a single passage using the same lifecycle."""
    PiperSession(model, config, length_scale, player, output_file).play(text)


def _serve(args, output_file: Path) -> None:
    session = PiperSession(args.model, args.config, args.length_scale, args.player, output_file)
    if args.stream:
        while data := sys.stdin.buffer.readline(MAX_INPUT_BYTES + 1):
            if len(data) > MAX_INPUT_BYTES or not data.endswith(b"\n") or b"\0" in data:
                raise WorkerError("input")
            try:
                request = json.loads(data)
                if (not isinstance(request, dict) or set(request) != {"text"}
                        or not isinstance(request["text"], str) or "\0" in request["text"]):
                    raise ValueError("Invalid passage")
            except (ValueError, UnicodeError) as error:
                raise WorkerError("input") from error
            # Keep library diagnostics out of the acknowledgement channel.
            with redirect_stdout(sys.stderr):
                session.play(request["text"])
            sys.stdout.buffer.write(b"PIPER_DONE\n")
            sys.stdout.buffer.flush()
    else:
        data = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(data) > MAX_INPUT_BYTES or b"\0" in data:
            raise WorkerError("input")
        try:
            text = data.decode("utf-8")
        except UnicodeError as error:
            raise WorkerError("input") from error
        session.play(text)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Private Malferma Libro Piper worker")
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--length-scale", required=True, type=float)
    parser.add_argument("--player", required=True)
    parser.add_argument("--output-file", type=Path)
    parser.add_argument("--stream", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.output_file is not None:
            _serve(args, args.output_file)
        else:
            with tempfile.TemporaryDirectory(prefix="malferma-piper-") as directory:
                _serve(args, Path(directory) / "chunk.wav")
        return 0
    except WorkerError as error:
        # Codes keep parent UI errors localized and exclude text/library traces.
        print("PIPER_ERROR " + json.dumps({"error": error.code}), file=sys.stderr)
        return 1
    except Exception:
        print('PIPER_ERROR {"error": "runtime"}', file=sys.stderr)
        return 1


if __name__ == "__main__":
    # CPU-heavy neural inference should yield to desktop interaction. Only the
    # isolated narration process is affected; no priority change reaches GTK.
    try:
        os.nice(5)
    except (AttributeError, OSError):
        pass
    # SIGCONT precedes termination when the parent stops a paused worker.
    # Exiting via Python lets context managers remove private recordings.
    def terminate(signum, _frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminate)
    raise SystemExit(main())
