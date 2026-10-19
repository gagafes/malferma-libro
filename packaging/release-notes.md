Malferma Libro Debian package **0.1.1-1** includes the security corrections and AI development attribution added after the original 0.1.1 prerelease. The application version remains **0.1.1**; APT can upgrade the original package to this Debian revision. The original v0.1.1 release files remain unchanged.

- Bound archive directories, compression methods, EPUB HTML and cover lookup work.
- Validate imported/opened regular files to prevent FIFO and symlink replacement from blocking workers.
- Limit PDF/DjVu helper memory and output files; support cancellation in HTML/Markdown parsing and close rejected OPDS responses.
- Pin GitHub Actions to reviewed commit hashes and retain restricted release permissions.
- Include OpenAI Codex development attribution while preserving GPL/OFL/CC0 terms and existing copyright notices.

See [Security review](https://github.com/gagafes/malferma-libro/blob/v0.1.1-1/docs/SECURITY_REVIEW.md) and [Validation](https://github.com/gagafes/malferma-libro/blob/v0.1.1-1/VALIDATION.md) for checks and limitations. Review and regression tests do not establish the absence of vulnerabilities.

Assets include the DEB, matching complete source archives (ZIP and TAR.GZ), and `SHA256SUMS`. Application code, translations and documentation remain GPL-3.0-or-later; bundled fonts and AppStream metadata retain their own license notices.

This is a **development prerelease**, not the planned production 1.0 release. Piper and voice models are installed separately.
