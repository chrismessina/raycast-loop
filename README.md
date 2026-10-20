# The Raycast Loop

How the Raycast Store PR queue changed from January 2024 to October 2026: volume, outcomes, review
latency, Greptile's role, duplicate submissions, and whether to publish the review rules.

**Data as of 2026-10-19.** 15,078 PRs opened 2024-01-01 → 2026-10-18.

- Report: https://chrismessina.github.io/raycast-loop/ (source: `docs/index.html`, prose in `site/narrative.json`)
- Pilot (2025-Q1, definition checks): `site/pilot.html`
- Raw GraphQL snapshot: [`raw.tar.zst`](https://github.com/chrismessina/raycast-loop/releases/download/data-2026-10-19/raw.tar.zst) (17 MB, release `data-2026-10-19`)

## Re-run

Re-collecting from scratch takes 1.5–2 hours and about 1,500 GraphQL points, and won't reproduce the
snapshot exactly: labels get removed and comments get edited after the fact. To work from the same
data as the report, extract the release asset first; `collect.py` then only fetches what's missing.

```bash
python3 scripts/collect.py 2024-01-01 2026-10-18   # incremental; cached PRs in data/raw/pr are skipped, open ones refreshed daily
python3 scripts/analyze.py --period month           # data/prs.csv, data/periods.csv, extensions + Greptile raw findings
python3 scripts/greptile_themes.py                  # data/greptile_findings.csv
python3 scripts/store_listings.py                   # data/store_listings.json: every Store listing, downloads, contributors
python3 scripts/store_stats.py                      # contributors, download long tail, 2026-H1 flow numbers
python3 scripts/report_page.py                      # docs/index.html (prose in site/narrative.json)
```

`scripts/pilot_page.py` built the pilot page from the pilot-era columns and no longer runs against
the current `prs.csv`; the published pilot page is a snapshot.

`collect.py` needs an authenticated `gh`. One full pass costs about 1,500 GraphQL points. Run one
process at a time, or a few at most: more than that trips GitHub's secondary rate limit.

Two inputs come from outside GitHub's API:
- `data/folders_added.tsv`: first-added date per extension folder, from `git log` on a full-history
  clone (the fork used was synced 2026-08-07; later folders come from merged PRs in the data).
- `data/extensions_meta.tsv`: current title and author per extension, from a sparse checkout of
  `extensions/*/package.json`.

## Files

| File | What it is |
|---|---|
| `data/prs.csv` | One row per human-authored PR with every derived flag |
| `data/monthly.csv`, `data/quarterly.csv` | Per-period tables |
| `data/greptile_findings.csv` | Greptile inline findings clustered into themes, with public-rubric coverage and Greptile rule numbers |
| `data/dup_handcheck.csv` | 30 hand-checked duplicate matches (14 same service) |
| `data/events.csv` | Raycast releases, coding-agent launches, and review-process changes used as chart markers |
| `data/raw/pr/*.json` | Raw GraphQL responses, one per PR. Not in git: download the release asset and run `tar --zstd -xf raw.tar.zst` in the repo root |

## Definitions

See the Method section of the report. In short: **auto-closed** means closed unmerged by
raycastbot with the `status: stalled` label or the inactivity message; new-extension PRs from one
author for one folder count as one **submission**, scored by the last PR; **feedback** comes from
Greptile, a Raycast maintainer, the extension owner (from raycastbot's 🔔 ping), or another
contributor requesting changes.

## Verification (2026-10-19)

- Monthly totals for 2024-01 → 2025-06 match the brief's reference counts exactly (18 of 18 months).
- GitHub's live search finds 2,030 closed-unmerged PRs with the stalled label in the window; the raw
  data has 2,030. 1,907 of those are auto-closed by the bot and 123 were closed by a person while
  stalled; 25 further auto-closes lost the label later (1,932 auto-closed in total).
- Four rounds of adversarial review by Codex (definitions vs. code, every published number vs. the
  CSVs, and every named actor vs. the raw PR records); all corrections are applied.
- Duplicate heuristic: 30 matches checked against both extensions' Store descriptions, 47% precision.
