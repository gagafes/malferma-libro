"""Bounded, cancellable Piper model downloads and private local imports.

No model ships with the application and construction never creates a store or
uses the network. Only install() downloads curated, immutable HTTPS resources.
Receipts bind verified installation bytes to their file identity; get_model()
checks those small receipts and stat signatures without hashing large models
on the GTK thread. User imports are identified by content and never acquire an
invented redistribution license.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import http.client
from itertools import islice
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request
from uuid import uuid4

from . import __version__
from .i18n import _
from .network import fetch_response
from .paths import user_data_directory
from .tasks import check_cancel, report_progress
from .voice_catalog import CURATED_VOICES


LANGUAGES = frozenset({"ru", "uk", "en", "de", "fr", "es", "it", "pt"})
MAX_MODEL_BYTES = 200 * 1024 * 1024
MAX_CONFIG_BYTES = 1024 * 1024
MAX_CARD_BYTES = 256 * 1024
MAX_RECEIPT_BYTES = 64 * 1024
VOICE_TRANSFER_TIMEOUT = 600
_LIMITS = {"model.onnx": MAX_MODEL_BYTES, "model.onnx.json": MAX_CONFIG_BYTES, "MODEL_CARD": MAX_CARD_BYTES}
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,95}\Z")
_SHA256 = re.compile(r"[a-f0-9]{64}\Z")
_RECEIPT = "installed.json"


class VoiceError(ValueError):
    """A voice cannot safely be obtained, installed, or selected."""


@dataclass(frozen=True)
class VoiceFile:
    name: str
    url: str | None
    sha256: str | None = None
    size: int | None = None


@dataclass(frozen=True)
class VoiceEntry:
    id: str
    language: str
    name: str
    license: str | None
    files: tuple[VoiceFile, ...]
    source_url: str = ""
    license_url: str = ""
    local: bool = False

    @property
    def title(self):
        return self.name

    @property
    def size_bytes(self):
        return sum(file.size or 0 for file in self.files)


VOICE_CATALOG = tuple(VoiceEntry(
    id=item["id"], language=item["language"], name=item["title"], license=item["declared_license"],
    files=(VoiceFile("model.onnx", item["model_url"], item["sha256"], item["size"]),
           VoiceFile("model.onnx.json", item["config_url"]), VoiceFile("MODEL_CARD", item["card_url"])),
    source_url=item["card_evidence_url"], license_url=item.get("author_license_url", item["card_evidence_url"]),
) for item in CURATED_VOICES)


def _trusted_url(url):
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        trusted = (host == "huggingface.co" or host.endswith(".huggingface.co")
                   or host == "hf.co" or host.endswith(".hf.co"))
        valid = (parsed.scheme == "https" and trusted and parsed.port in (None, 443)
                 and parsed.username is None and parsed.password is None and not parsed.fragment
                 and not any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url))
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise VoiceError(_("Файлы голоса Piper не прошли проверку."))
    return url


class _VoiceRedirects(HTTPRedirectHandler):
    max_redirections = 5
    max_repeats = 2

    def redirect_request(self, request, response, code, message, headers, new_url):
        try:
            _trusted_url(new_url)
            redirected = super().redirect_request(request, response, code, message, headers, new_url)
        except Exception:
            response.close()
            raise
        if redirected is not None:
            # urllib otherwise drains an unbounded redirect response body.
            response.close()
        return redirected


def _fingerprint(entry):
    return hashlib.sha256(json.dumps(asdict(entry), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _signature(path):
    information = path.lstat()
    if not stat.S_ISREG(information.st_mode):
        raise ValueError("Voice files must be regular files")
    return [information.st_dev, information.st_ino, information.st_size,
            information.st_mtime_ns, information.st_ctime_ns]


def _json_document(path, limit):
    # A corrupt store may contain a FIFO/device instead of JSON. Opening that
    # synchronously from a voice selector used to block the GTK thread before
    # validation; validate the opened descriptor and never follow symlinks.
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
                         | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as source:
        information = os.fstat(source.fileno())
        if not stat.S_ISREG(information.st_mode) or not 0 < information.st_size <= limit:
            raise ValueError("Invalid voice metadata")
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Voice metadata is too large")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("Voice metadata must be an object")
    return result


def _configuration(path, language=None):
    try:
        config = _json_document(path, MAX_CONFIG_BYTES)
        code = config.get("language", {}).get("code", "")
        detected = re.split("[_-]", code.casefold())[0] if isinstance(code, str) else ""
        if detected not in LANGUAGES or language is not None and detected != language:
            raise ValueError("Unsupported or mismatched language")
        sample_rate = config.get("audio", {}).get("sample_rate")
        if type(sample_rate) is not int or not 8000 <= sample_rate <= 96000:
            raise ValueError("Invalid audio rate")
        phonemes = config.get("phoneme_id_map")
        if not isinstance(phonemes, dict) or not 1 <= len(phonemes) <= 4096:
            raise ValueError("Missing phoneme map")
        for symbol, identifiers in phonemes.items():
            if (not isinstance(symbol, str) or len(symbol) > 256 or not isinstance(identifiers, list)
                    or not 1 <= len(identifiers) <= 64
                    or any(type(identifier) is not int or not 0 <= identifier <= 65535 for identifier in identifiers)):
                raise ValueError("Invalid phoneme map")
        if config.get("phoneme_type", "espeak") not in {"espeak", "text"}:
            raise ValueError("Unsupported phoneme type")
        speakers = config.get("num_speakers", 1)
        if type(speakers) is not int or not 1 <= speakers <= 4096:
            raise ValueError("Invalid speaker count")
        return detected
    except (OSError, ValueError, TypeError, AttributeError, RecursionError) as error:
        raise VoiceError(_("Файлы голоса Piper не прошли проверку.")) from error


def _validate_entry(entry):
    if (not isinstance(entry, VoiceEntry) or not isinstance(entry.id, str) or not _ID.fullmatch(entry.id)
            or not isinstance(entry.language, str) or entry.language not in LANGUAGES
            or not isinstance(entry.name, str) or not entry.name or type(entry.local) is not bool
            or not isinstance(entry.files, tuple) or not all(isinstance(file, VoiceFile) for file in entry.files)
            or set(file.name for file in entry.files) != set(_LIMITS) or len(entry.files) != 3):
        raise ValueError("Invalid voice catalog entry")
    for file in entry.files:
        if file.sha256 is not None and (not isinstance(file.sha256, str) or not _SHA256.fullmatch(file.sha256)):
            raise ValueError("Invalid voice digest")
        if file.size is not None and (type(file.size) is not int or not 0 < file.size <= _LIMITS[file.name]):
            raise ValueError("Invalid voice size")
        if not entry.local:
            _trusted_url(file.url)
            if not re.match(r"https://huggingface\.co/rhasspy/piper-voices/resolve/[a-f0-9]{40}/", file.url):
                raise ValueError("Curated voice URLs must pin an immutable repository revision")
    if not entry.local and (not isinstance(entry.license, str) or not entry.license
                            or not next(file for file in entry.files if file.name == "model.onnx").sha256):
        raise ValueError("Curated models need a reviewed license and a pinned model SHA256")


class VoiceManager:
    def __init__(self, root=None, catalog=VOICE_CATALOG, *, opener=None):
        self.root = Path(root) if root is not None else user_data_directory() / "voices"
        self._catalog = tuple(catalog)
        for entry in self._catalog:
            _validate_entry(entry)
        if len({entry.id for entry in self._catalog}) != len(self._catalog):
            raise ValueError("Duplicate voice identifiers")
        self._opener = opener
        self._lock = threading.RLock()
        self._voice_locks = {}
        self._local_index_signature = None
        self._local_index = None

    def _receipt(self, entry):
        directory = self.root / entry.id
        if directory.is_symlink():
            return None
        try:
            receipt = _json_document(directory / _RECEIPT, MAX_RECEIPT_BYTES)
            if receipt.get("schema") != 1 or receipt.get("fingerprint") != _fingerprint(entry):
                return None
            for file in entry.files:
                record = receipt["files"][file.name]
                signature = _signature(directory / file.name)
                if (record["signature"] != signature or not 0 < signature[2] <= _LIMITS[file.name]
                        or not _SHA256.fullmatch(record["sha256"])
                        or file.sha256 is not None and record["sha256"] != file.sha256
                        or file.size is not None and signature[2] != file.size):
                    return None
            return receipt
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
            return None

    def _local_entry(self, directory):
        if not directory.name.startswith("local-") or directory.is_symlink():
            return None
        try:
            receipt = _json_document(directory / _RECEIPT, MAX_RECEIPT_BYTES)
            data = receipt["entry"]
            entry = VoiceEntry(directory.name, data["language"], data["name"], None,
                               tuple(VoiceFile(**file) for file in data["files"]), local=True)
            _validate_entry(entry)
            return entry if self._receipt(entry) is not None else None
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
            return None

    def _root_signature(self):
        try:
            information = self.root.stat()
            return (information.st_dev, information.st_ino, information.st_mtime_ns, information.st_ctime_ns)
        except OSError:
            return None

    def _local_entries(self):
        signature = self._root_signature()
        with self._lock:
            if self._local_index is not None and signature == self._local_index_signature:
                return self._local_index
        try:
            # Bound traversal before sorting: sorting root.iterdir() used to
            # consume an arbitrary number of unrelated files before the cap.
            with os.scandir(self.root) as source:
                directories = sorted((self.root / item.name for item in islice(source, 512)),
                                     key=lambda path: path.name)
        except OSError:
            directories = ()
        entries = tuple(entry for directory in directories
                        if (entry := self._local_entry(directory)) is not None)
        with self._lock:
            if self._root_signature() == signature:
                self._local_index_signature = signature
                self._local_index = entries
        return entries

    @property
    def catalog(self):
        # The directory index is metadata only. get_model still validates the
        # selected receipt and file identities before every playback.
        return self._catalog + self._local_entries()

    def voices_for(self, language="auto"):
        return tuple(entry for entry in self.catalog if language == "auto" or entry.language == language)

    def voice_for(self, language, voice_id="auto"):
        if voice_id not in (None, "auto"):
            # Selecting one model must not scan/read every other local voice.
            if not isinstance(voice_id, str) or not _ID.fullmatch(voice_id):
                return None
            entry = next((entry for entry in self._catalog if entry.id == voice_id), None)
            if entry is None:
                entry = self._local_entry(self.root / voice_id)
            return entry if entry is not None and (language == "auto" or entry.language == language) else None
        entries = self.voices_for(language)
        if language == "auto":
            return None
        return next((entry for entry in entries if self._receipt(entry) is not None), next(iter(entries), None))

    def get_model(self, language, voice_id="auto"):
        entry = self.voice_for(language, voice_id)
        return self.root / entry.id / "model.onnx" if entry is not None and self._receipt(entry) else None

    @contextmanager
    def _voice_operation(self, identifier, cancel):
        with self._lock:
            lock = self._voice_locks.setdefault(identifier, threading.Lock())
        while not lock.acquire(timeout=0.1):
            check_cancel(cancel)
        try:
            check_cancel(cancel)
            yield
        finally:
            lock.release()

    def _stage(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Only abandoned partial staging directories are eligible for cleanup;
        # complete voices and recovery backups are never treated as stale.
        for directory in self.root.glob(".piper-*.partial"):
            try:
                if not directory.is_symlink() and directory.stat().st_mtime < time.time() - 86400:
                    shutil.rmtree(directory)
            except OSError:
                pass
        return Path(tempfile.mkdtemp(prefix=".piper-", suffix=".partial", dir=self.root))

    @staticmethod
    def _sync_directory(directory):
        descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _publish(self, stage, entry, digests, cancel):
        check_cancel(cancel)
        receipt = {"schema": 1, "entry": asdict(entry), "fingerprint": _fingerprint(entry), "files": {}}
        for file in entry.files:
            path = stage / file.name
            path.chmod(0o444)
            receipt["files"][file.name] = {"sha256": digests[file.name], "signature": _signature(path)}
        with (stage / _RECEIPT).open("x", encoding="utf-8") as target:
            json.dump(receipt, target, ensure_ascii=False, sort_keys=True)
            target.flush()
            os.fsync(target.fileno())
        self._sync_directory(stage)
        destination = self.root / entry.id
        backup = self.root / (".piper-backup-" + uuid4().hex)
        with self._lock:
            check_cancel(cancel)
            moved = False
            if destination.exists() or destination.is_symlink():
                os.replace(destination, backup)
                moved = True
            try:
                os.replace(stage, destination)
            except BaseException:
                if moved:
                    os.replace(backup, destination)
                raise
            self._local_index_signature = None
            self._local_index = None
        # Slow filesystem flushes and deleting an old 200 MiB model must not
        # hold the metadata lock used by GTK's voice selector.
        try:
            self._sync_directory(self.root)
        finally:
            if moved:
                if backup.is_symlink() or backup.is_file():
                    backup.unlink()
                else:
                    shutil.rmtree(backup, ignore_errors=True)
        return destination / "model.onnx"

    def _download(self, file, target, cancel, progress_offset, total):
        _trusted_url(file.url)
        request = Request(file.url, headers={"User-Agent": f"Malferma-Libro/{__version__}", "Accept-Encoding": "identity"})
        digest, done = hashlib.sha256(), 0
        try:
            response = (self._opener.open(request, timeout=20) if self._opener is not None else
                        fetch_response(request, policy="voice", limit=_LIMITS[file.name],
                                       cancel=cancel, total_timeout=VOICE_TRANSFER_TIMEOUT))
            with response, target.open("xb") as destination:
                _trusted_url(response.geturl())
                if getattr(response, "status", 200) != 200 or response.headers.get("Content-Encoding", "identity").lower() not in {"", "identity"}:
                    raise VoiceError(_("Файлы голоса Piper не прошли проверку."))
                length = response.headers.get("Content-Length")
                if length is not None:
                    try:
                        declared = int(length)
                    except (ValueError, TypeError):
                        raise VoiceError(_("Файлы голоса Piper не прошли проверку.")) from None
                    if not 0 < declared <= _LIMITS[file.name] or file.size is not None and declared != file.size:
                        raise VoiceError(_("Файлы голоса Piper не прошли проверку."))
                else:
                    declared = None
                model_total = file.size or declared if file.name == "model.onnx" else None
                while True:
                    check_cancel(cancel)
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    done += len(chunk)
                    if done > _LIMITS[file.name]:
                        raise VoiceError(_("Файлы голоса Piper не прошли проверку."))
                    destination.write(chunk)
                    digest.update(chunk)
                    report_progress(cancel, progress_offset + done if total is not None else done,
                                    total if total is not None else model_total)
                if not done or declared is not None and done != declared or file.size is not None and done != file.size:
                    raise VoiceError(_("Файлы голоса Piper не прошли проверку."))
                destination.flush()
                os.fsync(destination.fileno())
        except HTTPError as error:
            error.close()
            raise VoiceError(_("Не удалось скачать голос Piper.")) from error
        except (URLError, TimeoutError, http.client.HTTPException) as error:
            raise VoiceError(_("Не удалось скачать голос Piper.")) from error
        value = digest.hexdigest()
        if file.sha256 is not None and value != file.sha256:
            raise VoiceError(_("Файлы голоса Piper не прошли проверку."))
        return value, done

    def install(self, voice_id, cancel=None):
        entry = next((entry for entry in self._catalog if entry.id == voice_id), None)
        if entry is None:
            raise VoiceError(_("Голос Piper для выбранного языка недоступен."))
        with self._voice_operation(entry.id, cancel):
            existing = self.get_model(entry.language, entry.id)
            if existing is not None:
                return existing
            stage = None
            try:
                stage = self._stage()
                total = sum(file.size for file in entry.files) if all(file.size is not None for file in entry.files) else None
                digests, done = {}, 0
                for file in entry.files:
                    digests[file.name], size = self._download(file, stage / file.name, cancel, done, total)
                    done += size
                _configuration(stage / "model.onnx.json", entry.language)
                card = (stage / "MODEL_CARD").read_text(encoding="utf-8")
                if not card.strip():
                    raise VoiceError(_("Файлы голоса Piper не прошли проверку."))
                return self._publish(stage, entry, digests, cancel)
            except UnicodeError as error:
                raise VoiceError(_("Файлы голоса Piper не прошли проверку.")) from error
            except OSError as error:
                raise VoiceError(_("Не удалось сохранить голос Piper.")) from error
            finally:
                if stage is not None:
                    shutil.rmtree(stage, ignore_errors=True)

    @staticmethod
    def _copy_local(source, destination, limit, cancel, progress_offset=0, total=None):
        digest, done = hashlib.sha256(), 0
        descriptor = os.open(source, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as incoming, destination.open("xb") as outgoing:
            information = os.fstat(incoming.fileno())
            if not stat.S_ISREG(information.st_mode) or not 0 < information.st_size <= limit:
                raise VoiceError(_("Файлы голоса Piper не прошли проверку."))
            while True:
                check_cancel(cancel)
                block = incoming.read(65536)
                if not block:
                    break
                done += len(block)
                if done > limit:
                    raise VoiceError(_("Файлы голоса Piper не прошли проверку."))
                digest.update(block)
                outgoing.write(block)
                report_progress(cancel, progress_offset + done, total)
            if done != information.st_size:
                raise VoiceError(_("Файлы голоса Piper не прошли проверку."))
            outgoing.flush()
            os.fsync(outgoing.fileno())
        return digest.hexdigest(), done

    def import_model(self, onnx_path, cancel=None):
        path = Path(onnx_path)
        if path.suffix.casefold() != ".onnx":
            raise VoiceError(_("Файлы голоса Piper не прошли проверку."))
        config = path.with_name(path.name + ".json")
        stage = None
        try:
            check_cancel(cancel)
            stage = self._stage()
            model_hash, model_size = self._copy_local(path, stage / "model.onnx", MAX_MODEL_BYTES, cancel)
            with (stage / "model.onnx").open("rb") as incoming:
                header = incoming.read(16)
            if len(header) < 16 or header[0] != 0x08:
                raise VoiceError(_("Файлы голоса Piper не прошли проверку."))
            config_hash, config_size = self._copy_local(config, stage / "model.onnx.json", MAX_CONFIG_BYTES, cancel, model_size)
            language = _configuration(stage / "model.onnx.json")
            identifier = "local-" + hashlib.sha256((model_hash + config_hash).encode()).hexdigest()
            name = "".join(character for character in path.stem if character.isprintable()).strip()[:100] or identifier
            card = ("Personal Piper model imported by the user.\n"
                    "No redistribution license has been verified or granted by Malferma Libro.\n"
                    f"Original file: {name}.onnx\nLanguage declared by configuration: {language}\n")
            card_bytes = card.encode("utf-8")
            with (stage / "MODEL_CARD").open("xb") as outgoing:
                outgoing.write(card_bytes)
                outgoing.flush()
                os.fsync(outgoing.fileno())
            card_hash = hashlib.sha256(card_bytes).hexdigest()
            entry = VoiceEntry(identifier, language, name, None,
                               (VoiceFile("model.onnx", None, model_hash, model_size),
                                VoiceFile("model.onnx.json", None, config_hash, config_size),
                                VoiceFile("MODEL_CARD", None, card_hash, len(card_bytes))), local=True)
            with self._voice_operation(identifier, cancel):
                if self.get_model(language, identifier) is not None:
                    return self.voice_for(language, identifier)
                self._publish(stage, entry, {"model.onnx": model_hash, "model.onnx.json": config_hash,
                                            "MODEL_CARD": card_hash}, cancel)
            return entry
        except OSError as error:
            raise VoiceError(_("Не удалось сохранить голос Piper.")) from error
        finally:
            if stage is not None:
                shutil.rmtree(stage, ignore_errors=True)
