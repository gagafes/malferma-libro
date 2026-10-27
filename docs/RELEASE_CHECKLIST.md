<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Release readiness: DEB 0.1.1-4

Application version: **0.1.1**. Debian package revision: **0.1.1-4**.
This security update supersedes the published 0.1.1-3 package. Its existing
tag and assets remain unchanged. Version 1.0 remains reserved for the owner's
production milestone.

The release contains the DEB, matching ZIP and TAR.GZ source archives, and
`SHA256SUMS`. The [release page](https://github.com/gagafes/malferma-libro/releases/tag/v0.1.1-4)
and [Actions runs](https://github.com/gagafes/malferma-libro/actions)
provide the published artifact and workflow results.

## Automated checks

The **Check and build** workflow must pass for the exact source commit being
released. Publication requires the source/build job, the Debian 13 installation
job, and both Ubuntu 24.04 scenarios (fresh installation and upgrade).

- Source tests, all translation catalogs, desktop metadata and native GTK tests.
- Native illustration checks at 200% scale.
- DEB, corresponding source archives and verified `SHA256SUMS`.
- Fresh APT installation on Debian 13 and Ubuntu 24.04, installed CLI/manuals/resources and runtime dependencies.
- Upgrade from the checksum-pinned published 0.1.1-3 DEB, preserving a seeded
  test library, book bytes, reading position, bookmarks, notes and settings.
- Native GTK tests against the installed package on both distributions, also at 200% scale.
- Ubuntu fresh/upgrade scenarios use the candidate artifact and SHA256SUMS from
  the same workflow run. Minimal-image documentation exclusions are removed and
  the real man command is restored before strict installed-file verification.

The installation test uses an isolated profile under an unprivileged test
account. Its automated library checks do not represent a user's personal library.

The fixes' merged source commit `8b936ee7f697081b04b0e5ddc3a40d09b467792a`
passed [CI 40372419964](https://github.com/gagafes/malferma-libro/actions/runs/40372419964)
on 2026-10-26: 289 source-suite entries (two native test classes skipped there
and exercised separately), 48 translation catalogs, native UI/illustration
checks at normal and 200% scale, package/source builds and Debian installation
and upgrade. The final publication workflow repeats the checks for 0.1.1-4
and uses published 0.1.1-3 as the upgrade baseline.

## Published Ubuntu package result — 2026-10-27

[Workflow 40481338889](https://github.com/gagafes/malferma-libro/actions/runs/40481338889)
passed with the published DEBs in Ubuntu 24.04 amd64 containers. Both fresh
installation of 0.1.1-4 and upgrade from 0.1.1-3 succeeded, including SHA-256,
installed-file/dependency/CLI/manual checks and preservation of book bytes,
positions, bookmarks, notes, settings and OPDS configuration. Each scenario
passed 18 native GTK tests and eight illustration tests at 200% scale under Xvfb.
The exact tested checksum and scope are recorded in [VALIDATION.md](../VALIDATION.md).

## Manual desktop result

On 2026-10-26, the owner confirmed that the manual check of the new build had
been performed. The tested build checksum, OS/session, interface language,
scale and individual checklist outcomes were not supplied. The earlier
XFCE 4.20 report for 0.1.1-3 is retained in [VALIDATION.md](../VALIDATION.md).
The reusable detailed procedure remains in [TESTING.md](TESTING.md).

| Check | Result | Evidence |
| --- | --- | --- |
| Manual check of the new build | Performed, as reported by owner | Owner's confirmation on 2026-10-26 |
| Installation on Ubuntu 24.04 | Successful, as reported by owner | Owner's confirmation on 2026-10-27; exact installed checksum not supplied |
| Individual formats and live OPDS catalog | Not separately reported | No per-format results or catalog URL supplied |
| Piper with an actual voice and audio device (optional) | Not separately reported | Runtime and models are separate |
| System screen reader (optional) | Not separately reported | No screen-reader result supplied |

Missing optional hardware or tools is **Not tested**. Do not convert unperformed
checks into a pass. Resolve reproducible blocking failures before publication;
retain the actual remaining limitations in the release notes.

## Publish the checked revision

Complete the administrator setup and verification in
[release publication controls](RELEASE_SECURITY.md). The publisher requires
protected main, the `github-release` environment, the current main head, and a
new tag. Publication refuses an existing tag.

1. Confirm the candidate files match the source commit and checksums.
2. Record the manual results and ensure the exact final commit's checks are green.
3. Run **Check and build** from protected **main** with **Publish the checked build**
   enabled and **release_channel = release**. The default channel remains
   `prerelease` for development builds.
4. Verify the release contains the DEB, both matching source archives and
   `SHA256SUMS`, is not marked prerelease, and is the latest release.
5. Keep the README download link aligned with the published asset.
6. When preparing the next package revision, review the checksum-pinned upgrade
   baseline in both Debian and Ubuntu jobs and update it to the relevant published
   version. Keep a real older-to-newer version comparison and verify seeded data.

Do not overwrite files attached to an earlier release under the same name.
