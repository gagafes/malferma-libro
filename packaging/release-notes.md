Malferma Libro Debian package **0.1.1-3** includes the reviewed German accessibility translations and the current documentation. The application version remains **0.1.1**. APT can upgrade the previously published **0.1.1-2** package to this revision.

- Clarify German narration, magnifier, speech-rate and keyboard labels, and synchronize the German manual.
- Add an English source-recovery note and a reusable manual desktop test checklist.
- Verify fresh installation and upgrade from 0.1.1-2 in Debian 13, including preservation of a seeded library, reading position, bookmarks, notes and settings.
- Exercise the installed GTK interface and illustrations at normal and 200% scale on Debian 13.
- Wait for the illustration viewer's actual viewport before fitting an image, avoiding an incorrect initial scale during window creation.
- Keep the existing GTK compatibility, compact library layout, security corrections and OpenAI Codex attribution.

The checks above are automated. The [validation record](https://github.com/gagafes/malferma-libro/blob/v0.1.1-3/VALIDATION.md) and [release checklist](https://github.com/gagafes/malferma-libro/blob/v0.1.1-3/docs/RELEASE_CHECKLIST.md) distinguish them from manual desktop, screen-reader and audio checks.

Assets include the DEB, corresponding complete source archives (ZIP and TAR.GZ), and `SHA256SUMS`. Earlier published assets remain unchanged. Code, translations and documentation are GPL-3.0-or-later; fonts and AppStream metadata retain their own license notices.

Piper and voice models are installed separately. OCR, DRM and the publisher's complete EPUB layout are not supported.
