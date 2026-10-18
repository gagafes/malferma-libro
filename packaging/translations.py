#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Extract, compile and check the reader's UTF-8 gettext catalogs.

Uses Python's standard library so Debian builds do not need gettext tools.
PO files are the editable source; MO files are generated package resources.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import gettext
import io
import json
from pathlib import Path
import re
import string
import struct

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "malferma_libro"
PO_DIR = ROOT / "po"
DOMAIN = "malferma-libro"
VERSION = "0.1.0"


@dataclass
class Entry:
    msgid: str
    translations: dict[int, str] = field(default_factory=dict)
    context: str | None = None
    plural: str | None = None
    fuzzy: bool = False
    obsolete: bool = False

    @property
    def key(self) -> str:
        return (self.context + "\x04" if self.context is not None else "") + self.msgid


def source_messages() -> dict[str, list[str]]:
    """Find literal source messages, including the live-translation alias."""
    references: dict[str, list[str]] = defaultdict(list)
    for path in sorted(SOURCE.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id not in {"_", "N_", "localized"} or not node.args:
                continue
            value = node.args[0]
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                references[value.value].append(f"{path.relative_to(ROOT)}:{node.lineno}")
    return dict(references)


def read_po(path: Path) -> list[Entry]:
    """Read the conventional PO syntax; obsolete entries remain untranslated."""
    entries: list[Entry] = []
    values: dict[str, str] = {}
    active: str | None = None
    fuzzy = False
    obsolete = False

    def finish() -> None:
        nonlocal values, active, fuzzy, obsolete
        if values:
            if "msgid" not in values:
                raise ValueError(f"{path}: entry without msgid")
            translations = {int(key[7:-1]): value for key, value in values.items()
                            if key.startswith("msgstr[")}
            if "msgstr" in values:
                if translations:
                    raise ValueError(f"{path}: mixed singular and plural msgstr")
                translations[0] = values["msgstr"]
            entries.append(Entry(values["msgid"], translations, values.get("msgctxt"),
                                 values.get("msgid_plural"), fuzzy, obsolete))
        values, active, fuzzy, obsolete = {}, None, False, False

    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            finish()
            continue
        if line.startswith("#~"):
            obsolete = True
            line = line[2:].lstrip()
        elif line.startswith("#"):
            fuzzy = fuzzy or (line.startswith("#,") and "fuzzy" in {flag.strip() for flag in line[2:].split(",")})
            continue
        if line.startswith('"'):
            if active is None:
                raise ValueError(f"{path}:{number}: orphan continuation")
            token = line
        else:
            match = re.fullmatch(r'(msgctxt|msgid_plural|msgid|msgstr(?:\[\d+\])?)\s+(".*")', line)
            if not match:
                raise ValueError(f"{path}:{number}: unsupported PO syntax")
            active, token = match.groups()
            if active in values:
                raise ValueError(f"{path}:{number}: duplicate {active}")
            values[active] = ""
        value = ast.literal_eval(token)
        if not isinstance(value, str):
            raise ValueError(f"{path}:{number}: expected a string")
        values[active] += value
    finish()
    if len({entry.key for entry in entries}) != len(entries):
        raise ValueError(f"{path}: duplicate translation keys")
    return entries


def write_po(path: Path, entries: list[Entry], references: dict[str, list[str]]) -> None:
    provenance = ("# Generated from the current Python source."
                  if path.suffix == ".pot" else
                  "# Translation source recovered from the installed GNU gettext catalog.")
    lines = ["# SPDX-License-Identifier: GPL-3.0-or-later", provenance, ""]
    quote = lambda value: json.dumps(value, ensure_ascii=False)
    for entry in sorted(entries, key=lambda item: (item.obsolete, item.key)):
        start = len(lines)
        if entry.msgid and not entry.obsolete and (refs := references.get(entry.msgid)):
            lines.append("#: " + " ".join(sorted(refs)))
        if entry.fuzzy:
            lines.append("#, fuzzy")
        if entry.context is not None:
            lines.append("msgctxt " + quote(entry.context))
        lines.append("msgid " + quote(entry.msgid))
        if entry.plural is not None:
            lines.append("msgid_plural " + quote(entry.plural))
            lines.extend(f"msgstr[{index}] {quote(value)}"
                         for index, value in sorted(entry.translations.items()))
        else:
            lines.append("msgstr " + quote(entry.translations.get(0, "")))
        if entry.obsolete:
            lines[start:] = ["#~ " + line for line in lines[start:]]
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def compile_mo(entries: list[Entry]) -> bytes:
    messages: dict[bytes, bytes] = {}
    for entry in entries:
        if entry.obsolete or entry.fuzzy or (entry.msgid and not any(entry.translations.values())):
            continue
        key = entry.key + ("\0" + entry.plural if entry.plural is not None else "")
        value = "\0".join(entry.translations[index] for index in sorted(entry.translations))
        messages[key.encode("utf-8")] = value.encode("utf-8")
    ordered = sorted(messages.items())
    count = len(ordered)
    offset = 28 + 16 * count
    original_table, translated_table = [], []
    originals = bytearray()
    translated = bytearray()
    for key, _value in ordered:
        original_table.extend((len(key), offset + len(originals)))
        originals.extend(key + b"\0")
    offset += len(originals)
    for _key, value in ordered:
        translated_table.extend((len(value), offset + len(translated)))
        translated.extend(value + b"\0")
    return (struct.pack("<7I", 0x950412DE, 0, count, 28, 28 + 8 * count, 0, 0)
            + struct.pack(f"<{len(original_table)}I", *original_table)
            + struct.pack(f"<{len(translated_table)}I", *translated_table)
            + originals + translated)


def format_fields(value: str) -> Counter:
    """Check named fields, conversions and nested format specifications."""
    fields: Counter = Counter()
    for _literal, name, spec, conversion in string.Formatter().parse(value):
        if name is not None:
            fields[(name, spec, conversion)] += 1
            fields.update(format_fields(spec))
    return fields


def validate(entries: list[Entry], language: str, expected: set[str]) -> bytes:
    entries = [entry for entry in entries if not entry.obsolete]
    by_key = {entry.key: entry for entry in entries}
    if set(by_key) != expected | {""}:
        missing = sorted(expected - by_key.keys())
        extra = sorted(by_key.keys() - expected - {""})
        raise ValueError(f"{language}: source/catalog mismatch; missing={missing}, extra={extra}")
    for entry in entries:
        if entry.fuzzy:
            raise ValueError(f"{language}: fuzzy entry: {entry.msgid!r}")
        if entry.msgid and (not entry.translations or not all(entry.translations.values())):
            raise ValueError(f"{language}: untranslated entry: {entry.msgid!r}")
        if entry.plural is None and set(entry.translations) != {0}:
            raise ValueError(f"{language}: invalid singular translation: {entry.msgid!r}")
        if entry.plural is not None and format_fields(entry.msgid) != format_fields(entry.plural):
            raise ValueError(f"{language}: singular/plural fields differ: {entry.msgid!r}")
        for value in entry.translations.values():
            if entry.msgid and format_fields(entry.msgid) != format_fields(value):
                raise ValueError(f"{language}: format fields differ: {entry.msgid!r}")
    data = compile_mo(entries)
    translated = gettext.GNUTranslations(io.BytesIO(data))
    metadata = translated.info()
    if metadata.get("language") != language:
        raise ValueError(f"{language}: Language header differs")
    if metadata.get("project-id-version") != f"Malferma Libro {VERSION}":
        raise ValueError(f"{language}: Project-Id-Version differs")
    if metadata.get("content-type", "").lower() != "text/plain; charset=utf-8":
        raise ValueError(f"{language}: UTF-8 Content-Type header required")
    match = re.fullmatch(r"\s*nplurals=(\d+);\s*plural=(.+);\s*", metadata.get("plural-forms", ""))
    if not match:
        raise ValueError(f"{language}: invalid Plural-Forms header")
    count = int(match[1])
    try:
        invalid_plural = not 1 <= count <= 6 or any(
            not 0 <= translated.plural(n) < count for n in (*range(201), 1000, 1_000_000))
    except ArithmeticError as error:
        raise ValueError(f"{language}: invalid plural expression: {error}") from error
    if invalid_plural:
        raise ValueError(f"{language}: plural expression out of range")
    for entry in entries:
        if entry.plural is not None and set(entry.translations) != set(range(count)):
            raise ValueError(f"{language}: missing plural forms: {entry.msgid!r}")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true", help="validate source coverage, PO and compiled MO catalogs")
    action.add_argument("--compile", action="store_true", help="validate PO catalogs and regenerate installed MO files")
    action.add_argument("--extract", action="store_true", help="refresh the POT template and source references in PO files")
    parser.add_argument("--output-dir", type=Path, default=SOURCE / "locale",
                        help="compiled locale directory (default: src/malferma_libro/locale)")
    args = parser.parse_args()
    try:
        references = source_messages()
        template = PO_DIR / f"{DOMAIN}.pot"
        if args.extract:
            header = (f"Project-Id-Version: Malferma Libro {VERSION}\n"
                      "MIME-Version: 1.0\nContent-Type: text/plain; charset=UTF-8\n"
                      "Content-Transfer-Encoding: 8bit\n")
            write_po(template, [Entry("", {0: header}), *(Entry(key, {0: ""}) for key in references)], references)
            for path in sorted(PO_DIR.glob("*.po")):
                entries = read_po(path)
                for entry in entries:
                    entry.obsolete = bool(entry.msgid and entry.msgid not in references)
                existing = {entry.msgid for entry in entries}
                entries.extend(Entry(key, {0: ""}) for key in references if key not in existing)
                write_po(path, entries, references)
            print(f"Extracted {len(references)} messages into {template.relative_to(ROOT)}")
            return 0
        if {entry.key for entry in read_po(template)} != set(references) | {""}:
            raise ValueError("POT template differs from source; run --extract")
        paths = sorted(PO_DIR.glob("*.po"))
        language_choices = next(node.value for node in ast.parse((SOURCE / "i18n.py").read_text(encoding="utf-8")).body
                                if isinstance(node, ast.Assign)
                                and any(isinstance(target, ast.Name) and target.id == "LANGUAGE_CHOICES"
                                        for target in node.targets))
        expected_languages = {code for code, _name in ast.literal_eval(language_choices)} - {"ru"}
        if {path.stem for path in paths} != expected_languages:
            raise ValueError("PO and supported language sets differ")
        for path in paths:
            data = validate(read_po(path), path.stem, set(references))
            target = args.output_dir / path.stem / "LC_MESSAGES" / f"{DOMAIN}.mo"
            if args.compile:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            else:
                if not target.is_file():
                    raise ValueError(f"{path.stem}: compiled MO is missing; run --compile: {target}")
                with target.open("rb") as stream:
                    installed = gettext.GNUTranslations(stream)
                generated = gettext.GNUTranslations(io.BytesIO(data))
                if installed._catalog != generated._catalog:
                    raise ValueError(f"{path.stem}: MO differs from editable PO; run --compile")
        print(f"{'Compiled' if args.compile else 'Checked'} {len(paths)} catalogs, {len(references)} messages each")
        return 0
    except (OSError, SyntaxError, ValueError, KeyError, TypeError, struct.error) as error:
        parser.exit(1, f"Translation error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
