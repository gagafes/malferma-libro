<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Release publication controls

These controls describe the current source workflow, including the Ubuntu
publication gate added on 27 October 2026. Existing release tags and assets
retain their original contents and historical workflows.

## Source controls

- `publish` runs only for an explicitly requested manual run on protected
  `refs/heads/main`, after Linux, Debian and both Ubuntu fresh/upgrade jobs succeed.
- Ubuntu jobs validate the candidate DEB and SHA256SUMS from the same workflow
  run, including data preservation across the checksum-pinned 0.1.1-3 baseline.
  Their job dependency blocks publication on failure or a skipped required job.
- The job references the `github-release` environment and serializes publication
  attempts. This YAML reference alone does **not** configure environment rules.
- Immediately before publication, `packaging/release_guard.py` checks the local
  checkout against `GITHUB_SHA`, reads current main protection and its head SHA
  from GitHub, and refuses a stale run or an existing release tag. A failed or
  malformed API read stops publication. The guard performs only read operations.
- The existing `gh release create` command does not update an existing release.
  Use a new package revision for each release; this update uses `0.1.1-4`.
  Do not reuse `0.1.1-3`.

These checks are defense in depth for the checked workflow. They are not an
authorization boundary against a repository writer who can replace workflows
or publish releases directly. Old tags retain their original workflow files;
changing a file on main does not retroactively secure historical refs or cancel
already running jobs. Never rewrite release history to update old workflows.

## Repository administrator setup

The connected managed GitHub App does not have administration access. Source
changes cannot enable or verify all of the following settings on its behalf.

1. In [branch settings](https://github.com/gagafes/malferma-libro/settings/branches),
   protect `main`: require successful `linux` and `Install and upgrade on Debian 13`
   status checks, require the branch to be up to date, and disallow force pushes
   and branch deletion. Configure pull-request/review requirements for the actual
   maintainer team; this document does not assume an independent reviewer exists.
2. In [environment settings](https://github.com/gagafes/malferma-libro/settings/environments),
   create/configure `github-release`. Set deployment branches and tags to
   **Selected branches and tags**, add exactly the **branch** `main`, and add no
   tag rules. Do not use **Protected branches only** as a substitute: GitHub
   allows all branches through that option when no branch protection exists.
3. Retire publication in obsolete active branches. Review outstanding manual
   runs and cancel any obsolete publication attempt before enabling releases.
   Do not merge an obsolete documentation branch merely to remove its publisher.
4. Keep release-capable repository access limited to trusted maintainers and
   protect changes to workflows. If publication must resist repository writers,
   it needs an independently enforced credential/authorization policy; an `if`
   condition, environment reference, or read-only default token setting alone
   does not provide that guarantee.

Until main is protected, the updated workflow skips `publish` even when the
manual publish input is selected. Ordinary source/build/installation checks
continue to run. An environment is not considered configured just because its
name appears in YAML or in a successful CI run where `publish` was skipped.

## Repository controls verified on 26 October 2026

Main requires a pull request, an up-to-date branch, and the GitHub Actions
checks `linux` and `Install and upgrade on Debian 13`. Administrator bypass,
force pushes and deletion are disabled. No independent review approval is
required. The `github-release` environment permits exactly the main branch
and zero tags, with administrator bypass disabled. These settings were
verified separately from the source workflow. The Ubuntu publication gate is
an additional source-workflow dependency; the branch-protection snapshot above
records the checks configured on 26 October.

## Verification before the next release

Confirm the exact main commit's required checks are green, GitHub reports main
as protected, and `github-release` has only the main branch deployment rule.
Confirm a manual run from an ordinary branch or a tag cannot enter `publish`.
The read-only release guard must refuse an old main SHA, an existing tag, or
unavailable GitHub metadata. Do not test these cases by publishing a dummy release.

Local regression commands:

```sh
PYTHONPATH=src:tests python3 -W error::ResourceWarning -B -m unittest test_network test_jpeg_security test_release_guard
make check
make release
```
