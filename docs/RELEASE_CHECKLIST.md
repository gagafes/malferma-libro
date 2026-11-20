<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Release checklist

The current [release page] shows the published DEB, source archives and
checksums. See the [validation record](../VALIDATION.md) for dated results.

## Prepare the candidate

1. Assign an unpublished full package version and update
   [packaging/release-notes.md](../packaging/release-notes.md).
2. Review the checksum-pinned upgrade baseline in
   [check.yml](../.github/workflows/check.yml) for both distributions.
   The current baseline is the [published 0.1.1-4 DEB]. Check the version
   ordering and confirm that the seeded data survives the upgrade.
3. Run **Check and build** on the exact candidate commit. Confirm the source,
   translation and GTK checks, artifact checksums, the Debian 13 job, and both
   Ubuntu 24.04 fresh-install and upgrade jobs.
4. Review **Python quality and security** for that commit. Follow the
   [desktop checklist](TESTING.md) and record the build checksum,
   environment and observed results.

## Publish

1. Verify the [repository publication controls](RELEASE_SECURITY.md).
2. On protected `main`, run **Check and build** with **Publish the checked
   build** enabled. Set `release_channel` to `release` for a stable release
   or leave it set to `prerelease` for a development build.
3. Confirm the GitHub release has the intended channel and tag, plus the DEB,
   both source archives and `SHA256SUMS` from that workflow run. Stable
   releases should be marked Latest.
4. Update the README download link after the stable release is published.

[release page]: https://github.com/gagafes/malferma-libro/releases/latest
[published 0.1.1-4 DEB]: https://github.com/gagafes/malferma-libro/releases/tag/v0.1.1-4
