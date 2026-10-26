Malferma Libro Debian package **0.1.1-4** is a security update for **0.1.1-3** and earlier revisions. The application version remains **0.1.1**. Install the new DEB with APT to upgrade an existing installation.

- Bound OPDS URL length, cumulative URL resolution work, entries and links; honor cancellation during catalog processing.
- Enforce absolute network deadlines and cancellation across DNS, redirects, headers and body for OPDS and Piper downloads, with bounded responses and helper-process cleanup.
- Remove JPEG APP2/ICC profiles before caching and native cover, illustration and CBZ decoding, including cached and manually constructed cover data.
- Unify the application ID, desktop metadata and icons as `io.github.malferma_libro.Reader`.
- Restrict the checked release workflow to protected `main`, require Linux/Debian checks and the `github-release` environment, and refuse stale commits or an existing release tag.

**Data directory:** the application uses `$XDG_DATA_HOME/malferma-libro` (normally `~/.local/share/malferma-libro`). Directories named for the earlier project are no longer automatically detected. Existing user files are not moved or deleted.

The release workflow checks source tests and translations, native GTK at normal and 200% scale, fresh Debian 13 installation, and upgrade from the checksum-pinned published **0.1.1-3** package while preserving a seeded library, reading position, bookmarks, notes and settings. It verifies the DEB, matching complete ZIP/TAR.GZ sources and `SHA256SUMS` before publication.

On **26 October 2026**, the owner confirmed that the manual check of the new build had been performed. The tested build checksum and individual format, live OPDS, audio and screen-reader results were not separately supplied. Automated GTK tests use a virtual display.

See the [validation record](https://github.com/gagafes/malferma-libro/blob/v0.1.1-4/VALIDATION.md), [release checklist](https://github.com/gagafes/malferma-libro/blob/v0.1.1-4/docs/RELEASE_CHECKLIST.md) and [security review](https://github.com/gagafes/malferma-libro/blob/v0.1.1-4/docs/SECURITY_REVIEW.md) for scope and limits. JPEG preflight mitigates the reviewed ICC input path; supported, updated native system libraries are still required.

Assets include the DEB, corresponding complete source archives and `SHA256SUMS`. Earlier release tags and assets remain unchanged; use **0.1.1-4** for these fixes. Code, translations and documentation are GPL-3.0-or-later; fonts and AppStream metadata retain their own license notices.

Piper and voice models are installed separately. OCR, DRM and the publisher's complete EPUB layout are not supported.
