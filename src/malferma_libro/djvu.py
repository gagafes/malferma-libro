"""Lazy DjVu pages, decoded by Debian's DjVuLibre command-line tools.

Page indices are zero based. Only self-contained single-page or bundled DjVu
files are accepted: indirect multi-file books need to be bundled before import.
The decoder sees an isolated copy so included components cannot read nearby
files. Original page images are retained; text is optional and needs a text layer.
"""

from __future__ import annotations

from collections import OrderedDict
import math
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import tempfile
import threading
import zlib

from .i18n import _
from .native_process import run_native_command


MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_PAGES = 10_000
MAX_RENDER_DIMENSION = 4096
MAX_RENDER_PIXELS = 12 * 1024 * 1024
MAX_TEXT_BYTES = 16 * 1024 * 1024
MAX_INFO_BYTES = 256 * 1024
MAX_IMAGE_BYTES = 64 * 1024 * 1024
PROCESS_TIMEOUT = 30


def _engine_help() -> str:
    return _("Для чтения DjVu установите пакет djvulibre-bin: sudo apt install djvulibre-bin.")


class DjvuError(ValueError):
    """A DjVu document is unreadable, unsupported or exceeds a resource limit."""


def _local_file(path: Path | str) -> tuple[Path, os.stat_result]:
    try:
        resolved = Path(path).expanduser().resolve(strict=True)
        details = resolved.stat()
    except (OSError, ValueError, RuntimeError) as exc:
        raise DjvuError(_("Не удалось открыть файл DjVu")) from exc
    if not stat.S_ISREG(details.st_mode):
        raise DjvuError(_("Выберите обычный файл DjVu"))
    if not 0 < details.st_size <= MAX_FILE_BYTES:
        raise DjvuError(_("Файл DjVu пуст или превышает допустимый размер 64 МиБ"))
    return resolved, details


def _validate_container(data: bytes) -> None:
    """Check IFF bounds and reject indirect or path-based component references."""
    if len(data) < 16 or data[:8] != b"AT&TFORM":
        raise DjvuError(_("Файл не является документом DjVu"))
    end = 12 + int.from_bytes(data[8:12], "big")
    if end < 16 or end > len(data) or len(data) - end > 1:
        raise DjvuError(_("Повреждена структура файла DjVu"))
    kind = data[12:16]
    if kind not in (b"DJVU", b"DJVM"):
        raise DjvuError(_("Неподдерживаемый тип документа DjVu"))
    bundled = kind == b"DJVM"
    directories = 0
    pages = 0
    chunks = 0

    def walk(start: int, limit: int, form: bytes, depth: int = 0) -> None:
        nonlocal directories, pages, chunks
        if depth > 8:
            raise DjvuError(_("Слишком сложная структура документа DjVu"))
        has_info = False
        if form == b"DJVU":
            pages += 1
            if pages > MAX_PAGES:
                raise DjvuError(_('В DjVu допускается не более {max_pages} страниц').format(max_pages=MAX_PAGES))
        position = start
        while position < limit:
            chunks += 1
            if chunks > 200_000 or position + 8 > limit:
                raise DjvuError(_("Повреждена структура файла DjVu"))
            tag = data[position:position + 4]
            length = int.from_bytes(data[position + 4:position + 8], "big")
            body = position + 8
            tail = body + length
            if tail > limit:
                raise DjvuError(_("Повреждена структура файла DjVu"))
            if tag == b"FORM":
                if length < 4 or data[body:body + 4] not in (b"DJVU", b"DJVI", b"THUM"):
                    raise DjvuError(_("Неподдерживаемая структура документа DjVu"))
                walk(body + 4, tail, data[body:body + 4], depth + 1)
            elif tag == b"DIRM":
                directories += 1
                if not bundled or depth != 0 or length < 3 or not data[body] & 0x80:
                    raise DjvuError(
                        _("Многофайловый DjVu не поддерживается. Сначала объедините книгу "
                        "в один файл командой djvmcvt -b.")
                    )
                count = int.from_bytes(data[body + 1:body + 3], "big")
                version = data[body] & 0x7f
                if version not in (0, 1):
                    raise DjvuError(_("Неподдерживаемая версия каталога DjVu"))
                stride = 7 if version == 0 else 4
                if count < 1 or length < 3 + count * stride:
                    raise DjvuError(_("Повреждён каталог страниц DjVu"))
                for entry in range(count):
                    at = body + 3 + entry * stride
                    offset = int.from_bytes(data[at:at + 4], "big")
                    if offset < 16 or offset + 12 > end or data[offset:offset + 4] != b"FORM":
                        raise DjvuError(_("Повреждён каталог страниц DjVu"))
            elif tag == b"INFO" and form == b"DJVU":
                if length < 5 or not all(struct.unpack(">HH", data[body:body + 4])):
                    raise DjvuError(_("Недопустимый размер страницы DjVu"))
                has_info = True
            elif tag == b"INCL":
                reference = data[body:tail].rstrip(b"\x00")
                if (
                    not bundled or not reference or reference in (b".", b"..")
                    or any(character in reference for character in (b"/", b"\\", b":", b"\x00"))
                ):
                    raise DjvuError(_("DjVu с внешними файлами не поддерживается"))
            position = tail + (length & 1)
        if position > limit + 1 or (form == b"DJVU" and not has_info):
            raise DjvuError(_("Повреждена структура страницы DjVu"))

    walk(16, end, kind)
    if (bundled and directories != 1) or not pages:
        raise DjvuError(_("В DjVu не найден корректный каталог страниц"))


def _engine(name: str) -> str:
    packaged = Path("/usr/bin") / name
    if packaged.is_file() and os.access(packaged, os.X_OK):
        return str(packaged)
    found = shutil.which(name)
    if not found:
        raise DjvuError(_engine_help())
    return found


def _run(
    path: Path, name: str, arguments: list[str], *, limit: int = MAX_INFO_BYTES,
    output: str | None = None,
) -> bytes:
    """Run one bounded native operation on an isolated validated document copy."""
    source, _details = _local_file(path)
    try:
        with source.open("rb") as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise DjvuError(_("Файл DjVu превышает допустимый размер 64 МиБ"))
        _validate_container(data)
        environment = os.environ.copy()
        environment["LC_ALL"] = "C.UTF-8"
        with tempfile.TemporaryDirectory(prefix="djvu-decode-") as directory:
            document = Path(directory) / "document.djvu"
            document.write_bytes(data)
            command = [_engine(name), *arguments, str(document)]
            rendered = Path(directory) / output if output else None
            if rendered is not None:
                command.append(str(rendered))
            with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                try:
                    result = run_native_command(
                        command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                        cwd=directory, timeout=PROCESS_TIMEOUT, check=False, env=environment,
                    )
                except subprocess.TimeoutExpired as exc:
                    raise DjvuError(_("Обработка DjVu заняла слишком много времени")) from exc
                except FileNotFoundError as exc:
                    raise DjvuError(_engine_help()) from exc
                if result.returncode:
                    raise DjvuError(_("Не удалось прочитать DjVu: файл повреждён или имеет неподдерживаемую структуру"))
                if rendered is not None:
                    if not rendered.is_file() or rendered.stat().st_size > limit:
                        raise DjvuError(_("Изображение страницы DjVu превышает допустимый размер"))
                    return rendered.read_bytes()
                if stdout.tell() > limit:
                    raise DjvuError(_("Данные страницы DjVu превышают допустимый размер"))
                stdout.seek(0)
                return stdout.read(limit + 1)
    except DjvuError:
        raise
    except (OSError, ValueError, RuntimeError) as exc:
        raise DjvuError(_("Не удалось обработать DjVu. ") + _engine_help()) from exc


def _metadata_fields(data: bytes) -> dict[str, str]:
    fields = {}
    for line in data.decode("utf-8", errors="replace").splitlines():
        match = re.fullmatch(r'\s*([\w-]+)\s+"((?:[^"\\]|\\.)*)"\s*', line)
        if not match:
            continue
        raw = match.group(2).encode("utf-8")
        value = re.sub(
            rb'\\([0-7]{1,3}|.)',
            lambda item: bytes([int(item.group(1), 8) & 255])
            if re.fullmatch(rb'[0-7]{1,3}', item.group(1))
            else {b"n": b"\n", b"r": b"\r", b"t": b"\t"}.get(item.group(1), item.group(1)),
            raw,
        ).decode("utf-8", errors="replace").strip()
        fields[match.group(1).casefold()] = value
    return fields


def _ppm_png(data: bytes) -> bytes:
    """Convert DjVuLibre's bounded P6 RGB raster to a plain PNG using stdlib."""
    position = 0

    def token() -> bytes:
        nonlocal position
        while position < len(data):
            if data[position:position + 1] == b"#":
                newline = data.find(b"\n", position)
                position = newline + 1 if newline >= 0 else len(data)
            elif data[position] in b" \t\r\n\v\f":
                position += 1
            else:
                break
        start = position
        while position < len(data) and data[position] not in b" \t\r\n\v\f#":
            position += 1
        return data[start:position]

    try:
        if token() != b"P6":
            raise ValueError("not RGB PPM")
        width, height, depth = (int(token()) for _index in range(3))
        if (
            not 0 < width <= MAX_RENDER_DIMENSION or not 0 < height <= MAX_RENDER_DIMENSION
            or width * height > MAX_RENDER_PIXELS or depth != 255
            or position >= len(data) or data[position] not in b" \t\r\n\v\f"
        ):
            raise ValueError("invalid PPM geometry")
        position += 2 if data[position:position + 2] == b"\r\n" else 1
        if len(data) - position != width * height * 3:
            raise ValueError("invalid PPM data size")
    except (ValueError, OverflowError) as exc:
        raise DjvuError(_("Обработчик DjVu создал недопустимое изображение страницы")) from exc

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    compressor = zlib.compressobj()
    compressed = bytearray()
    stride = width * 3
    for row in range(height):
        at = position + row * stride
        compressed += compressor.compress(b"\x00" + data[at:at + stride])
    compressed += compressor.flush()
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", bytes(compressed)) + chunk(b"IEND", b"")
    )


class DjvuDocument:
    """A self-contained DjVu with lazy page decoding and bounded raster output.

    Page sizes are native image pixels. ``fit_width`` fits that many output
    pixels across before applying ``scale``. Both options preserve aspect ratio.
    """

    def __init__(self, path: Path | str):
        self.path, details = _local_file(path)
        self._file_size = details.st_size
        with self.path.open("rb") as stream:
            _validate_container(stream.read(MAX_FILE_BYTES + 1))
        self._lock = threading.RLock()
        self._sizes: dict[int, tuple[float, float]] = {}
        self._text: OrderedDict[int, str] = OrderedDict()
        count = _run(self.path, "djvused", ["-u", "-e", "n"]).decode("ascii", errors="replace").strip()
        try:
            self.page_count = int(count)
        except ValueError as exc:
            raise DjvuError(_("Недопустимое количество страниц DjVu")) from exc
        if not 1 <= self.page_count <= MAX_PAGES:
            raise DjvuError(_('В DjVu должно быть от 1 до {max_pages} страниц').format(max_pages=MAX_PAGES))
        fields = _metadata_fields(
            _run(self.path, "djvused", ["-u", "-e", "select 1; print-meta"])
        )
        self.title = fields.get("title", "") or self.path.stem
        self.author = fields.get("author", "") or fields.get("authors", "")

    def with_path(self, path: Path | str) -> DjvuDocument:
        """Reuse metadata for the caller's identical managed copy without a CLI."""
        target, details = _local_file(path)
        if details.st_size != self._file_size:
            raise DjvuError(_("Копирование DjVu не завершено: размер книги изменился"))
        relocated = object.__new__(type(self))
        relocated.path = target
        relocated._file_size = self._file_size
        relocated.title, relocated.author = self.title, self.author
        relocated.page_count = self.page_count
        with self._lock:
            relocated._sizes = dict(self._sizes)
            relocated._text = OrderedDict(self._text)
        relocated._lock = threading.RLock()
        return relocated

    def _check_index(self, index: int) -> None:
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < self.page_count:
            raise DjvuError(_("Номер страницы DjVu вне допустимого диапазона"))

    def page_size(self, index: int) -> tuple[float, float]:
        self._check_index(index)
        with self._lock:
            size = self._sizes.get(index)
        if size is None:
            result = _run(self.path, "djvused", ["-u", "-e", f"select {index + 1}; size"])
            match = re.search(rb"width\s*=\s*(\d+)\s+height\s*=\s*(\d+)", result)
            if not match or not all(0 < int(value) <= 65_535 for value in match.groups()):
                raise DjvuError(_("Не удалось определить размер страницы DjVu"))
            size = tuple(float(value) for value in match.groups())
            rotation = re.search(rb"\brotation\s*=\s*(\d+)", result)
            if rotation and int(rotation.group(1)) % 2:
                size = size[1], size[0]
            with self._lock:
                self._sizes[index] = size
        return size

    def page_text(self, index: int) -> str:
        self._check_index(index)
        with self._lock:
            if index in self._text:
                self._text.move_to_end(index)
                return self._text[index]
        text = _run(
            self.path, "djvutxt", [f"--page={index + 1}"], limit=MAX_TEXT_BYTES,
        ).decode("utf-8", errors="replace").strip()
        with self._lock:
            self._text[index] = text
            self._text.move_to_end(index)
            while len(self._text) > 8:
                self._text.popitem(last=False)
        return text

    def render_page(
        self, index: int, output: Path | str, *, scale: float = 1.0, fit_width: int | None = None,
    ) -> Path:
        self._check_index(index)
        try:
            scale = float(scale)
        except (TypeError, ValueError, OverflowError) as exc:
            raise DjvuError(_("Недопустимый масштаб DjVu")) from exc
        if not math.isfinite(scale) or scale <= 0:
            raise DjvuError(_("Масштаб DjVu должен быть положительным числом"))
        if fit_width is not None and (
            isinstance(fit_width, bool) or not isinstance(fit_width, int) or fit_width < 1
        ):
            raise DjvuError(_("Ширина страницы DjVu должна быть положительным целым числом"))
        width, height = self.page_size(index)
        longest, shortest = max(width, height), min(width, height)
        ratio = shortest / longest
        capped = min(MAX_RENDER_DIMENSION, int(math.sqrt(MAX_RENDER_PIXELS / ratio)))
        while capped * max(1, math.ceil(capped * ratio)) > MAX_RENDER_PIXELS:
            capped -= 1
        try:
            factor = scale if fit_width is None else fit_width / width * scale
            desired = longest * factor
        except OverflowError:
            desired = math.inf
        dimension = max(1, min(capped, math.ceil(desired) if desired < capped else capped))
        pixel_width = max(1, math.ceil(dimension * width / longest))
        pixel_height = max(1, math.ceil(dimension * height / longest))
        try:
            target = Path(output).expanduser().resolve()
            if target == self.path:
                raise DjvuError(_("Нельзя заменить файл книги изображением страницы"))
            ppm = _run(
                self.path, "ddjvu",
                ["-format=ppm", f"-page={index + 1}", f"-size={pixel_width}x{pixel_height}",
                 "-aspect=yes", "-mode=color"],
                limit=MAX_IMAGE_BYTES, output="page.ppm",
            )
            png = _ppm_png(ppm)
            with tempfile.TemporaryDirectory(prefix=".djvu-render-", dir=target.parent) as temporary:
                rendered = Path(temporary) / "page.png"
                rendered.write_bytes(png)
                rendered.replace(target)
        except DjvuError:
            raise
        except (OSError, ValueError, RuntimeError) as exc:
            raise DjvuError(_("Не удалось сохранить изображение страницы DjVu")) from exc
        return target
