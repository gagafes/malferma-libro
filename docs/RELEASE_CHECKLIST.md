<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Release readiness: Debian 0.1.1-3

Application version: **0.1.1**. Debian package revision: **0.1.1-3**.
This revision is being prepared for an ordinary GitHub release. Its release
status is pending the checks below; preparing these files does not publish it.
Version 1.0 remains reserved for the owner's production milestone.

## Automated checks

The **Check and build** workflow must pass for the exact source commit being
released. The publication job requires both the source/build job and the
Debian 13 installation job.

- Source tests, all translation catalogs, desktop metadata and native GTK tests.
- Native illustration checks at 200% scale.
- DEB, corresponding source archives and verified `SHA256SUMS`.
- Fresh APT installation on Debian 13, installed CLI/manuals/resources and runtime dependencies.
- Upgrade from the checksum-pinned published 0.1.1-2 DEB, preserving a seeded
  test library, book bytes, reading position, bookmarks, notes and settings.
- Native GTK tests against the installed package on Debian 13, also at 200% scale.

The installation test uses an isolated profile under an unprivileged test
account. Its automated library checks do not represent a user's personal
library or a manual session on physical hardware.

## Manual desktop result

Test the candidate DEB on Debian 13 using [TESTING.md](TESTING.md). Record the
candidate SHA-256, desktop, X11/Wayland session, language and screen scale.
At minimum, check installation or upgrade, reopening a book at the saved
position, contents, search, illustrations, text size, themes, keyboard,
fullscreen and the accessibility menu. Include each book format actually
tested and one available OPDS catalog. A catalog outage should be recorded
separately from an application failure.

| Check | Result | Evidence |
| --- | --- | --- |
| Ordinary Debian 13 desktop session | Not tested | Awaiting a desktop test report |
| Live OPDS catalog | Not tested | Awaiting a catalog test report |
| Piper with an actual voice and audio device (optional) | Not tested | Runtime and models are separate |
| System screen reader (optional) | Not tested | Record the actual desktop and screen reader if tested |

Missing optional hardware or tools is **Not tested**. Do not convert unperformed
checks into a pass. Resolve reproducible blocking failures before publication;
retain the actual remaining limitations in the release notes.

## Publish the checked revision

1. Confirm that the candidate files match the source commit and checksums.
2. Record the manual results and ensure the final commit's workflow is green.
3. Run **Check and build** on that commit with **Publish the checked build**
   enabled and **release_channel = release**. The default channel remains
   `prerelease` for development builds.
4. Verify the release contains the DEB, both matching source archives and
   `SHA256SUMS`, is not marked prerelease, and is the latest release.
5. Update the README download link to that published asset and its actual size.

The workflow creates a new tag and release and refuses to replace an existing
one. Do not overwrite files attached to an earlier release under the same name.
