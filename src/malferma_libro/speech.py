"""Offline neural narration through Piper, isolated from the GTK process.

Only this reader's process group (worker and audio player) is controlled. Text
travels over stdin, never argv or a text file. Private temporary WAV audio is
removed by both the worker and its owning parent, including cancellation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib.util
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import subprocess
import threading
import sys
import tempfile
import unicodedata
from typing import Callable, Iterator

from .i18n import _, SPEECH_LANGUAGE_CHOICES, SPEECH_LANGUAGE_CODES


MAX_CHUNK_CHARS = 600
_SENTENCE_END = re.compile(r"[.!?…][\"»”')\]]*\s+")


_LANGUAGE_WORDS = {
    "ru": frozenset("и в не на он что это как его она они было были есть для но из по или уже чтобы когда только книга глава первая чтения русский русская".split()),
    "uk": frozenset("і в не на він що це як його вона вони було були є для але із за або вже щоб коли тільки книга розділ перша читання українська".split()),
    "en": frozenset("the and of to in is that was he she it with for as his her not had this but from they were you have said book english paragraph old text".split()),
    "de": frozenset("der die das und ein eine einer eines dem den des ist war nicht mit für von auf sich er sie es zu im als aber auch hatte buch deutsch deutsches".split()),
    "fr": frozenset("le la les de du des et un une est était il elle dans pour avec pas que qui au aux ce cette son sa sur mais livre ceci écrit français".split()),
    "es": frozenset("el la los las de del y un una es estaba era él ella en para con no que por como su sus se al pero este esta libro está escrito español".split()),
    "it": frozenset("il lo la le gli di del della e un uno una è era lui lei in per con non che da come suo sua si al ma questo questa libro scritto italiano".split()),
    "pt": frozenset("o a os as de do da dos das e um uma é era ele ela em para com não que por como seu sua se ao mas este esta livro escrito português".split()),
}
_LATIN_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyzàáâãäçèéêëìíîïñòóôõöùúûüýÿœß")
_CYRILLIC_LETTERS = frozenset("абвгґдеєёжзиіїйклмнопрстуфхцчшщъыьэюя")


def detect_language(text: str) -> str | None:
    """Conservatively choose one of the eight narration languages.

    This is an offline hint, not a general language recognizer. Unsupported
    scripts and distinctive letters of removed languages require an explicit
    choice. Ambiguous ordinary Latin and Cyrillic retain the historic English
    and Russian fallback; an explicit language remains authoritative.
    """
    text = unicodedata.normalize("NFC", text).lower()
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return "en"
    cyrillic = [char for char in letters if "CYRILLIC" in unicodedata.name(char, "")]
    latin = [char for char in letters if "LATIN" in unicodedata.name(char, "")]
    other = len(letters) - len(cyrillic) - len(latin)
    if other >= max(len(cyrillic), len(latin)):
        return None
    if len(cyrillic) > len(latin):
        if any(char not in _CYRILLIC_LETTERS for char in cyrillic):
            return None
        ukrainian = any(char in "іїєґ" for char in cyrillic)
        russian = any(char in "ыэёъ" for char in cyrillic)
        if ukrainian != russian:
            return "uk" if ukrainian else "ru"
        languages = ("ru", "uk")
        fallback = "ru"
    else:
        if any(char not in _LATIN_LETTERS for char in latin):
            return None
        languages = ("en", "de", "fr", "es", "it", "pt")
        fallback = "en"
    words = re.findall(r"[^\W\d_]+", text, flags=re.UNICODE)
    scores = sorted(
        ((sum(word in _LANGUAGE_WORDS[language] for word in words), language)
         for language in languages), reverse=True,
    )
    best, language = scores[0]
    return language if best >= 2 and best >= scores[1][0] + 2 else fallback


def _executable(path: str | Path) -> str | None:
    candidate = Path(path).expanduser()
    return str(candidate) if candidate.is_absolute() and candidate.is_file() and os.access(candidate, os.X_OK) else None


def piper_python() -> str | None:
    """Locate an installed Piper Python runtime without importing ONNX/Piper.

    A Debian package/executable named ``piper`` may be a mouse configurator;
    never mistake it for a TTS engine. An explicitly chosen interpreter wins;
    otherwise prefer an existing bundled runtime before user environments.
    """
    override = os.environ.get("PIPER_PYTHON")
    if override:
        return _executable(override)
    data_home = os.environ.get("XDG_DATA_HOME", "")
    base = Path(data_home) if data_home and Path(data_home).is_absolute() else Path.home() / ".local" / "share"
    candidates = (
        Path("/usr/lib/malferma-libro/piper-python"),
        base / "malferma-libro" / "piper" / "bin" / "python",
        Path.home() / ".local" / "share" / "pipx" / "venvs" / "piper-tts" / "bin" / "python",
        Path.home() / ".local" / "pipx" / "venvs" / "piper-tts" / "bin" / "python",
    )
    for candidate in candidates:
        if executable := _executable(candidate):
            return executable
    try:
        if importlib.util.find_spec("piper") is not None:
            return sys.executable
    except (ImportError, ValueError):
        pass
    return None


def split_chunks(text: str, offset: int = 0, limit: int = MAX_CHUNK_CHARS) -> Iterator[tuple[int, int]]:
    """Yield bounded, contiguous character ranges, preferring prose boundaries.

    Offsets are Python Unicode character indices, matching GTK text offsets.
    Whitespace is preserved so resuming cannot drift relative to the book.
    """
    if limit < 1:
        raise ValueError(_("Размер фрагмента должен быть положительным."))
    start = min(max(0, offset), len(text))
    while start < len(text):
        end = min(start + limit, len(text))
        if end < len(text):
            lower = start + limit // 3
            paragraph = text.rfind("\n\n", lower, end)
            if paragraph >= 0:
                end = paragraph + 2
            else:
                sentences = list(_SENTENCE_END.finditer(text, lower, end))
                if sentences:
                    end = sentences[-1].end()
                else:
                    spaces = [index for index in range(lower, end) if text[index].isspace()]
                    if spaces:
                        end = spaces[-1] + 1
        yield start, end
        start = end


@dataclass
class _Session:
    generation: int
    text: str
    offset: int
    language: str
    rate: int
    voice_id: str = "auto"
    cancelled: threading.Event = field(default_factory=threading.Event)
    paused: bool = False
    process: subprocess.Popen | None = None


class SpeechReader:
    """Narrate one text at a time without blocking the GTK main loop.

    ``dispatch(callback, *args)`` should schedule a callback on the UI thread,
    for example with ``GLib.idle_add``. Direct dispatch also works in tests.
    ``on_range(start, end)`` identifies the currently spoken chunk. ``offset``
    advances only after that chunk succeeds; interruption may replay a short
    passage but cannot silently skip one. ``close`` and ``stop`` do not wait on
    the UI thread; their worker reaps the terminated process.
    """

    def __init__(
        self,
        dispatch: Callable,
        on_state: Callable[[str, str], None],
        on_range: Callable[[int, int], None],
        on_finished: Callable[[], None],
        *,
        voices=None,
        voice_manager=None,
    ):
        self._dispatch = dispatch
        self._on_state = on_state
        self._on_range = on_range
        self._on_finished = on_finished
        self._engine = piper_python()
        self._player = shutil.which("paplay") or shutil.which("aplay")
        self._voice_manager = voices if voices is not None else voice_manager
        if self._voice_manager is None:
            from .voices import VoiceManager
            self._voice_manager = VoiceManager()
        self._condition = threading.Condition(threading.RLock())
        self._generation = 0
        self._session: _Session | None = None
        self.state = "idle" if self.available else "unavailable"
        self.offset = 0
        self._closed = False

    @property
    def available(self) -> bool:
        return self._engine is not None and self._player is not None

    def _notify(self, generation: int, callback: Callable, *args) -> None:
        def deliver():
            # Check when dispatched, not merely when queued: a new book or stop
            # can happen before GLib gets to a callback from the old worker.
            with self._condition:
                if self._closed or generation != self._generation:
                    return False
                callback(*args)
            return False

        self._dispatch(deliver)

    def _set_state(self, generation: int, state: str, message: str = "") -> None:
        with self._condition:
            if generation != self._generation:
                return
            self.state = state
            self._notify(generation, self._on_state, state, message)

    @staticmethod
    def _signal(process: subprocess.Popen | None, sig: int) -> None:
        # Audio can outlive a crashed group leader. The session owns the whole
        # process group until its pipes are drained and all cleanup is done.
        if process is not None:
            try:
                os.killpg(process.pid, sig)
            except (ProcessLookupError, PermissionError):
                pass

    def start(self, text: str, offset: int = 0, language: str = "auto", rate: int = 180, voice_id: str = "auto") -> None:
        if not isinstance(text, str):
            raise TypeError(_("Текст озвучки должен быть строкой."))
        if language not in SPEECH_LANGUAGE_CODES:
            raise ValueError(_("Неизвестный язык озвучки: {language}.").format(language=language))
        rate = max(80, min(450, int(rate)))
        offset = max(0, min(len(text), int(offset)))
        with self._condition:
            if self._closed:
                return
            self._cancel_current()
            self._generation += 1
            generation = self._generation
            self.offset = offset
            if not self.available:
                self._set_state(
                    generation,
                    "unavailable",
                    _("Для озвучки установите Piper по инструкции в руководстве пользователя.") if self._engine is None else _("Для воспроизведения озвучки установите paplay или aplay."),
                )
                return
            voice = detect_language(text[offset : offset + 4000]) if language == "auto" else language
            if voice is None:
                self._set_state(
                    generation, "error",
                    _("Не удалось определить поддерживаемый язык озвучки. Выберите русский, украинский, английский, немецкий, французский, испанский, итальянский или португальский в настройках."),
                )
                return
            session = _Session(generation, text, offset, voice, rate, voice_id or "auto")
            self._session = session
            self._set_state(generation, "speaking")
            threading.Thread(
                target=self._read,
                args=(session,),
                name="book-narrator",
                # On application exit Python must let superseded sessions
                # finish their background kill/reap and private-WAV cleanup.
                daemon=False,
            ).start()

    def _cancel_current(self) -> None:
        session = self._session
        self._session = None
        if session is not None:
            session.cancelled.set()
            session.paused = False
            # A stopped process must be continued before it can handle SIGTERM.
            self._signal(session.process, signal.SIGCONT)
            self._signal(session.process, signal.SIGTERM)
            self._condition.notify_all()

    def pause(self) -> None:
        with self._condition:
            session = self._session
            if session is None or self.state != "speaking":
                return
            session.paused = True
            self._signal(session.process, signal.SIGSTOP)
            self._set_state(session.generation, "paused")

    def resume(self) -> None:
        with self._condition:
            session = self._session
            if session is None or self.state != "paused":
                return
            session.paused = False
            self._signal(session.process, signal.SIGCONT)
            self._condition.notify_all()
            self._set_state(session.generation, "speaking")

    def stop(self) -> None:
        with self._condition:
            self._cancel_current()
            self._generation += 1
            self._set_state(self._generation, "idle" if self.available else "unavailable")

    def close(self) -> None:
        with self._condition:
            process = self._session.process if self._session is not None else None
            self._closed = True
            self.stop()
            # The GUI is closing, so there is no playback left to preserve.
            # Kill native synthesis immediately; the worker thread reaps it.
            self._signal(process, signal.SIGKILL)

    @staticmethod
    def _communicate(session: _Session, process: subprocess.Popen) -> tuple[bytes, bytes]:
        """Close the request stream, drain output and reap without blocking GTK."""
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
            process.stdin = None
        while not session.cancelled.is_set():
            try:
                return process.communicate(timeout=0.1)
            except subprocess.TimeoutExpired:
                pass
        SpeechReader._signal(process, signal.SIGCONT)
        SpeechReader._signal(process, signal.SIGTERM)
        try:
            return process.communicate(timeout=1.0)
        except subprocess.TimeoutExpired:
            SpeechReader._signal(process, signal.SIGKILL)
            return process.communicate()

    @staticmethod
    def _wait_passage(session: _Session, process: subprocess.Popen, errors: bytearray) -> bool:
        """Drain both bounded protocol pipes until playback is acknowledged.

        The worker stays alive with its ONNX model loaded. No blocking reads or
        pipe writes run on GTK, and cancellation is observed every 100 ms even
        when the engine is stuck in native synthesis code.
        """
        response = bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, "output")
            selector.register(process.stderr, selectors.EVENT_READ, "error")
            while selector.get_map() and not session.cancelled.is_set():
                for key, _events in selector.select(timeout=0.1):
                    data = os.read(key.fd, 4096)
                    if not data:
                        selector.unregister(key.fileobj)
                    elif key.data == "error":
                        errors.extend(data)
                        del errors[:-65536]
                    else:
                        response.extend(data)
                        if b"\n" in response:
                            if response != b"PIPER_DONE\n":
                                raise RuntimeError(SpeechReader._worker_error(bytes(errors), 1))
                            return True
                        if len(response) > 1024:
                            raise RuntimeError(SpeechReader._worker_error(bytes(errors), 1))
                # A surviving audio child may still hold an inherited pipe;
                # an exited engine cannot acknowledge the pending passage.
                if process.poll() is not None:
                    return False
        return False

    def _read(self, session: _Session) -> None:
        try:
            with self._condition:
                if session.cancelled.is_set() or session.generation != self._generation:
                    return
            # Hash verification and model discovery belong on this worker,
            # never the GTK thread. Starting narration never downloads a model.
            model = self._voice_manager.get_model(session.language, voice_id=session.voice_id)
            with self._condition:
                if session.cancelled.is_set() or session.generation != self._generation:
                    return
                if model is None:
                    name = dict(SPEECH_LANGUAGE_CHOICES).get(session.language, session.language)
                    raise RuntimeError(_("Голос Piper «{language}» не установлен. Загрузите голос в настройках.").format(language=name))
            model = Path(model)
            config = Path(str(model) + ".json")
            # The parent owns this directory too, so SIGKILL of a stuck worker
            # cannot leave a speech recording behind after its process is reaped.
            with tempfile.TemporaryDirectory(prefix="malferma-piper-") as directory:
                output_file = str(Path(directory) / "chunk.wav")
                errors = bytearray()
                with self._condition:
                    self._condition.wait_for(lambda: not session.paused or session.cancelled.is_set())
                    if session.cancelled.is_set():
                        return
                    process = subprocess.Popen(
                        # A stdlib-only helper also works from a Piper venv;
                        # keep the model loaded across bounded passages.
                        [self._engine, str(Path(__file__).with_name("piper_worker.py")),
                         "--model", str(model), "--config", str(config),
                         "--length-scale", format(180.0 / session.rate, ".8g"),
                         "--player", self._player, "--output-file", output_file, "--stream"],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, start_new_session=True,
                    )
                    session.process = process
                for start, end in split_chunks(session.text, session.offset):
                    with self._condition:
                        self._condition.wait_for(lambda: not session.paused or session.cancelled.is_set())
                        if session.cancelled.is_set():
                            break
                        self._notify(session.generation, self._on_range, start, end)
                    # A request is < 4 KiB even with escaped control characters.
                    # Writing it on this background thread cannot freeze GTK.
                    request = json.dumps({"text": session.text[start:end]}, ensure_ascii=False).encode("utf-8") + b"\n"
                    process.stdin.write(request)
                    process.stdin.flush()
                    succeeded = self._wait_passage(session, process, errors)
                    with self._condition:
                        if session.cancelled.is_set():
                            break
                        if not succeeded:
                            raise RuntimeError(self._worker_error(bytes(errors), process.poll() or 1))
                        if session.generation == self._generation:
                            self.offset = end
                _output, error = self._communicate(session, process)
                errors.extend(error)
                with self._condition:
                    session.process = None
                    if session.cancelled.is_set():
                        return
                    if process.returncode != 0:
                        raise RuntimeError(self._worker_error(bytes(errors[-65536:]), process.returncode))
            with self._condition:
                self._condition.wait_for(lambda: not session.paused or session.cancelled.is_set())
                if session.cancelled.is_set() or session.generation != self._generation:
                    return
                self._session = None
                self._set_state(session.generation, "idle")
                self._notify(session.generation, self._on_finished)
        except Exception as error:
            was_cancelled = session.cancelled.is_set()
            process = session.process
            if process is not None:
                session.cancelled.set()
                self._communicate(session, process)
            with self._condition:
                if session.generation == self._generation and not was_cancelled:
                    self._session = None
                    self._set_state(session.generation, "error", _("Не удалось озвучить текст: {error}").format(error=error))

    @staticmethod
    def _worker_error(error: bytes, returncode: int) -> str:
        messages = {
            "runtime": _("Не удалось запустить Piper."),
            "model": _("Не удалось загрузить голос Piper."),
            "synthesis": _("Не удалось синтезировать речь Piper."),
            "playback": _("Не удалось воспроизвести озвучку."),
        }
        for line in reversed(error.decode("utf-8", errors="replace").splitlines()):
            if line.startswith("PIPER_ERROR "):
                try:
                    code = json.loads(line[len("PIPER_ERROR "):])["error"]
                    return messages.get(code, messages["runtime"])
                except (ValueError, KeyError, TypeError):
                    break
        detail = error.decode("utf-8", errors="replace").strip()[:400]
        return detail or _("Код завершения {code}").format(code=returncode)
