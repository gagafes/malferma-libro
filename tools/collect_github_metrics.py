#!/usr/bin/env python3
"""Daily GitHub release and traffic history; standard library only."""
import base64
import csv
import html
import io
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

BRANCH = "metrics-history"
API = "https://api.github.com"


def request(method, path, token, data=None):
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + token,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "github-repository-metrics/1.0",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = Request(API + path, data=None if data is None else json.dumps(data).encode(),
                  headers=headers, method=method)
    try:
        with urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except HTTPError as e:
        message = e.read(1000).decode("utf-8", "replace")
        raise RuntimeError("GitHub API error %s on %s: %s" % (e.code, path, message)) from None


def optional_request(method, path, token):
    try:
        return request(method, path, token)
    except RuntimeError as e:
        if "GitHub API error 404 " in str(e):
            return None
        raise


def read_file(repo, path, token):
    encoded = quote(path, safe="/")
    result = optional_request("GET", "/repos/%s/contents/%s?ref=%s" % (repo, encoded, BRANCH), token)
    if result is None:
        return None, None
    return base64.b64decode(result["content"]).decode("utf-8"), result["sha"]


def write_file(repo, path, content, token):
    _, sha = read_file(repo, path, token)
    payload = {
        "message": "metrics: update " + path,
        "branch": BRANCH,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    }
    if sha:
        payload["sha"] = sha
    request("PUT", "/repos/%s/contents/%s" % (repo, quote(path, safe="/")), token, payload)


def ensure_branch(repo, base_sha, token):
    ref = "/repos/%s/git/ref/heads/%s" % (repo, BRANCH)
    if optional_request("GET", ref, token) is None:
        try:
            request("POST", "/repos/%s/git/refs" % repo, token,
                    {"ref": "refs/heads/" + BRANCH, "sha": base_sha})
        except RuntimeError as e:
            if "GitHub API error 422 " not in str(e):
                raise


def releases(repo, token):
    assets = {}
    page = 1
    while True:
        batch = request("GET", "/repos/%s/releases?per_page=100&page=%d" % (repo, page), token)
        for rel in batch:
            for asset in rel.get("assets", []):
                assets[str(asset["id"])] = {
                    "release": rel["tag_name"], "name": asset["name"],
                    "downloads": int(asset["download_count"]),
                }
        if len(batch) < 100:
            break
        page += 1
    return assets


def download_deltas(snapshots):
    seen, result = {}, {}
    first = min(snapshots) if snapshots else ""
    for day in sorted(snapshots):
        delta = 0
        for asset_id, record in snapshots[day].items():
            count = record["downloads"]
            if asset_id in seen:
                delta += max(0, count - seen[asset_id])
            seen[asset_id] = count
        result[day] = "" if day == first else delta
    return result


def daily_rows(history):
    snapshots = history["downloads"]
    traffic = history["traffic"]
    deltas = download_deltas(snapshots)
    dates = sorted(set(snapshots) | set(traffic["views"]) | set(traffic["clones"]))
    rows = []
    for date in dates:
        v = traffic["views"].get(date, {})
        c = traffic["clones"].get(date, {})
        row = {
            "date": date,
            "views": v.get("count", ""),
            "unique_views_daily": v.get("uniques", ""),
            "clones": c.get("count", ""),
            "unique_clones_daily": c.get("uniques", ""),
            "observed_new_downloads": deltas.get(date, ""),
            "asset_downloads_total": sum(x["downloads"] for x in snapshots[date].values())
                                     if date in snapshots else "",
        }
        rows.append(row)
    return rows


FIELDS = ["date", "views", "unique_views_daily", "clones",
          "unique_clones_daily", "observed_new_downloads", "asset_downloads_total"]


def csv_report(rows):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def monthly(rows):
    values = defaultdict(lambda: {"views": 0, "clones": 0, "observed_new_downloads": 0})
    for row in rows:
        group = values[row["date"][:7]]
        for key in group:
            if row[key] != "":
                group[key] += int(row[key])
    return [{"month": month, **values[month]} for month in sorted(values)]


def svg_chart(data, key, title):
    values = data[-12:]
    maximum = max((d[key] for d in values), default=0)
    result = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 820 300" role="img">',
        '<rect width="820" height="300" fill="#fafafa"/>',
        '<text x="48" y="30" font-family="sans-serif" font-size="18" fill="#111827">%s</text>' % html.escape(title),
        '<line x1="48" y1="250" x2="800" y2="250" stroke="#9ca3af"/>',
    ]
    if maximum == 0:
        result.append('<text x="410" y="145" text-anchor="middle" font-family="sans-serif" fill="#6b7280">No recorded data yet</text>')
    else:
        step = 750 / len(values)
        for i, data_point in enumerate(values):
            count = data_point[key]
            bar_height = 170 * count / maximum
            x = 48 + i * step + step * 0.2
            y = 250 - bar_height
            result.extend([
                '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#2563eb"/>' %
                (x, y, step * 0.6, bar_height),
                '<text x="%.1f" y="%.1f" text-anchor="middle" font-size="12" font-family="sans-serif">%s</text>' %
                (x + step * 0.3, max(55, y - 6), count),
                '<text x="%.1f" y="271" text-anchor="middle" font-size="12" font-family="sans-serif">%s</text>' %
                (x + step * 0.3, html.escape(data_point["month"])),
            ])
    return "\n".join(result + ["</svg>", ""])


def dashboard(history, rows):
    repo = history["repository"]
    monthly_data = monthly(rows)
    snapshots = history["downloads"]
    latest = snapshots[max(snapshots)] if snapshots else {}
    lines = [
        "# GitHub statistics — " + repo, "",
        "**Updated (UTC):** " + history["updated_at"] + "  ",
        "**Traffic API:** " + history["traffic_status"], "",
        "## Monthly graphs", "",
        "![Repository views](monthly-views.svg)", "",
        "![Repository clones](monthly-clones.svg)", "",
        "![Observed new downloads](monthly-downloads.svg)", "",
        "## Monthly totals", "",
        "| Month (UTC) | Views | Clones | Observed new downloads |",
        "|---|---:|---:|---:|",
    ]
    for d in reversed(monthly_data[-24:]):
        lines.append("| %s | %d | %d | %d |" %
                     (d["month"], d["views"], d["clones"], d["observed_new_downloads"]))
    lines.extend(["", "## Release assets: current download counters", "",
                  "| Release | Asset | Downloads |", "|---|---|---:|"])
    for asset in sorted(latest.values(), key=lambda a: (a["release"], a["name"]), reverse=True):
        lines.append("| %s | %s | %s |" %
                     (asset["release"].replace("|", "/"),
                      asset["name"].replace("|", "/"), asset["downloads"]))
    if not latest:
        lines.append("| — | No published assets | — |")
    lines.extend([
        "", "## Raw data and limitations", "",
        "- [Daily CSV](daily.csv) / [Complete JSON history](history.json).",
        "- GitHub supplies traffic for the rolling last 14 days. Daily snapshots here preserve earlier days.",
        "- Monthly view/clone event totals are sums of daily figures, NOT unique monthly users.",
        "- Download changes are measured between saved snapshots. The first observation",
        "  of each release asset is a baseline, not a historical daily count.",
        "- Missing snapshot dates cannot be reconstructed precisely. Deleted assets are absent from",
        "  current release download totals; auto-generated GitHub source archives are not included.",
        "- All dates use UTC. No personal access tokens are written into these files.", "",
    ])
    return "\n".join(lines)


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]
    traffic_token = os.environ.get("TRAFFIC_READ_TOKEN", "")
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    ensure_branch(repo, os.environ["GITHUB_SHA"], token)
    previous, _ = read_file(repo, "metrics/history.json", token)
    history = json.loads(previous) if previous else {
        "schema": 1, "repository": repo, "downloads": {},
        "traffic": {"views": {}, "clones": {}},
    }
    history["updated_at"] = now.isoformat(timespec="seconds")
    history["downloads"][day] = releases(repo, token)
    error = None
    if traffic_token:
        try:
            for kind in ("views", "clones"):
                data = request("GET", "/repos/%s/traffic/%s?per=day" % (repo, kind), traffic_token)
                for record in data.get(kind, []):
                    history["traffic"][kind][record["timestamp"][:10]] = {
                        "count": int(record["count"]), "uniques": int(record["uniques"]),
                    }
            history["traffic_status"] = "active"
            history["last_traffic_success_at"] = history["updated_at"]
        except Exception as exc:
            error = str(exc)
            history["traffic_status"] = "ERROR — see GitHub Actions log"
    else:
        history["traffic_status"] = "not configured (TRAFFIC_READ_TOKEN missing)"
    rows = daily_rows(history)
    report = monthly(rows)
    output = {
        "metrics/history.json": json.dumps(history, sort_keys=True, indent=2) + "\n",
        "metrics/daily.csv": csv_report(rows),
        "metrics/README.md": dashboard(history, rows),
        "metrics/monthly-views.svg": svg_chart(report, "views", "Repository views by month"),
        "metrics/monthly-clones.svg": svg_chart(report, "clones", "Repository clones by month"),
        "metrics/monthly-downloads.svg": svg_chart(report, "observed_new_downloads",
                                                   "Observed new release downloads by month"),
    }
    for path, content in output.items():
        write_file(repo, path, content, token)
    print("Dashboard: https://github.com/%s/blob/%s/metrics/README.md" % (repo, BRANCH))
    if not traffic_token:
        print("::warning::Traffic metrics require TRAFFIC_READ_TOKEN repository secret")
    if error:
        print("::error::Traffic API request failed: " + error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
