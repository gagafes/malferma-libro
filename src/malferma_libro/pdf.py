"""Lazy PDF metadata, text and original-layout rendering through Poppler.

No GTK objects or PDF executable content are evaluated by the reader.  Each
operation invokes one of Debian's ``poppler-utils`` programs without a shell,
on a single local document and (for text/rendering) a single requested page.
Page indices are zero based; page sizes use PDF points at 72 points per inch.
Saved reading positions belong to the viewport, not to extracted text offsets.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
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

from .i18n import _
from .native_process import run_native_command


MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_PAGES = 10_000
MAX_RENDER_DIMENSION = 4096
MAX_RENDER_PIXELS = 12 * 1024 * 1024
MAX_TEXT_BYTES = 16 * 1024 * 1024
MAX_INFO_BYTES = 256 * 1024
MAX_PNG_BYTES = 64 * 1024 * 1024
PROCESS_TIMEOUT = 30
_PAGE_SIZE = re.compile(
    r"^Page(?:\s+\d+)?\s+size:\s*([\d.+eE-]+)\s+x\s+([\d.+eE-]+)\s+pts\b",
    re.MULTILINE,
)
_PAGE_ROTATION = re.compile(r"^Page(?:\s+\d+)?\s+rot:\s*(-?\d+)", re.MULTILINE)


def _engine_help() -> str:
    return _("Для чтения PDF установите пакет poppler-utils: sudo apt install poppler-utils.")


class PdfError(ValueError):
    """A PDF is unreadable, unsupported or exceeds a resource limit."""


class PdfPasswordRequired(PdfError):
    """The PDF requires a password, or the supplied password was rejected."""


@dataclass(frozen=True)
class PdfMetadata:
    title: str
    author: str
    page_count: int


def _local_file(path: Path | str) -> tuple[Path, os.stat_result]:
    try:
        resolved = Path(path).expanduser().resolve(strict=True)
        details = resolved.stat()
    except (OSError, ValueError, RuntimeError) as exc:
        raise PdfError(_("Не удалось открыть файл PDF")) from exc
    if not stat.S_ISREG(details.st_mode):
        raise PdfError(_("Выберите обычный файл PDF"))
    if not 0 < details.st_size <= MAX_FILE_BYTES:
        raise PdfError(_("Файл PDF пуст или превышает допустимый размер 64 МиБ"))
    return resolved, details


def _engine(name: str) -> str:
    # On Debian use the package executable directly.  Some launchers wrap PATH
    # commands for unrelated export workflows and do not expose Poppler's CLI.
    packaged = Path("/usr/bin") / name
    if packaged.is_file() and os.access(packaged, os.X_OK):
        return str(packaged)
    found = shutil.which(name)
    if not found:
        raise PdfError(_engine_help())
    return found


def _run(name: str, arguments: list[str], *, limit: int = MAX_INFO_BYTES) -> bytes:
    """Capture output on disk so an unusually large page cannot fill RAM."""
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        try:
            result = run_native_command(
                [_engine(name), *arguments],
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=errors,
                timeout=PROCESS_TIMEOUT,
                check=False,
                env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            raise PdfError(_("Обработка PDF заняла слишком много времени")) from exc
        except FileNotFoundError as exc:
            raise PdfError(_engine_help()) from exc
        except OSError as exc:
            raise PdfError(_("Не удалось запустить обработчик PDF. ") + _engine_help()) from exc
        if result.returncode:
            errors.seek(0)
            diagnostic = errors.read(8192).decode("utf-8", errors="replace")
            if "password" in diagnostic.lower():
                raise PdfPasswordRequired(
                    _("PDF защищён паролем. Откройте незашифрованную копию книги.")
                )
            if "permission" in diagnostic.lower() or "copying of text" in diagnostic.lower():
                raise PdfError(_("Автор PDF запретил извлечение текста из этого документа"))
            raise PdfError(_("Не удалось прочитать PDF: файл повреждён или имеет неподдерживаемую структуру"))
        if output.tell() > limit:
            raise PdfError(_("Данные страницы PDF превышают допустимый размер"))
        output.seek(0)
        return output.read(limit + 1)


def _size_from_info(info: str) -> tuple[float, float]:
    match = _PAGE_SIZE.search(info)
    if not match:
        raise PdfError(_("Не удалось определить размер страницы PDF"))
    try:
        width, height = map(float, match.groups())
    except ValueError as exc:
        raise PdfError(_("Недопустимый размер страницы PDF")) from exc
    if not all(math.isfinite(value) and value > 0 for value in (width, height)):
        raise PdfError(_("Недопустимый размер страницы PDF"))
    rotation = _PAGE_ROTATION.search(info)
    if rotation and int(rotation.group(1)) % 180:
        width, height = height, width
    return width, height


class PdfDocument:
    """A local PDF with lazy per-page operations and a small text cache.

    ``scale=1`` renders at 72 dpi.  With ``fit_width`` the page first fits that
    many pixels across, then ``scale`` applies zoom.  Both paths retain the
    aspect ratio, page rotation, illustrations and typography, subject to the
    same raster limits.  Text extraction is optional: scans still render.
    """

    def __init__(self, path: Path | str, password: str | None = None):
        self.path, details = _local_file(path)
        self._file_size = details.st_size
        if password is not None and (not isinstance(password, str) or "\x00" in password):
            raise PdfError(_("Недопустимый пароль PDF"))
        self._password = password
        self._sizes: dict[int, tuple[float, float]] = {}
        self._text: OrderedDict[int, str] = OrderedDict()
        self._lock = threading.RLock()
        info = self._info()
        fields = dict(
            (key.strip(), value.strip())
            for line in info.splitlines()
            if ":" in line
            for key, value in [line.split(":", 1)]
        )
        try:
            self.page_count = int(fields.get("Pages", "0"))
        except ValueError as exc:
            raise PdfError(_("Недопустимое количество страниц PDF")) from exc
        if not 1 <= self.page_count <= MAX_PAGES:
            raise PdfError(_('В PDF должно быть от 1 до {max_pages} страниц').format(max_pages=MAX_PAGES))
        self.title = fields.get("Title", "").strip() or self.path.stem
        self.author = fields.get("Author", "").strip()
        self._sizes[0] = _size_from_info(info)

    def with_path(self, path: Path | str) -> PdfDocument:
        """Relocate metadata to the caller's identical managed copy, without CLI.

        The caller has already copied this document's bytes.  Size validation
        catches an incomplete copy; this method deliberately does not reparse
        the PDF or hash a potentially large book on the GTK main thread.
        """
        target, details = _local_file(path)
        if details.st_size != self._file_size:
            raise PdfError(_("Копирование PDF не завершено: размер книги изменился"))
        relocated = object.__new__(type(self))
        relocated.path = target
        relocated._file_size = self._file_size
        relocated._password = self._password
        relocated.title = self.title
        relocated.author = self.author
        relocated.page_count = self.page_count
        with self._lock:
            relocated._sizes = dict(self._sizes)
            relocated._text = OrderedDict(self._text)
        relocated._lock = threading.RLock()
        return relocated

    def _password_arguments(self) -> list[str]:
        return ["-upw", self._password] if self._password is not None else []

    def _info(self, index: int | None = None) -> str:
        arguments = ["-enc", "UTF-8", *self._password_arguments()]
        if index is not None:
            arguments.extend(["-f", str(index + 1), "-l", str(index + 1)])
        arguments.append(str(self.path))
        return _run("pdfinfo", arguments).decode("utf-8", errors="replace")

    def _check_index(self, index: int) -> None:
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < self.page_count:
            raise PdfError(_("Номер страницы PDF вне допустимого диапазона"))

    def page_size(self, index: int) -> tuple[float, float]:
        """Return the displayed page width/height in points, including rotation."""
        self._check_index(index)
        with self._lock:
            size = self._sizes.get(index)
        if size is None:
            size = _size_from_info(self._info(index))
            with self._lock:
                self._sizes[index] = size
        return size

    def page_text(self, index: int) -> str:
        """Extract one page's UTF-8 text, or return empty text for an image scan."""
        self._check_index(index)
        with self._lock:
            if index in self._text:
                self._text.move_to_end(index)
                return self._text[index]
        page = str(index + 1)
        text = _run(
            "pdftotext",
            ["-f", page, "-l", page, "-enc", "UTF-8", "-layout", "-nopgbrk",
             *self._password_arguments(), str(self.path), "-"],
            limit=MAX_TEXT_BYTES,
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
        """Atomically write a single bounded PNG; leave existing output on error."""
        self._check_index(index)
        try:
            scale = float(scale)
        except (TypeError, ValueError, OverflowError) as exc:
            raise PdfError(_("Недопустимый масштаб PDF")) from exc
        if not math.isfinite(scale) or scale <= 0:
            raise PdfError(_("Масштаб PDF должен быть положительным числом"))
        if fit_width is not None and (
            isinstance(fit_width, bool) or not isinstance(fit_width, int) or fit_width < 1
        ):
            raise PdfError(_("Ширина страницы PDF должна быть положительным целым числом"))
        width, height = self.page_size(index)
        longest, shortest = max(width, height), min(width, height)
        ratio = shortest / longest
        # Limit dimensions *before* Poppler allocates its page raster, including
        # the short-axis rounding that happens for very unusual page shapes.
        capped = MAX_RENDER_DIMENSION
        if ratio > MAX_RENDER_PIXELS / (MAX_RENDER_DIMENSION * MAX_RENDER_DIMENSION):
            capped = min(capped, int(math.sqrt(MAX_RENDER_PIXELS / ratio)))
        while capped * max(1, math.ceil(capped * ratio)) > MAX_RENDER_PIXELS:
            capped -= 1
        try:
            factor = scale if fit_width is None else (fit_width / width) * scale
            desired = longest * factor
        except OverflowError:
            desired = math.inf
        dimension = max(1, min(capped, math.ceil(desired) if desired < capped else capped))
        try:
            target = Path(output).expanduser().resolve()
            if target == self.path:
                raise PdfError(_("Нельзя заменить файл книги изображением страницы"))
            with tempfile.TemporaryDirectory(prefix=".pdf-render-", dir=target.parent) as temporary:
                prefix = Path(temporary) / "page"
                page = str(index + 1)
                _run(
                    "pdftoppm",
                    ["-f", page, "-l", page, "-singlefile", "-png", "-cropbox", "-r", "72",
                     "-scale-to", str(dimension), *self._password_arguments(),
                     str(self.path), str(prefix)],
                )
                rendered = prefix.with_suffix(".png")
                if not rendered.is_file() or not 24 <= rendered.stat().st_size <= MAX_PNG_BYTES:
                    raise PdfError(_("Обработчик PDF не создал изображение страницы"))
                with rendered.open("rb") as image:
                    header = image.read(24)
                if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
                    raise PdfError(_("Обработчик PDF создал недопустимое изображение"))
                pixel_width, pixel_height = struct.unpack(">II", header[16:24])
                if not (
                    0 < pixel_width <= MAX_RENDER_DIMENSION
                    and 0 < pixel_height <= MAX_RENDER_DIMENSION
                    and pixel_width * pixel_height <= MAX_RENDER_PIXELS
                ):
                    raise PdfError(_("Изображение страницы PDF превышает допустимый размер"))
                rendered.replace(target)
        except PdfError:
            raise
        except (OSError, ValueError, RuntimeError) as exc:
            raise PdfError(_("Не удалось сохранить изображение страницы PDF")) from exc
        return target


def metadata(path: Path | str, password: str | None = None) -> PdfMetadata:
    """Read document metadata without extracting text or rendering any page."""
    document = PdfDocument(path, password)
    return PdfMetadata(document.title, document.author, document.page_count)
