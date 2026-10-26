#!/usr/bin/python3
"""Read-only release preflight; publication itself remains in the workflow.

SPDX-License-Identifier: GPL-3.0-or-later
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys


class ReleaseRefused(ValueError):
    """The selected checkout cannot be published as a new release."""


def _output(command):
    # No shell, token arguments or error-response dumps in workflow logs.
    return subprocess.run(command, check=True, capture_output=True, text=True,
                          timeout=30).stdout.strip()


def check_publication(version, *, environ=None):
    environment = os.environ if environ is None else environ
    if (environment.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
            or environment.get("GITHUB_REF") != "refs/heads/main"
            or environment.get("GITHUB_REF_PROTECTED") != "true"):
        raise ReleaseRefused("Publication requires a manual run on protected main")
    repository = environment.get("GITHUB_REPOSITORY", "")
    commit = environment.get("GITHUB_SHA", "")
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", repository)
            or not re.fullmatch(r"[0-9a-f]{40}", commit)
            or not isinstance(version, str)
            or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[1-9][0-9]*)?", version)):
        raise ReleaseRefused("Invalid release identity")
    if _output(["git", "rev-parse", "HEAD"]) != commit:
        raise ReleaseRefused("Checkout differs from the checked workflow commit")
    branch = json.loads(_output(["gh", "api", f"repos/{repository}/branches/main"]))
    if branch["protected"] is not True or branch["commit"]["sha"] != commit:
        raise ReleaseRefused("Main protection or its checked commit has changed; start a new run")
    tag = f"refs/tags/v{version}"
    references = json.loads(_output([
        "gh", "api", f"repos/{repository}/git/matching-refs/tags/v{version}",
    ]))
    if not isinstance(references, list):
        raise ReleaseRefused("Unexpected tag lookup response")
    for reference in references:
        if not isinstance(reference, dict) or not isinstance(reference.get("ref"), str):
            raise ReleaseRefused("Unexpected tag lookup response")
        if reference["ref"] == tag:
            # --target does not retarget an existing tag. Never attach new
            # artifacts to an older source commit, even if its release is gone.
            raise ReleaseRefused("Release tag already exists; increase the package version")


def main():
    from build import package_version

    try:
        check_publication(package_version())
    except (ReleaseRefused, OSError, subprocess.SubprocessError, ValueError,
            KeyError, TypeError) as error:
        message = str(error) if isinstance(error, ReleaseRefused) else "Release preflight could not be verified"
        print(message, file=sys.stderr)
        return 1
    print("Release preflight passed for the current protected main commit and a new tag")
    return 0


if __name__ == "__main__":
    sys.exit(main())
