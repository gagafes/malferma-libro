<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Release readiness: Debian 0.1.1-3

Application version: **0.1.1**. Debian package revision: **0.1.1-3**.
[Version 0.1.1-3](https://github.com/gagafes/malferma-libro/releases/tag/v0.1.1-3)
was published on 2026-10-20 as an ordinary release and marked **Latest**.
The [publication workflow](https://github.com/gagafes/malferma-libro/actions/runs/39457172853)
passed for final source commit `0a2f49ef704a4043f28d389e52bd81cdc09a55bd`.
The release contains the DEB, matching ZIP and TAR.GZ source archives, and
`SHA256SUMS`; the published checksums match GitHub's asset digests.
Version 1.0 remains reserved for the owner's production milestone.

Published DEB: **2,446,352 bytes**. SHA-256:
`fff7a03912353b2f3313061181af7db780f2ea746a29480d9ba119143179241f`.

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

Candidate commit: `d389e4b0ba1bfc3fc650e69eeb3f714ff55ffde0`.
[Candidate workflow 39455884597](https://github.com/gagafes/malferma-libro/actions/runs/39455884597)
passed on 2026-10-20: 257 source-suite entries (two native test classes skipped
there and exercised separately), 48 translation catalogs, 18 native UI tests
and eight illustration tests at 200% scale on both Ubuntu 24.04 and Debian 13.
The Debian job also passed fresh installation and upgrade from 0.1.1-2 with
the seeded library preserved.

## Manual desktop result

On 2026-10-20, after being asked to test the candidate linked above, the owner
reported **XFCE 4.20; no problems found**. This is an owner-reported result.
The OS version, X11/Wayland session, interface language, display scale, candidate
checksum and individual checklist outcomes were not supplied.
The reusable detailed procedure remains in [TESTING.md](TESTING.md).

| Check | Result | Evidence |
| --- | --- | --- |
| XFCE 4.20 desktop use | No issues reported by owner | Owner's report on 2026-10-20 |
| Individual formats and live OPDS catalog | Not separately reported | No per-format results or catalog URL supplied |
| Piper with an actual voice and audio device (optional) | Not verified | Runtime and models are separate; no audio result supplied |
| System screen reader (optional) | Not verified | No screen-reader result supplied |

Final preparation only updated documentation relative to the tested candidate;
application code and runtime assets are unchanged. Documentation is included in
the DEB, so the final package was rebuilt and received a new checksum. The release
workflow tested that final package again before publication.

Missing optional hardware or tools is **Not tested**. Do not convert unperformed
checks into a pass. Resolve reproducible blocking failures before publication;
retain the actual remaining limitations in the release notes.

## Publish the checked revision

For unreleased source, first complete the administrator setup and verification
in [release publication controls](RELEASE_SECURITY.md). The updated publisher
requires protected main, the `github-release` environment, the current main
head, and a new tag. Increase the package revision before the next release;
the published `0.1.1-3` tag and assets must remain unchanged.

1. Confirm that the candidate files match the source commit and checksums.
2. Record the manual results and ensure the final commit's workflow is green.
3. Run **Check and build** from protected **main** on that commit with **Publish the checked build**
   enabled and **release_channel = release**. The default channel remains
   `prerelease` for development builds.
4. Verify the release contains the DEB, both matching source archives and
   `SHA256SUMS`, is not marked prerelease, and is the latest release.
5. Update the README download link to that published asset and its actual size.

The workflow creates a new tag and release and refuses to replace an existing
one. Do not overwrite files attached to an earlier release under the same name.
