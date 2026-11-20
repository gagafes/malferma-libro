"""Check that a metrics run publishes a consistent snapshot.

SPDX-License-Identifier: GPL-3.0-or-later
"""
import base64
import json
import os
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch


COLLECTOR = Path(__file__).resolve().parents[1] / "tools/collect_github_metrics.py"


class GitHubMetricsTests(unittest.TestCase):
    def test_scheduled_run_commits_complete_snapshot_against_the_read_head(self):
        repo = "example/reader"
        ref = f"/repos/{repo}/git/ref/heads/metrics-history"
        previous = {
            "schema": 1, "repository": repo, "downloads": {"2026-10-01": {}},
            "traffic": {"views": {}, "clones": {}},
        }
        history_path = f"/repos/{repo}/contents/metrics/history.json?ref=old-head"
        responses = {
            ("GET", ref): {"object": {"sha": "old-head"}},
            ("GET", history_path): {
                "content": base64.b64encode(json.dumps(previous).encode()).decode(),
            },
            ("GET", f"/repos/{repo}/git/commits/old-head"): {"tree": {"sha": "old-tree"}},
            ("POST", f"/repos/{repo}/git/trees"): {"sha": "new-tree"},
            ("POST", f"/repos/{repo}/git/commits"): {"sha": "new-head"},
            ("PATCH", f"/repos/{repo}/git/refs/heads/metrics-history"): {},
        }
        writes = []

        def request(method, path, token, data=None):
            if method != "GET":
                writes.append((method, path, data))
            return responses[(method, path)]

        main = runpy.run_path(str(COLLECTOR))["main"]
        with patch.dict(main.__globals__, request=request), patch.dict(os.environ, {
            "GITHUB_REPOSITORY": repo, "GITHUB_TOKEN": "stub", "GITHUB_SHA": "main-head",
            "GITHUB_EVENT_NAME": "schedule", "TRAFFIC_READ_TOKEN": "",
        }, clear=True), patch("builtins.print"):
            self.assertEqual(main(), 0)

        self.assertEqual([method for method, _, _ in writes], ["POST", "POST", "PATCH"])
        tree, commit, update = [data for _, _, data in writes]
        self.assertEqual(tree["base_tree"], "old-tree")
        files = {entry["path"]: entry["content"] for entry in tree["tree"]}
        self.assertEqual(set(files), {
            "metrics/history.json", "metrics/daily.csv", "metrics/README.md",
            "metrics/monthly-views.svg", "metrics/monthly-clones.svg", "metrics/monthly-downloads.svg",
        })
        self.assertEqual(json.loads(files["metrics/history.json"])["downloads"], previous["downloads"])
        self.assertEqual(commit["tree"], "new-tree")
        self.assertEqual(commit["parents"], ["old-head"])
        self.assertEqual(update, {"sha": "new-head", "force": False})
