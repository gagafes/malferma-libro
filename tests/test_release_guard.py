"""Publication preflight rejects untrusted, stale and already tagged inputs.

SPDX-License-Identifier: GPL-3.0-or-later
"""

import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


path = Path(__file__).resolve().parents[1] / "packaging/release_guard.py"
spec = importlib.util.spec_from_file_location("release_guard", path)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
SHA = "a" * 40
ENVIRONMENT = {
    "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main",
    "GITHUB_REF_PROTECTED": "true", "GITHUB_REPOSITORY": "gagafes/malferma-libro",
    "GITHUB_SHA": SHA,
}


class ReleaseGuardTests(unittest.TestCase):
    def responses(self, *, head=SHA, remote=SHA, protected=True, references=None):
        return [head, json.dumps({"protected": protected, "commit": {"sha": remote}}),
                json.dumps([] if references is None else references)]

    def test_only_manual_protected_main_is_eligible_without_starting_commands(self):
        for change in ({"GITHUB_EVENT_NAME": "pull_request"}, {"GITHUB_EVENT_NAME": "push"},
                       {"GITHUB_REF": "refs/heads/docs/0.1.1-3-release-consistency"},
                       {"GITHUB_REF": "refs/tags/main"}, {"GITHUB_REF_PROTECTED": "false"},
                       {"GITHUB_REF_PROTECTED": ""}):
            with self.subTest(change=change), patch.object(guard, "_output") as command:
                with self.assertRaises(guard.ReleaseRefused):
                    guard.check_publication("0.1.1-4", environ={**ENVIRONMENT, **change})
                command.assert_not_called()

    def test_invalid_identifiers_do_not_reach_git_or_github(self):
        for change, version in (({"GITHUB_REPOSITORY": "../other"}, "0.1.1-4"),
                                ({"GITHUB_SHA": "main"}, "0.1.1-4"),
                                ({}, "0.1.1-4/../../main"), ({}, None)):
            with self.subTest(change=change, version=version), patch.object(guard, "_output") as command:
                with self.assertRaises(guard.ReleaseRefused):
                    guard.check_publication(version, environ={**ENVIRONMENT, **change})
                command.assert_not_called()

    def test_wrong_checkout_moved_main_and_removed_protection_are_rejected(self):
        for replies in (self.responses(head="b" * 40), self.responses(remote="b" * 40),
                        self.responses(protected=False)):
            with self.subTest(replies=replies), patch.object(guard, "_output", side_effect=replies):
                with self.assertRaises(guard.ReleaseRefused):
                    guard.check_publication("0.1.1-4", environ=ENVIRONMENT)

    def test_existing_tag_is_rejected_even_without_a_release(self):
        with patch.object(guard, "_output", side_effect=self.responses(
                references=[{"ref": "refs/tags/v0.1.1-4"}])):
            with self.assertRaisesRegex(guard.ReleaseRefused, "already exists"):
                guard.check_publication("0.1.1-4", environ=ENVIRONMENT)

    def test_a_new_tag_allows_only_read_only_checks(self):
        for references in ([], [{"ref": "refs/tags/v0.1.1-40"}]):
            with self.subTest(references=references), patch.object(
                    guard, "_output", side_effect=self.responses(references=references)) as command:
                guard.check_publication("0.1.1-4", environ=ENVIRONMENT)
                self.assertEqual([call.args[0] for call in command.call_args_list], [
                    ["git", "rev-parse", "HEAD"],
                    ["gh", "api", "repos/gagafes/malferma-libro/branches/main"],
                    ["gh", "api", "repos/gagafes/malferma-libro/git/matching-refs/tags/v0.1.1-4"],
                ])

    def test_failed_or_malformed_github_reads_do_not_authorize_publication(self):
        for result in (subprocess.CalledProcessError(1, ["gh", "api"]),
                       "not JSON", json.dumps({"protected": True}),
                       json.dumps({"protected": "true", "commit": {"sha": SHA}})):
            with self.subTest(result=result), patch.object(guard, "_output", side_effect=[SHA, result]):
                with self.assertRaises((subprocess.SubprocessError, ValueError, KeyError, TypeError)):
                    guard.check_publication("0.1.1-4", environ=ENVIRONMENT)
        for references in ({}, [None], [{"ref": None}]):
            with self.subTest(references=references), patch.object(
                    guard, "_output", side_effect=self.responses(references=references)):
                with self.assertRaises(guard.ReleaseRefused):
                    guard.check_publication("0.1.1-4", environ=ENVIRONMENT)
