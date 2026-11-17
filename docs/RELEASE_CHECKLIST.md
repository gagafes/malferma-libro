<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Release readiness: DEB 0.1.2-1

Application version: **0.1.2**. Candidate Debian package: **0.1.2-1**.
The upgrade baseline is the [published 0.1.1-4 DEB](https://github.com/gagafes/malferma-libro/releases/tag/v0.1.1-4).
Historical results are recorded in [VALIDATION.md](../VALIDATION.md).

## Automated checks

Run **Check and build** for the exact source commit being released.
Publication requires the source/build job, the Debian 13 installation and
upgrade job, and both Ubuntu 24.04 scenarios (fresh installation and upgrade).

- Check source tests, translation catalogs, desktop metadata and native GTK,
  including illustrations at 200% scale.
- Build the DEB and matching ZIP and TAR.GZ source archives and verify `SHA256SUMS`.
- Check fresh APT installation, installed files, launcher, manuals and dependencies.
- Upgrade from the checksum-pinned 0.1.1-4 DEB and verify book bytes, reading
  position, bookmarks, notes, settings and OPDS configuration in an isolated profile.

Review the **Python quality and security** workflow for the same commit.

## Manual desktop result

On 2026-11-17, the owner confirmed the manual desktop check and manual
installation of the 0.1.2 candidate. The tested checksum, OS and desktop
session, interface language, scale, and individual outcomes were not recorded.
The detailed procedure is in [TESTING.md](TESTING.md).

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
