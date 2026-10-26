# Security review

Review date: 19 October 2026. Scope: the source tree for Debian package
0.1.1-1, including application modules, packaging and GitHub Actions. The
application version remains 0.1.1. This package revision contains the fixes
below and matching complete sources, recorded under 0.1.1-1 in the changelog.
The existing v0.1.1 release assets are unchanged.

## Follow-up corrections — 26 October 2026 (unreleased)

These corrections follow the review of commit
`168fe69d6c8635ebbdb6985b53b7482f47de1353`. They are source changes for the
next release, not changes to the published 0.1.1-3 artifacts.

- OPDS URLs are limited to 8,192 characters both before parsing and after
  IRI encoding. Resolution checks inherited XML bases and has shared limits
  of 8,192 references and 2 MiB of resolved URL characters, counting duplicates
  and unused links. A page allows at most 2,048 entries and 128 links per
  entry or feed. Oversized pages fail explicitly; unsafe individual links
  are omitted. Cancellation is checked around XML parsing and during entry
  and link processing. Existing byte, XML node and depth limits remain.
- HTTP transfers run in a private helper process with streamed bounded
  output. The owning worker checks cancellation and an absolute deadline
  while waiting for DNS, connection, redirects, headers and body; it kills
  and reaps the helper on cancellation, timeout or early response close.
  Total budgets are 30 seconds for catalogs, 15 seconds for covers, five
  minutes for books and ten minutes per Piper file. Socket inactivity
  timeouts remain 20 seconds, or eight seconds for covers. URLs are passed
  through a private file rather than command-line arguments. HTTP(S)/LAN
  OPDS and the separate trusted HTTPS Piper redirect policy are preserved.
- A shared JPEG preflight walks the entire marker stream, including all
  scans, and removes every APP2 segment before native decoding. This removes
  optional ICC color profiles, including malformed/repeated profile chunks,
  from covers, inline illustrations and CBZ pages. Cached or hand-constructed
  cover data is revalidated at the decoder boundary. JPEGs without APP2 retain
  their bytes; removing a color profile may change color rendering. This
  mitigates the reviewed ICC input path; it does not patch or sandbox the
  system GdkPixbuf library. Supported, updated native packages remain required.
- The manual release job additionally requires protected `refs/heads/main`,
  references the `github-release` environment, serializes publication attempts,
  and still depends on the Linux and Debian checks. A read-only preflight
  rejects a different checkout, moved/unprotected main, failed metadata reads,
  or an existing tag. Repository/environment rules still require administrator
  configuration; these source checks do not secure historical workflow refs or
  constrain a trusted writer who replaces the workflow. See
  [release publication controls](RELEASE_SECURITY.md) for the exact boundary
  and administrator setup.

Regressions use loopback HTTP servers and bounded benign JPEG fixtures: slow
headers and trickle bodies, cancellation and process cleanup, early close,
byte caps, short responses, redirects, atomic downloads, URL amplification,
duplicate references, profiles around scan boundaries, and native pixel
equality after sanitization. Run `make check` and `make release`; CI also
exercises the installed Debian package and GTK at normal and 200% scale.
No hostile native decoder payload is needed for these regressions.

Additional regressions exercise a blocked `getaddrinfo` with both timeout and
cancellation, oversized header values/lines/counts, redirect chains and slow
redirect bodies, raw preexisting cover-cache data, and release preflight
rejection paths. These tests do not publish releases or change GitHub settings.

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
