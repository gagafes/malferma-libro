Malferma Libro **0.1.2-1** is a security and packaging update. The application version remains **0.1.2**.

- EPUB, CBZ metadata and OPDS XML parsing now uses `defusedxml` to reject entity declarations and external references while keeping the existing node and nesting limits. The DEB declares `python3-defusedxml` as a dependency.
- Release CI checks fresh installation and upgrade from the published, checksum-pinned **0.1.1-4** DEB on Debian 13 and Ubuntu 24.04. The upgrade scenarios verify book data, reading positions, bookmarks, notes, settings, and OPDS configuration.
- The repository adds Python quality and dependency checks and daily GitHub download and traffic reporting.

Install the DEB with `sudo apt install ./malferma-libro_0.1.2-1_all.deb`. Release assets include the DEB, matching ZIP and TAR.GZ source archives, and `SHA256SUMS`.

Library sorting avoids an extra list allocation. GitHub metrics requests reject HTTP redirects to keep credentials on the original endpoint.

PDF passwords exceeding 127 bytes are rejected before invoking Poppler as a mitigation for CVE-2026-107705. This includes multibyte passwords. System-library CVEs still require distribution fixes.
