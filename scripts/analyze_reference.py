"""Analyze raycast/extensions PRs (2024-01-01 .. 2026-10-18).

Inputs (same folder):
  prs.csv            one row per PR (from GitHub search API)
  sets.json          {"greptile": [pr numbers], "changes_requested": [...], "dup_phrase": [...]}
  folders.txt        current extension folder names in the monorepo
Outputs:
  quarterly.csv, summary.json
"""
import csv, json, re, statistics as st, sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

D = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
rows = list(csv.DictReader(open(D / "prs.csv")))
sets = {k: set(map(int, v)) for k, v in json.load(open(D / "sets.json")).items()}
folders = [l.strip() for l in open(D / "folders.txt") if l.strip()]

BOTS = re.compile(r"\[bot\]$|^raycastbot$|^dependabot", re.I)
CUTOFF = datetime(2026, 10, 18)


def dt(s):
    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S") if s else None


def q(d):
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


for r in rows:
    r["n"] = int(r["number"])
    r["c"] = dt(r["created_at"])
    r["cl"] = dt(r["closed_at"])
    r["m"] = dt(r["merged_at"])
    labs = set(filter(None, r["labels"].split("|")))
    r["new"] = "new extension" in labs
    r["fix"] = "extension fix / improvement" in labs
    r["kind"] = "new" if r["new"] else ("existing" if r["fix"] else "other")
    r["stale_closed"] = r["state"] == "closed" and not r["m"] and "status: stalled" in labs
    r["closed_unmerged"] = r["state"] == "closed" and not r["m"]
    r["greptile"] = r["n"] in sets.get("greptile", set())
    r["cr"] = r["n"] in sets.get("changes_requested", set())
    r["bot"] = bool(BOTS.search(r["login"] or ""))
    r["q"] = q(r["c"])
    r["first_timer"] = r["author_association"] in ("FIRST_TIME_CONTRIBUTOR", "FIRST_TIMER", "NONE")
    r["ext"] = [e for e in r["ext_labels"].split("|") if e]

rows = [r for r in rows if not r["bot"]]


def pct(a, b):
    return round(100 * a / b, 1) if b else None


def med_days(xs):
    return round(st.median(xs), 1) if xs else None


def p75(xs):
    return round(st.quantiles(xs, n=4)[2], 1) if len(xs) >= 4 else None


# ---- duplicate heuristic: new-extension PR whose service token matches an existing folder
def toks(name):
    name = name.split("/")[-1].lower()
    return [t for t in re.split(r"[^a-z0-9]+", name) if t]


GENERIC = {"raycast", "extension", "the", "my", "simple", "quick", "open", "search", "ai", "app", "tools", "tool",
           "manager", "helper", "for", "and", "to", "of", "get", "new", "better", "mac", "macos", "menu", "bar"}
lead = defaultdict(set)
for f in folders:
    t = [x for x in toks(f) if x not in GENERIC]
    if t:
        lead[t[0]].add(f)

# first time each extension folder shows up on a merged PR in our window
first_merged = {}
for r in sorted(rows, key=lambda r: r["c"]):
    if r["m"]:
        for e in r["ext"]:
            first_merged.setdefault(e.split("/")[-1], r["c"])


def dup_candidates(r):
    own = {e.split("/")[-1] for e in r["ext"]}
    title = re.sub(r"(?i)^\s*(add|new|feat:?|\[new\]|create)\s*", "", r["title"])
    title = re.sub(r"(?i)\bextension\b.*$", "", title)
    t = [x for x in toks(title.replace(" ", "-")) if x not in GENERIC] or \
        [x for o in own for x in toks(o) if x not in GENERIC]
    if not t:
        return []
    hits = [f for f in lead.get(t[0], ()) if f not in own]
    # keep only folders that plausibly existed before this PR (not first merged after it)
    return [f for f in hits if not (f in first_merged and first_merged[f] > r["c"])]


for r in rows:
    r["dup_heur"] = bool(r["new"] and dup_candidates(r))
    r["dup_phrase"] = r["n"] in sets.get("dup_phrase", set())

# ---- quarterly table
Q = defaultdict(list)
for r in rows:
    Q[r["q"]].append(r)

out = []
for qq in sorted(Q):
    R = Q[qq]
    rec = {"quarter": qq, "prs": len(R)}
    for k in ("new", "existing", "other"):
        K = [r for r in R if r["kind"] == k]
        rec[f"{k}_prs"] = len(K)
        rec[f"{k}_merged"] = sum(1 for r in K if r["m"])
        rec[f"{k}_auto_closed"] = sum(r["stale_closed"] for r in K)
        rec[f"{k}_closed_unmerged"] = sum(r["closed_unmerged"] for r in K)
        rec[f"{k}_merge_rate"] = pct(rec[f"{k}_merged"], len(K))
        rec[f"{k}_auto_close_rate"] = pct(rec[f"{k}_auto_closed"], len(K))
        ttm = [(r["m"] - r["c"]).total_seconds() / 86400 for r in K if r["m"]]
        rec[f"{k}_ttm_median_days"] = med_days(ttm)
        rec[f"{k}_ttm_p75_days"] = p75(ttm)
    rec["merged"] = sum(1 for r in R if r["m"])
    rec["auto_closed"] = sum(r["stale_closed"] for r in R)
    rec["open"] = sum(1 for r in R if r["state"] == "open")
    rec["greptile_pct"] = pct(sum(r["greptile"] for r in R), len(R))
    rec["changes_requested_pct"] = pct(sum(r["cr"] for r in R), len(R))
    rec["first_timer_pct"] = pct(sum(r["first_timer"] for r in R), len(R))
    fb = [r for r in R if r["greptile"] or r["cr"]]
    rec["feedback_prs"] = len(fb)
    rec["feedback_auto_closed_pct"] = pct(sum(r["stale_closed"] for r in fb), len(fb))
    rec["new_dup_heur_auto_closed"] = sum(1 for r in R if r["new"] and r["stale_closed"] and r["dup_heur"])
    rec["new_dup_phrase_closed"] = sum(1 for r in R if r["new"] and r["closed_unmerged"] and r["dup_phrase"])
    out.append(rec)

with open(D / "quarterly.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
    w.writeheader()
    w.writerows(out)

# ---- headline summary
S = {}
S["window"] = f"{min(r['c'] for r in rows):%Y-%m-%d} .. {max(r['c'] for r in rows):%Y-%m-%d}"
S["prs_human"] = len(rows)
S["auto_closed_total"] = sum(r["stale_closed"] for r in rows)
for k in ("new", "existing", "other"):
    S[f"auto_closed_{k}"] = sum(r["stale_closed"] for r in rows if r["kind"] == k)
    S[f"prs_{k}"] = sum(1 for r in rows if r["kind"] == k)
S["auto_closed_after_feedback"] = sum(1 for r in rows if r["stale_closed"] and (r["greptile"] or r["cr"]))
S["auto_closed_new_dup_heur"] = sum(1 for r in rows if r["new"] and r["stale_closed"] and r["dup_heur"])
S["closed_new_dup_phrase"] = sum(1 for r in rows if r["new"] and r["closed_unmerged"] and r["dup_phrase"])
S["closed_unmerged_new_total"] = sum(1 for r in rows if r["new"] and r["closed_unmerged"])
g = [r for r in rows if r["greptile"]]
S["greptile_first_pr_created"] = f"{min(r['c'] for r in g):%Y-%m-%d}" if g else None
json.dump(S, open(D / "summary.json", "w"), indent=2)

# examples of dup candidates for spot checks
ex = [(r["n"], r["title"], dup_candidates(r)[:3]) for r in rows if r["new"] and r["stale_closed"] and r["dup_heur"]]
json.dump(ex, open(D / "dup_examples.json", "w"), indent=1)
print(json.dumps(S, indent=2))
