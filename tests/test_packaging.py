"""Release tests use temporary inputs and never overwrite a real artifact.

SPDX-License-Identifier: GPL-3.0-or-later
"""
from email.parser import Parser
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile


BUILDER_PATH = Path(__file__).resolve().parents[1] / "packaging/build.py"
spec = importlib.util.spec_from_file_location("release_builder", BUILDER_PATH)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class ReleaseBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "project"
        self.root.mkdir()
        self.put("src/malferma_libro/__init__.py", '__version__ = "0.1.0"\n')
        self.put("src/malferma_libro/reader.py", 'message = "Українська עברית"\n')
        self.put("src/malferma_libro/assets/docs/MANUAL.md", "Current manual\n")
        self.put("README.md", "Current release\n")
        self.put("LICENSE", "Test fixture license\n")
        for name in builder.SOURCE_FILES:
            if not (self.root / name).exists():
                self.put(name, (BUILDER_PATH.parents[1] / name).read_text(encoding="utf-8"))
        for name in builder.SOURCE_DIRECTORIES:
            (self.root / name).mkdir(exist_ok=True)
        self.put("packaging/malferma-libro", "#!/usr/bin/python3\n")
        self.put("packaging/build.py", BUILDER_PATH.read_text(encoding="utf-8"))
        self.put("packaging/copyright", "Copyright test fixture\n")
        self.put("packaging/control.in", (BUILDER_PATH.parent / "control.in").read_text())
        self.put("data/malferma-libro.1", ".TH MALFERMA-LIBRO 1\n")
        self.put("data/applications/example.desktop", "[Desktop Entry]\nName=Example\n")
        self.put("data/icons/hicolor/scalable/apps/example.svg", "<svg/>\n")
        self.put("data/metainfo/example.metainfo.xml", "<component/>\n")

    def put(self, relative, text):
        destination = self.root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")

    def test_release_archives_match_inputs_and_exclude_local_artifacts(self):
        self.put("dist/previous_source.zip", "old version")
        self.put("src/malferma_libro/__pycache__/reader.pyc", "cache")
        self.put(".git/config", "private repository data")
        self.put(".env", "TOKEN=secret")
        self.put("src/malferma_libro/.env.local", "TOKEN=secret")
        self.put("src/malferma_libro/reader.py~", "personal editor backup")
        self.put("malferma-libro_0.9.1_all.deb", "previous package")
        output = self.root / "dist"
        paths = builder.build_source(self.root, output, 0)
        expected = {path.relative_to(self.root).as_posix(): path.read_bytes()
                    for path in builder.source_files(self.root)}
        with tarfile.open(paths[0]) as archive:
            tar_contents = {member.name.split("/", 1)[1]: archive.extractfile(member).read()
                            for member in archive.getmembers() if member.isfile()}
        with zipfile.ZipFile(paths[1]) as archive:
            zip_contents = {name.split("/", 1)[1]: archive.read(name) for name in archive.namelist()}
            launcher = archive.getinfo("malferma-libro-0.1.0/packaging/malferma-libro")
            self.assertEqual((launcher.external_attr >> 16) & 0o777, 0o755)
        self.assertEqual(tar_contents, expected)
        self.assertEqual(zip_contents, expected)
        self.assertFalse(any("previous" in name or "__pycache__" in name or name.startswith(".git/")
                             or name.endswith((".deb", "~")) or ".env" in name for name in expected))
        original = [path.read_bytes() for path in paths]
        os.utime(self.root / "README.md", (1720000000, 1720000000))
        rebuilt = builder.build_source(self.root, output, 0)
        self.assertEqual([path.read_bytes() for path in rebuilt], original)

    def test_source_archives_preserve_compressed_project_inputs(self):
        # ZIP/GZIP can be source fixtures or runtime assets. Only generated
        # output directories should exclude them from a source release.
        self.put("tests/fixtures/book.zip", "archive fixture")
        self.put("data/example.txt.gz", "compressed data")
        paths = builder.build_source(self.root, self.root / "dist", 0)
        with zipfile.ZipFile(paths[1]) as archive:
            for name in ("tests/fixtures/book.zip", "data/example.txt.gz"):
                self.assertEqual(archive.read(f"malferma-libro-0.1.0/{name}"),
                                 (self.root / name).read_bytes())

    @unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb is unavailable")
    def test_debian_payload_control_and_reproducible_build(self):
        self.put("src/malferma_libro/.env.local", "TOKEN=secret")
        output = self.root / "dist"
        path = builder.build_deb(self.root, output, 0)
        original = path.read_bytes()
        metadata = subprocess.check_output(["dpkg-deb", "-f", str(path), "Version"], text=True)
        self.assertEqual(metadata.strip(), "0.1.0")
        payload_tar = subprocess.check_output(["dpkg-deb", "--fsys-tarfile", str(path)])
        with tarfile.open(fileobj=io.BytesIO(payload_tar)) as archive:
            names = archive.getnames()
            self.assertIn("./usr/share/malferma-libro/malferma_libro/reader.py", names)
            self.assertIn("./usr/share/man/man1/malferma-libro.1.gz", names)
            self.assertIn("./usr/share/doc/malferma-libro/copyright", names)
            self.assertFalse(any("/dist/" in name or "/tests/" in name for name in names))
            self.assertFalse(any(".env" in name for name in names))
            for member in archive.getmembers():
                self.assertEqual((member.uid, member.gid, member.mtime), (0, 0, 0))
            launcher = archive.getmember("./usr/bin/malferma-libro")
            self.assertEqual(launcher.mode, 0o755)
        rebuilt = builder.build_deb(self.root, output, 0)
        self.assertEqual(rebuilt.read_bytes(), original)
        builder.write_checksums(output, "0.1.0")
        self.assertEqual((output / "SHA256SUMS").read_text(),
                         f"{hashlib.sha256(original).hexdigest()}  {path.name}\n")

    def test_checksums_do_not_include_unrelated_backups(self):
        output = self.root / "dist"
        output.mkdir()
        artifact = output / "malferma-libro_0.1.0_source.zip"
        artifact.write_bytes(b"release")
        (output / "malferma-libro_0.1.0_source.zip.backup").write_bytes(b"old content")
        builder.write_checksums(output, "0.1.0")
        self.assertEqual((output / "SHA256SUMS").read_text(),
                         f"{hashlib.sha256(b'release').hexdigest()}  {artifact.name}\n")

    @unittest.skipUnless(shutil.which("dpkg-deb") and shutil.which("dpkg"),
                         "Debian package tools are unavailable")
    def test_debian_revision_upgrades_and_preserves_reproducible_corresponding_source(self):
        self.put("packaging/revision", "1\n")
        for directory in builder.SOURCE_DIRECTORIES:
            self.put(f"{directory}/release-input.txt", "Corresponding source input\n")
        output = self.root / "dist"
        self.assertEqual(builder.version(self.root), "0.1.0")
        self.assertEqual(builder.package_version(self.root), "0.1.0-1")
        package = builder.build_deb(self.root, output, 0)
        self.assertEqual(package.name, "malferma-libro_0.1.0-1_all.deb")
        metadata = subprocess.check_output(["dpkg-deb", "-f", str(package), "Version"], text=True)
        self.assertEqual(metadata.strip(), "0.1.0-1")
        subprocess.run(["dpkg", "--compare-versions", metadata.strip(), "gt", "0.1.0"], check=True)
        source = builder.build_source(self.root, output, 0)
        original = [path.read_bytes() for path in [package, *source]]
        prefix = "malferma-libro-0.1.0-1/"
        with zipfile.ZipFile(source[1]) as archive:
            self.assertEqual(archive.read(prefix + "packaging/revision"), b"1\n")
            archive.extractall(Path(self.temporary.name) / "extracted")
        extracted = Path(self.temporary.name) / "extracted" / prefix
        corresponding = Path(self.temporary.name) / "rebuilt"
        rebuilt = [builder.build_deb(extracted, corresponding, 0),
                   *builder.build_source(extracted, corresponding, 0)]
        self.assertEqual([path.read_bytes() for path in rebuilt], original)
        builder.write_checksums(output, builder.package_version(self.root))
        expected = "".join(f"{hashlib.sha256(contents).hexdigest()}  {path.name}\n"
                           for path, contents in zip([package, *source], original))
        self.assertEqual((output / "SHA256SUMS").read_text(), expected)

    def test_optional_and_invalid_debian_revisions(self):
        self.assertEqual(builder.package_version(self.root), builder.version(self.root))
        for value in ("", "0", "-1", "01", "1.0", "1-2", "١", "1\n2"):
            with self.subTest(value=value):
                self.put("packaging/revision", value)
                with self.assertRaises(ValueError):
                    builder.package_version(self.root)
        revision = self.root / "packaging/revision"
        revision.unlink()
        revision.symlink_to(self.root / "missing-revision")
        with self.assertRaises(ValueError):
            builder.package_version(self.root)

    def test_incomplete_release_inputs_fail_before_writing_archives(self):
        for name in ("LICENSE", "Makefile", "tests"):
            path = self.root / name
            hidden = path.with_name(path.name + ".missing")
            path.rename(hidden)
            try:
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, "Required"):
                    builder.build_source(self.root, self.root / "dist", 0)
                self.assertFalse((self.root / "dist").exists())
            finally:
                hidden.rename(path)

    def test_deb_does_not_follow_symlinked_documents_or_source_ancestors(self):
        outside = Path(self.temporary.name) / "outside.txt"
        outside.write_text("private data")
        original = self.root / "README.md"
        original.unlink()
        original.symlink_to(outside)
        with self.assertRaises(ValueError):
            builder.build_deb(self.root, self.root / "dist", 0)
        original.unlink()
        original.write_text("Current release\n")
        source = self.root / "src"
        renamed = self.root / "external-src"
        source.rename(renamed)
        source.symlink_to(renamed, target_is_directory=True)
        with self.assertRaises(ValueError):
            builder.build_deb(self.root, self.root / "dist", 0)
        self.assertFalse((self.root / "dist").exists())

    @unittest.skipUnless(importlib.util.find_spec("setuptools"), "setuptools is unavailable")
    def test_python_distributions_include_runtime_and_source_inputs(self):
        self.put("MANIFEST.in", (BUILDER_PATH.parents[1] / "MANIFEST.in").read_text())
        self.put(".github/workflows/check.yml", "name: Source fixture\n")
        self.put("po/en.po", 'msgid "Book"\nmsgstr "Book"\n')
        self.put("src/malferma_libro/locale/en/LC_MESSAGES/malferma-libro.mo", "compiled catalog")
        self.put("src/malferma_libro/.env.local", "TOKEN=secret")
        self.put("src/malferma_libro/assets/notes.txt~", "personal editor backup")
        command = (
            "from setuptools.build_meta import build_wheel, build_sdist; "
            "build_wheel('dist'); build_sdist('dist')"
        )
        subprocess.run([sys.executable, "-B", "-c", command], cwd=self.root,
                       check=True, capture_output=True, text=True)
        with zipfile.ZipFile(next((self.root / "dist").glob("*.whl"))) as archive:
            names = archive.namelist()
            self.assertIn("malferma_libro/assets/docs/MANUAL.md", names)
            self.assertIn("malferma_libro/locale/en/LC_MESSAGES/malferma-libro.mo", names)
            self.assertFalse(any(".env" in name or name.endswith("~") for name in names))
            metadata = archive.read("malferma_libro-0.1.0.dist-info/METADATA").decode()
            # Setuptools versions differ in optional requirement whitespace.
            # Compare metadata fields while keeping names and version bounds exact.
            requirements = {"".join(value.split()) for value in
                            Parser().parsestr(metadata).get_all("Requires-Dist", [])}
            self.assertEqual(requirements, {"PyGObject>=3.42", "markdown-it-py>=3.0.0"})
            entry_points = archive.read("malferma_libro-0.1.0.dist-info/entry_points.txt").decode()
            self.assertIn("malferma-libro = malferma_libro.__main__:main", entry_points)
        with tarfile.open(next((self.root / "dist").glob("*.tar.gz"))) as archive:
            names = {name.split("/", 1)[1] for name in archive.getnames() if "/" in name}
            self.assertFalse(any(".env" in name or name.endswith("~") for name in names))
            for name in ("LICENSE", "Makefile", "packaging/build.py", "po/en.po",
                         ".github/workflows/check.yml"):
                self.assertIn(name, names)

    def test_source_symlinks_cannot_pull_files_from_outside_project(self):
        target = Path(self.temporary.name) / "outside.txt"
        target.write_text("outside data")
        (self.root / "src/malferma_libro/outside.txt").symlink_to(target)
        with self.assertRaises(ValueError):
            builder.build_source(self.root, self.root / "dist", 0)

    def test_invalid_source_date_epoch_is_rejected(self):
        for value in ("-1", "1.5", "tomorrow", "١٢", "4294967296"):
            with self.subTest(value=value), patch.dict(os.environ, SOURCE_DATE_EPOCH=value):
                with self.assertRaises(ValueError):
                    builder.source_epoch()
