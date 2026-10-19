# Security review

Review date: 19 October 2026. Scope: the source tree for Debian package
0.1.1-1, including application modules, packaging and GitHub Actions. The
application version remains 0.1.1. This package revision contains the fixes
below and matching complete sources, recorded under 0.1.1-1 in the changelog.
The existing v0.1.1 release assets are unchanged.

## Reviewed boundaries

- EPUB, FB2, FB2.ZIP, TXT, HTML, Markdown, CBZ, PDF and DjVu input handling,
  archive paths, XML declarations, image decoding and resource budgets.
- OPDS requests, redirects, downloads, local import, library persistence,
  Piper model downloads, imported models and process execution.
- GTK text presentation, search, bookmarks, cancellation, background results,
  release inputs, license notices and CI permissions.

## Corrections

- EPUB/FB2 ZIP directory size and entry counts are validated on the same
  open file before Python constructs ZIP member objects. Only stored and
  deflated members are accepted, avoiding unbounded LZMA decoder allocation.
- EPUB HTML has a total element budget as well as a nesting limit. Cover
  references and inherited XML bases are bounded; repeated cover candidates
  have a shared attempt budget.
- Local import and direct archive/markup/FB2-cover reads validate the opened
  regular file. Nonblocking opens and final-symlink checks prevent a file
  replacement from blocking the worker on a named pipe.
- Standalone HTML and Markdown parsing now observes task cancellation.
- Rejected OPDS redirects and HTTP errors close their responses without
  consuming an untrusted response body.
- PDF/DjVu helper processes receive POSIX limits of 64 MiB per output file,
  2 GiB virtual address space and no core dumps. Existing timeouts and task
  cancellation remain. Limits are applied by a fresh isolated Python process,
  avoiding unsafe `preexec_fn` use in the multithreaded application.
- GitHub Actions use maintained Node.js 24 releases pinned to commit hashes.
  Checkout does not retain
  credentials; jobs have timeouts. Write permission remains confined to the
  explicitly requested release job.
- Debian's required MD5 payload inventory explicitly uses
  `usedforsecurity=False`. SHA256 remains the release integrity manifest.

## Verification

Regression tests exercise hostile archive directories, compression methods,
cover references, FIFO replacement, cancellation, HTTP response cleanup and
real child-process resource limits. Run `make check`, `make gui-test` and
`make release` to reproduce the relevant checks; GTK tests require a display.

Bandit 1.9.4 scanned all application and packaging Python files (14,082 lines),
with no scan errors: 33 low and two medium notices, no high notices. Its XML and
subprocess findings were reviewed against the declaration/size/depth checks
and shell-free argument lists; optional-resource fallbacks account for the
low-severity exception-handling notices. This is a reviewed finding set,
not a claim that the scanner reported zero findings. All current callers of
the shared XML parser reject entity declarations and dangerous DTDs before
parsing; regressions cover UTF-8/16/32 and comment/CDATA handling.

The PyPI advisory service queried through pip-audit reported no known
vulnerabilities for the tested runtime versions: markdown-it-py 3.0.0,
mdurl 0.1.2 and PyGObject 3.50.0. This is a version-specific result;
distribution packages and optional Piper dependencies are outside that query.
Tracked/current text files were checked for common private-key and API-token
patterns without printing candidate values; no matching patterns were found.

## Limits

Review and regression tests cannot establish the absence of vulnerabilities.
Native Poppler, DjVuLibre, GdkPixbuf, GTK, Python/Expat and optional Piper/ONNX
components require supported, updated system packages. Decoder resource
limits contain resource use; native processes still run with the user's
permissions. Imported voice models should come from trusted sources.

OPDS intentionally supports user-selected local and LAN HTTP(S) catalogs.
An untrusted feed can reference other HTTP(S) hosts; private-address blocking
is not imposed because local library servers are supported. Requests do not
carry stored authentication or cookies. This is a desktop client boundary;
embedding its network module in a privileged server needs a separate policy.

Physical desktop/accessibility/audio testing, fuzzing campaigns, a complete
native-dependency CVE assessment and independent legal certification were not
performed. AI assistance is acknowledged in README and the license audit;
existing GPL/OFL/CC0 terms and copyright notices are retained.
