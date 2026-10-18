"""Parse public options and provide offline documentation before loading GTK."""

from dataclasses import dataclass
import sys


class CliError(ValueError):
    """A malformed public command line; report it with exit status 2."""


def _write_utf8(text: str, stream):
    """Keep public console documents UTF-8 even in an ASCII-only locale."""
    binary = getattr(stream, "buffer", None)
    if binary is not None:
        stream.flush()
        binary.write(text.encode("utf-8"))
        binary.flush()
    else:
        stream.write(text)


@dataclass(frozen=True)
class CliOptions:
    information: str | None
    files: tuple[str, ...]
    manual_language: str | None = None

    def application_arguments(self, program: str) -> list[str]:
        # The separator keeps a book named --version or -book.txt a filename
        # when GApplication performs its own option parsing.
        return [program, *(["--", *self.files] if self.files else [])]


def parse_arguments(arguments: list[str]) -> CliOptions:
    """Recognize documented reader flags before GApplication sees filenames.

    No abbreviation or unrelated GTK debugging option is implicitly accepted.
    Options may appear between filenames until an explicit ``--`` separator.
    """
    actions = {"-h": "help", "--help": "help", "--manual": "manual",
               "--license": "license", "--version": "version"}
    from .helptext import MANUAL_LANGUAGES

    information, filenames, manual_language = None, [], None
    index, literal_files = 0, False
    while index < len(arguments):
        argument = arguments[index]
        if literal_files:
            filenames.append(argument)
        elif argument == "--":
            literal_files = True
        elif argument in actions or argument.startswith("--manual="):
            explicit_manual = argument.startswith("--manual=")
            action = "manual" if explicit_manual else actions[argument]
            if information is not None and information != action:
                raise CliError("Choose only one of --help, --manual, --license or --version.")
            information = action
            if explicit_manual:
                code = argument.split("=", 1)[1]
                if code not in MANUAL_LANGUAGES:
                    raise CliError(f"Unsupported manual language in {argument}. Choose ru, en, de or uk.")
                if manual_language is not None and manual_language != code:
                    raise CliError("Choose only one manual language with --manual=ru, --manual=en, --manual=de or --manual=uk.")
                manual_language = code
        elif argument.startswith("-"):
            raise CliError(f"Unknown option: {argument}. Use -- before a filename beginning with '-'.")
        else:
            filenames.append(argument)
        index += 1
    return CliOptions(information, tuple(filenames), manual_language)


def main(argv: list[str] | None = None):
    from .i18n import _, configure_language

    configure_language("system")
    try:
        options = parse_arguments(list(sys.argv[1:] if argv is None else argv))
    except CliError as error:
        _write_utf8(f"malferma-libro: {error}\nTry 'malferma-libro --help'.\n", sys.stderr)
        return 2
    if options.information == "version":
        from . import APP_NAME, __version__

        _write_utf8(f"{APP_NAME} {__version__}\n", sys.stdout)
        return 0
    if options.information is not None:
        from .helptext import license_text, manual_text, short_help

        readers = {"help": short_help,
                   "manual": lambda: manual_text(options.manual_language or "system"),
                   "license": license_text}
        try:
            _write_utf8(readers[options.information](), sys.stdout)
        except (OSError, UnicodeError) as error:
            _write_utf8(f"malferma-libro: Cannot read bundled documentation: {error}\n", sys.stderr)
            return 1
        return 0
    try:
        from .appearance import register_fonts

        register_fonts()
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from .app import ReaderApplication
    except (ImportError, ValueError) as error:
        _write_utf8(
            _("Для запуска нужны GTK 4, libadwaita и PyGObject. На Debian 13 выполните:\n"
              "sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 poppler-utils djvulibre-bin\n"
              "Запускайте приложение через /usr/bin/python3.\n"
              "Подробности: {error}").format(error=error) + "\n",
            sys.stderr,
        )
        return 1
    return ReaderApplication().run(options.application_arguments(sys.argv[0]))


if __name__ == "__main__":
    raise SystemExit(main())
