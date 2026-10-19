"""Collect raycast/extensions PRs via GraphQL, cached per PR in data/raw/.

Usage: python3 scripts/collect.py 2025-01-01 2025-03-31
  1. Lists PR numbers created in the window (weekly search slices, each < 1000 results).
  2. Fetches full detail for each uncached PR in aliased batches.
Re-runs are incremental: listed windows and fetched PRs are skipped. Open PRs are
re-fetched when their cache is older than a day, since their state can still change.
"""
import json, re, subprocess, sys, time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
(RAW / "search").mkdir(parents=True, exist_ok=True)
(RAW / "pr").mkdir(parents=True, exist_ok=True)
BATCH = 8

PR_FIELDS = """
number title url createdAt closedAt mergedAt state isDraft authorAssociation
author { login }
additions deletions changedFiles
labels(first: 30) { nodes { name } }
files(first: 100) { totalCount nodes { path changeType } }
timelineItems(first: 250, itemTypes: [CLOSED_EVENT, REOPENED_EVENT, MERGED_EVENT, LABELED_EVENT,
    UNLABELED_EVENT, REVIEW_REQUESTED_EVENT, PULL_REQUEST_COMMIT, HEAD_REF_FORCE_PUSHED_EVENT,
    READY_FOR_REVIEW_EVENT, CONVERT_TO_DRAFT_EVENT]) {
  totalCount
  nodes {
    __typename
    ... on ClosedEvent { createdAt actor { login } }
    ... on ReopenedEvent { createdAt actor { login } }
    ... on MergedEvent { createdAt actor { login } }
    ... on LabeledEvent { createdAt label { name } actor { login } }
    ... on UnlabeledEvent { createdAt label { name } actor { login } }
    ... on ReviewRequestedEvent { createdAt requestedReviewer { ... on User { login } ... on Bot { login } } }
    ... on PullRequestCommit { commit { committedDate authoredDate author { user { login } } } }
    ... on HeadRefForcePushedEvent { createdAt actor { login } }
    ... on ReadyForReviewEvent { createdAt }
    ... on ConvertToDraftEvent { createdAt }
  }
}
reviews(first: 50) {
  totalCount
  nodes {
    author { login } authorAssociation state submittedAt body
    comments(first: 30) { totalCount nodes { path body createdAt } }
  }
}
comments(first: 100) { totalCount nodes { author { login } authorAssociation createdAt body } }
"""


class Timeout(Exception):
    """GitHub kept returning 502/504: the query is too heavy, not the network."""


def gql(query, variables=None, attempts=8):
    args = ["gh", "api", "graphql", "-f", f"query={query}"]
    for k, v in (variables or {}).items():
        args += ["-F" if isinstance(v, int) else "-f", f"{k}={v}"]
    attempt = -1
    while attempt + 1 < attempts:
        attempt += 1
        p = subprocess.run(args, capture_output=True, text=True)
        out = p.stdout or "{}"
        try:
            d = json.loads(out)
        except json.JSONDecodeError:
            d = {}
        errs = d.get("errors") or []
        limited = any(e.get("type") == "RATE_LIMITED" for e in errs) or "rate limit" in p.stderr.lower()
        if p.returncode == 0 and not errs:
            return d["data"]
        if limited:
            wait = rate_reset_wait()
            print(f"  rate limited; sleeping {wait}s", flush=True)
            time.sleep(wait)
            attempt -= 1  # waiting out a rate limit isn't a failed attempt
            continue
        if d.get("data") and errs and all(e.get("type") == "NOT_FOUND" for e in errs):
            return d["data"]
        wait = 5 * 2 ** attempt
        print(f"  error ({p.stderr.strip()[:200] or errs[:1]}); retry in {wait}s", flush=True)
        time.sleep(wait)
    if re.search(r"HTTP 50[24]|timeout", p.stderr, re.I):
        raise Timeout(p.stderr.strip()[:200])
    raise RuntimeError("GraphQL request failed repeatedly")


def rate_reset_wait():
    p = subprocess.run(["gh", "api", "rate_limit", "--jq", ".resources.graphql | \"\\(.remaining) \\(.reset)\""],
                       capture_output=True, text=True)
    try:
        remaining, reset = map(int, p.stdout.split())
    except ValueError:
        return 300
    if remaining > 200:  # a secondary (concurrency) limit, not the hourly quota: back off briefly
        return 60
    return max(30, reset - int(time.time()) + 5)


def list_window(start: date, end: date):
    """PR numbers created in [start, end] inclusive, all authors."""
    path = RAW / "search" / f"{start}_{end}.json"
    if path.exists() and end < date.today() - timedelta(days=1):
        return json.loads(path.read_text())
    q = f"repo:raycast/extensions is:pr created:{start}..{end}"
    nums, cursor = [], None
    while True:
        after = f', after: "{cursor}"' if cursor else ""
        d = gql(f"""query($q: String!) {{ search(query: $q, type: ISSUE, first: 100{after}) {{
            issueCount pageInfo {{ hasNextPage endCursor }}
            nodes {{ ... on PullRequest {{ number }} }} }} }}""", {"q": q})
        s = d["search"]
        if s["issueCount"] >= 1000:
            raise RuntimeError(f"window {start}..{end} has {s['issueCount']} results; shrink it")
        nums += [n["number"] for n in s["nodes"] if n]
        if not s["pageInfo"]["hasNextPage"]:
            break
        cursor = s["pageInfo"]["endCursor"]
    nums = sorted(set(nums))
    path.write_text(json.dumps(nums))
    return nums


def needs_fetch(n):
    path = RAW / "pr" / f"{n}.json"
    if not path.exists():
        return True
    d = json.loads(path.read_text())
    if d.get("state") == "OPEN":
        age = time.time() - path.stat().st_mtime
        return age > 86400
    return False


# Lighter connection sizes for a single PR whose full query times out.
PR_FIELDS_LITE = (PR_FIELDS.replace("timelineItems(first: 250", "timelineItems(first: 100")
                  .replace("comments(first: 30)", "comments(first: 5)").replace("comments(first: 100)", "comments(first: 60)"))


def fetch_chunk(chunk, fields=PR_FIELDS):
    body = "\n".join(f"p{n}: pullRequest(number: {n}) {{ {fields} }}" for n in chunk)
    try:
        d = gql(f'query {{ repository(owner: "raycast", name: "extensions") {{ {body} }} }}', attempts=3)
    except Timeout:
        if len(chunk) > 1:
            half = len(chunk) // 2
            print(f"  timeout on {len(chunk)} PRs; splitting", flush=True)
            fetch_chunk(chunk[:half], fields)
            fetch_chunk(chunk[half:], fields)
            return
        if fields is PR_FIELDS:
            print(f"  timeout on #{chunk[0]}; retrying with lighter fields", flush=True)
            fetch_chunk(chunk, PR_FIELDS_LITE)
            return
        print(f"  giving up on #{chunk[0]}", flush=True)
        return
    for n in chunk:
        pr = d["repository"].get(f"p{n}")
        if pr:
            pr["_lite"] = fields is not PR_FIELDS
            (RAW / "pr" / f"{n}.json").write_text(json.dumps(pr))


def fetch(nums):
    for i in range(0, len(nums), BATCH):
        fetch_chunk(nums[i:i + BATCH])
        print(f"  fetched {min(i + BATCH, len(nums))}/{len(nums)}", flush=True)


def main():
    start = date.fromisoformat(sys.argv[1])
    end = date.fromisoformat(sys.argv[2])
    nums = []
    d = start
    while d <= end:
        e = min(d + timedelta(days=6), end)
        got = list_window(d, e)
        print(f"{d}..{e}: {len(got)} PRs", flush=True)
        nums += got
        d = e + timedelta(days=1)
    todo = [n for n in sorted(set(nums)) if needs_fetch(n)]
    print(f"{len(nums)} PRs listed, {len(todo)} to fetch", flush=True)
    fetch(todo)
    stamp = {"collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "window": [str(start), str(end)], "prs": len(nums)}
    (RAW / f"collect_{start}_{end}.json").write_text(json.dumps(stamp, indent=1))
    print("done", stamp, flush=True)


if __name__ == "__main__":
    main()
