#!/usr/bin/python3
"""Run real native UI checks; a missing GTK runtime/display is an error here.

The ordinary offline suite may skip GUI tests. This dedicated command makes
CI fail when its graphical test environment is misconfigured instead of
silently reporting a green build that exercised no widgets.

SPDX-License-Identifier: GPL-3.0-or-later
"""

import os
from pathlib import Path
import sys
import unittest


def main() -> int:
    os.environ["RUN_GUI_TESTS"] = "1"
    tests = Path(__file__).resolve().parents[1] / "tests"
    suite = unittest.defaultTestLoader.discover(str(tests), pattern="test_gui*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.testsRun or result.skipped:
        print("Native UI validation requires GTK/libadwaita and a working display; "
              "skipped checks do not count as a pass.", file=sys.stderr)
        return 1
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
