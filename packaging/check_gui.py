#!/usr/bin/python3
"""Run real native UI checks; a missing GTK runtime/display is an error here.

The ordinary offline suite may skip GUI tests. This dedicated command makes
CI fail when its graphical test environment is misconfigured instead of
silently reporting a green build that exercised no widgets.
Each testcase runs in a fresh process so native application state cannot leak
between reader windows. --pattern selects a subset, including HiDPI checks.

SPDX-License-Identifier: GPL-3.0-or-later
"""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import unittest


def _run_case(case: str) -> int:
    suite = unittest.defaultTestLoader.loadTestsFromName(case)
    if suite.countTestCases() != 1:
        print(f"Expected exactly one native UI test: {case}", file=sys.stderr)
        return 1
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.testsRun != 1 or result.skipped:
        print("Native UI validation requires GTK/libadwaita and a working display; "
              "skipped checks do not count as a pass.", file=sys.stderr)
        return 1
    return 0 if result.wasSuccessful() else 1


def _test_ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _test_ids(item)
        else:
            yield item.id()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pattern", default="test_gui*.py", help="Test file discovery pattern")
    parser.add_argument("--case", help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    os.environ["RUN_GUI_TESTS"] = "1"
    tests = Path(__file__).resolve().parents[1] / "tests"
    sys.path.insert(0, str(tests))
    if arguments.case:
        return _run_case(arguments.case)

    suite = unittest.defaultTestLoader.discover(str(tests), pattern=arguments.pattern)
    cases = list(_test_ids(suite))
    if not cases:
        print("Native UI validation discovered no tests.", file=sys.stderr)
        return 1
    failures = 0
    for case in cases:
        # Every real reader instance gets a fresh native runtime, matching the
        # application's single-window lifecycle. GTK state from one testcase
        # must not outlive its interpreter and affect later widget assertions.
        print(f"\nNative UI check: {case}", flush=True)
        try:
            result = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()),
                                     "--case", case], timeout=120, check=False)
            failures += result.returncode != 0
        except subprocess.TimeoutExpired:
            print(f"Native UI check timed out: {case}", file=sys.stderr)
            failures += 1
    print(f"\nNative UI checks: {len(cases) - failures}/{len(cases)} passed.", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
