# Daily GitHub metrics

This project runs a lightweight, Python-standard-library-only collector using
[GitHub Actions](https://github.com/gagafes/malferma-libro/actions/workflows/daily-github-metrics.yml).

- **Schedule:** 03:23 UTC every day. Manual runs are available in the Actions tab.
- **Archive:** [dashboard, charts, CSV and original JSON](https://github.com/gagafes/malferma-libro/tree/metrics-history/metrics) on the separate `metrics-history` branch.
- **Downloads:** cumulative GitHub release asset download counters (with observed daily increases after the first snapshot).
- **Traffic:** GitHub repository page views and clones, archived from the rolling 14-day Traffic API.

## Required one-time setup for traffic

The regular `GITHUB_TOKEN` is sufficient for downloading release counters and writing the archive,
but **not** for GitHub's Traffic API. Create a [fine-grained personal access token](https://github.com/settings/personal-access-tokens/new) scoped to
`gagafes/malferma-libro` with **Repository permissions → Administration → Read-only**.
Then open [Actions secrets](https://github.com/gagafes/malferma-libro/settings/secrets/actions), create a repository secret named **`TRAFFIC_READ_TOKEN`**, and paste the token there.

Do **not** paste the token into chats, issues, code or README files. Rotate it before it expires. Until
this secret is configured the workflow saves downloads but explicitly reports Traffic as unavailable.
An invalid/expired configured token causes the workflow to fail visibly.

## Notes

The first asset counter reading is a baseline; historical daily downloads cannot be reconstructed.
Monthly event totals must not be interpreted as monthly unique users.
Scheduled GitHub Actions on inactive public repositories may be disabled after 60 days.
GitHub may delay or skip scheduled runs. The dashboard and archive are public because
the repository itself is public. They contain aggregate counts, not individual visitor identities.
