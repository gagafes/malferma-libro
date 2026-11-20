# Contributing

Contributions use GPL-3.0-or-later. Preserve third-party licenses and
attribution. Keep personal books, voice models, settings and credentials out
of commits and reports.

## Report a problem or help test

Search existing issues, then use the [issue forms] to report one bug, suggest
an improvement or share a desktop test report. Follow the [manual desktop
checklist](docs/TESTING.md) and include the application and package versions,
distribution, desktop, screen scale and interface language. Mark checks you
did not run **Not tested**. Remove personal information from logs and screenshots.

[issue forms]: https://github.com/gagafes/malferma-libro/issues/new/choose

## Develop and test

Clone the repository or your fork. Use Debian 13 or Ubuntu 24.04 and the system
`/usr/bin/python3`. Install the runtime dependencies listed in the
[README](README.md#run-from-source). Install the additional build and test tools:

```sh
sudo apt install dpkg-dev python3-setuptools python3-wheel
make check
```

- Run `make gui-test` for changes to the GTK interface. It requires GTK,
  libadwaita and a graphical session. For manual checks, use
  [TESTING.md](docs/TESTING.md).
- Edit `po/*.po` and run `make translations` to regenerate the tracked MO
  catalogs. `make check` checks that the catalogs match.
- Keep the four user manuals and their copies in
  `src/malferma_libro/assets/docs/` in sync. Update the corresponding man pages
  when CLI commands or documented controls change.
- Review `git diff --check` and the staged changes. Open a pull request against
  `main` describing the change and the checks you ran.

## Build and publish

```sh
make release
(cd dist && sha256sum --check SHA256SUMS)
```

The build creates a DEB and matching ZIP and TAR.GZ source archives.
The app version comes from `src/malferma_libro/__init__.py`.
The Debian revision in `packaging/revision` is appended to it. The full
package version determines the DEB metadata, artifact names and release tag.

```sh
/usr/bin/python3 -c 'import runpy; build = runpy.run_path("packaging/build.py"); print(build["package_version"]())'
```

The [Check and build workflow] provides the `malferma-libro-current` artifact
after the build job succeeds. See the [release checklist](docs/RELEASE_CHECKLIST.md)
for publication and the [release page] for the currently published files.

[Check and build workflow]: https://github.com/gagafes/malferma-libro/actions/workflows/check.yml
[release page]: https://github.com/gagafes/malferma-libro/releases/latest
