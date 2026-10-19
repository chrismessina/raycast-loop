"""Store-level stats from data/store_listings.json + data/prs.csv.

Outputs: data/extensions_contributors.csv, data/downloads_longtail.json, data/flow_2026h1.json
"""
import csv, json, statistics as st
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data"
snap = json.loads((D / "store_listings.json").read_text())
L = snap["listings"]
R = list(csv.DictReader(open(D / "prs.csv")))
T = lambda r, k: r[k] == "True"

# ---- contributors per extension: declared in the Store, and distinct authors of merged PRs in the window
pr_authors, merged = defaultdict(set), Counter()
for r in R:
    if r["merged_at"]:
        for e in r["extensions"].split("|"):
            if e:
                pr_authors[e].add(r["author"].lower())
                merged[e] += 1
rows = []
for x in L:
    people = {h.lower() for h in [x["author"], x["owner"], *x["contributors"], *x["past_contributors"]] if h}
    rows.append({"folder": x["folder"], "title": x["title"], "downloads": x["downloads"],
                 "store_contributors": len(people), "pr_authors_2024_2026": len(pr_authors.get(x["folder"], ())),
                 "merged_prs_2024_2026": merged.get(x["folder"], 0), "store_url": x["store_url"]})
rows.sort(key=lambda r: (-r["store_contributors"], -r["downloads"]))
with open(D / "extensions_contributors.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

# ---- download long tail
dl = sorted((x["downloads"] for x in L), reverse=True)
total = sum(dl)
bands = [(0, 10, "0–9"), (10, 100, "10–99"), (100, 1000, "100–999"), (1000, 10000, "1k–10k"),
         (10000, 100000, "10k–100k"), (100000, 10**9, "100k+")]
band_rows = [{"band": lab, "extensions": sum(lo <= d < hi for d in dl),
              "downloads": sum(d for d in dl if lo <= d < hi)} for lo, hi, lab in bands]
cohort = defaultdict(list)
for x in L:
    cohort[datetime.fromtimestamp(x["created_at"]).year].append(x["downloads"])
longtail = {
    "fetched_at": snap["fetched_at"], "extensions": len(dl), "downloads": total, "median": st.median(dl),
    "top1pct_share": round(100 * sum(dl[:len(dl) // 100]) / total, 1),
    "top10pct_share": round(100 * sum(dl[:len(dl) // 10]) / total, 1),
    "bottom50pct_share": round(100 * sum(dl[len(dl) // 2:]) / total, 1),
    "bands": band_rows,
    "cohorts": [{"year": y, "extensions": len(v), "median": st.median(v)} for y, v in sorted(cohort.items())],
    "top": [{"title": x["title"], "folder": x["folder"], "downloads": x["downloads"]}
            for x in sorted(L, key=lambda x: -x["downloads"])[:15]],
}
(D / "downloads_longtail.json").write_text(json.dumps(longtail, indent=1))

# ---- the path of new-extension submissions opened in 2026-H1, for the flow diagram
S = [r for r in R if r["kind"] == "new" and T(r, "chain_final") and "2026-01" <= r["created_at"][:7] <= "2026-06"]
A = [r for r in S if T(r, "auto_closed")]
rev = [r for r in A if T(r, "chain_ever_ready") and T(r, "chain_any_human_reply")]
flow = {
    "submissions": len(S),
    "never_ready": sum(not T(r, "chain_ever_ready") for r in S),
    "ready": sum(T(r, "chain_ever_ready") for r in S),
    "merged": sum(bool(r["merged_at"]) for r in S),
    "auto_closed": len(A),
    "auto_never_ready": sum(not T(r, "chain_ever_ready") for r in A),
    "auto_ready_no_human": sum(T(r, "chain_ever_ready") and not T(r, "chain_any_human_reply") for r in A),
    "auto_reviewed": len(rev),
    "auto_reviewed_replied_then_stopped": sum(not T(r, "waiting_on_reviewer_at_close") and T(r, "author_responded_after_feedback") for r in rev),
    "auto_reviewed_never_replied": sum(not T(r, "waiting_on_reviewer_at_close") and not T(r, "author_responded_after_feedback") for r in rev),
    "auto_reviewed_waiting_on_reviewer": sum(T(r, "waiting_on_reviewer_at_close") for r in rev),
    "author_closed": sum(r["close_by"] == "author" for r in S),
    "rejected": sum(r["close_by"] in ("maintainer", "owner") for r in S),
    "open": sum(r["state"] == "OPEN" for r in S),
    "dup_flagged": sum(T(r, "chain_dup_phrase") for r in S),
    "greptile_reviewed": sum(T(r, "greptile") for r in S),
    "opened_draft": sum(T(r, "opened_as_draft") for r in S),
    "opened_ready": sum(not T(r, "opened_as_draft") for r in S),
    "never_ready_author_closed": sum(not T(r, "chain_ever_ready") and r["close_by"] == "author" for r in S),
    "ready_author_closed": sum(T(r, "chain_ever_ready") and r["close_by"] == "author" for r in S),
    "median_days_ready_to_human": st.median(float(r["days_ready_to_first_human"]) for r in S if r["days_ready_to_first_human"]),
}
# of the "answered earlier feedback, reviewer spoke last" group: how many last acted before any human replied
chains_ = defaultdict(list)
for r in R:
    if r["chain_id"]:
        chains_[r["chain_id"]].append(r)


def first_human_at(rs):
    ts = [datetime.fromisoformat(x["created_at"][:19]) + timedelta(days=float(x["days_to_first_human"]))
          for x in rs if x["days_to_first_human"] != ""]
    return min(ts) if ts else None


stopped = [r for r in rev if not T(r, "waiting_on_reviewer_at_close") and T(r, "author_responded_after_feedback")]
n_before = 0
for r in stopped:
    rs = chains_.get(r["chain_id"], [r])
    last = max((x["last_author_activity_at"] for x in rs if x["last_author_activity_at"]), default="")
    fh = first_human_at(rs)
    n_before += bool(fh and last and datetime.fromisoformat(last[:19]) < fh)
flow["replied_before_first_human"] = n_before
(D / "flow_2026h1.json").write_text(json.dumps(flow, indent=1))
print(json.dumps(flow, indent=1))
print({k: longtail[k] for k in ("extensions", "downloads", "median", "top1pct_share", "top10pct_share", "bottom50pct_share")})
print(rows[:8])
