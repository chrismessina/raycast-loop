"""Derive per-PR flags and per-period tables from data/raw/pr/*.json.

Usage: python3 scripts/analyze.py [--period month|quarter]
Outputs: data/prs.csv, data/periods.csv, data/extensions_activity.csv, data/greptile_findings_raw.csv
"""
import csv, json, re, statistics as st, sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA_DATE = datetime(2026, 10, 19)
PERIOD = sys.argv[sys.argv.index("--period") + 1] if "--period" in sys.argv else "month"

# GraphQL reports bot logins without the "[bot]" suffix.
BOTS = {"raycastbot", "greptile-apps", "github-actions", "dependabot", "cursor", "copilot-pull-request-reviewer",
        "renovate", "coderabbitai", "Copilot", "chatgpt-codex-connector", "vercel"}
GREPTILE = "greptile-apps"
MAINT_ASSOC = {"COLLABORATOR", "MEMBER", "OWNER"}
STALL_LABEL = "status: stalled"
INACTIVITY = re.compile(r"automatically closed due to inactivity", re.I)
G_SUMMARY = re.compile(r"PR Summary|Greptile Summary|file\(s\) reviewed|Confidence Score", re.I)
G_SCORE = re.compile(r"Confidence Score:?\s*(?:</?\w+>|\*)*\s*(\d)\s*/\s*5", re.I)
OWNER_PING = re.compile(r"🔔((?:\s*@[\w-]+)+)")
DUP_PHRASE = re.compile(
    r"already (an? )?(existing )?extension|extension (that )?already exists|already exists in the (raycast )?store|existing extension|extension already|"
    r"contribut\w* to (the )?(existing|current)|instead of (creating|adding) a new|"
    # store listings only: developers.raycast.com/basics/... docs links appear on nearly every PR
    r"(?<![\w.])(?:www\.)?raycast\.com/(?!basics|community|settings|ai\b|api-reference|extensions\b|information|"
    r"utils-reference|examples|teams|misc|store|blog|pro\b|changelog|faq|schemas)[\w-]+/[\w-]+|"
    r"github\.com/raycast/extensions/tree/main/extensions/[\w-]+", re.I)

# stale.yml thresholds over time (days-before-pr-stale, days-before-pr-close); from its git history
STALE_RULES = [("2023-01-01", 14, 7), ("2025-02-25", 21, 14), ("2025-03-26", 14, 7), ("2025-12-20", 15, 30),
               ("2026-01-15", 14, 7), ("2026-06-02", 25, 7)]


def dt(s):
    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S") if s else None


def period(d):
    return f"{d:%Y-%m}" if PERIOD == "month" else f"{d.year}-Q{(d.month - 1) // 3 + 1}"


def rule_at(d):
    r = STALE_RULES[0]
    for x in STALE_RULES:
        if d >= dt(x[0] + "T00:00:00"):
            r = x
    return f"{r[1]}+{r[2]}"


def login(x):
    return ((x or {}).get("author") or {}).get("login") or ""


# ---- extension catalog: first-added date per folder, plus current titles
folder_added = {}
for line in (DATA / "folders_added.tsv").read_text().splitlines():
    f, d = line.split("\t")
    folder_added[f] = dt(d)
titles = {}
for line in (DATA / "extensions_meta.tsv").read_text().splitlines():
    parts = line.split("\t")
    titles[parts[0]] = parts[1]

GENERIC = {"raycast", "extension", "extensions", "the", "my", "simple", "quick", "open", "search", "ai", "app",
           "apps", "tools", "tool", "manager", "helper", "for", "and", "to", "of", "get", "new", "better", "mac",
           "macos", "menu", "bar", "utils", "utility", "lite", "pro", "plus", "client", "control", "controller",
           "cli", "api", "x", "io", "hq", "go", "run", "kit", "hub", "box", "now", "it", "a", "in", "on", "by"}


def toks(name):
    return [t for t in re.split(r"[^a-z0-9]+", (name or "").lower()) if t and t not in GENERIC and len(t) > 1]


def names_of(folder):
    """Token sets naming an extension: its folder and its store title."""
    return [t for t in (toks(folder), toks(titles.get(folder, ""))) if t]


def build_df(catalog):
    df = Counter()
    for f in catalog:
        seen = set()
        for t in names_of(f):
            seen.add(t[0])
        df.update(seen)
    return df


RARE_MAX = 3  # a lead word naming more than this many extensions is a category word, not a service


def dup_candidates(folder, pr_title, created, df):
    """Existing extensions (added before `created`) that share a rare lead word with this one."""
    # PR titles are unreliable ("Update CHANGELOG.md"); use the folder and, once merged, its store title
    leads = {t[0] for t in names_of(folder)}
    leads = {w for w in leads if df.get(w, 0) <= RARE_MAX}
    out = []
    for f, added in folder_added.items():
        if f == folder or added is None or added >= created:
            continue
        if any(t[0] in leads for t in names_of(f)):
            out.append(f)
    return sorted(out)


def derive(p, df):
    author = (p.get("author") or {}).get("login") or ""
    created, closed, merged = dt(p["createdAt"]), dt(p["closedAt"]), dt(p["mergedAt"])
    end = closed or datetime.max
    labels = {l["name"] for l in p["labels"]["nodes"]}
    tl = [t for t in p["timelineItems"]["nodes"] if t]
    files = (p.get("files") or {}).get("nodes") or []
    reviews, comments = p["reviews"]["nodes"], p["comments"]["nodes"]

    added_pkgs = [f["path"].split("/")[1] for f in files
                  if f["changeType"] == "ADDED" and re.fullmatch(r"extensions/[^/]+/package\.json", f["path"])]
    touched = sorted({f["path"].split("/")[1] for f in files if f["path"].startswith("extensions/")
                      and f["path"].count("/") >= 2})
    ext_labels = sorted(l.split(": ", 1)[1] for l in labels if l.startswith("extension: "))
    # a package.json re-added to a folder already in the Store (renames, re-creations) is an update, not a submission
    if added_pkgs and folder_added.get(added_pkgs[0]) and folder_added[added_pkgs[0]] < created:
        added_pkgs = []
        labels = labels - {"new extension"}
    is_new = "new extension" in labels or bool(added_pkgs)
    kind = "new" if is_new else ("existing" if "extension fix / improvement" in labels or touched else "other")

    owners = set()
    for c in comments:
        if login(c) == "raycastbot":
            for m in OWNER_PING.finditer(c["body"] or ""):
                owners |= set(re.findall(r"@([\w-]+)", m.group(1)))
    owners.discard(author)

    closes = [t for t in tl if t["__typename"] == "ClosedEvent"]
    closer = ((closes[-1].get("actor") or {}).get("login") or "") if closes else ""
    stalled_at = [dt(t["createdAt"]) for t in tl if t["__typename"] == "LabeledEvent"
                  and (t.get("label") or {}).get("name") == STALL_LABEL]
    inactivity_msg = any(login(c) == "raycastbot" and INACTIVITY.search(c["body"] or "") for c in comments)
    closed_unmerged = p["state"] == "CLOSED"
    auto_closed = closed_unmerged and closer == "raycastbot" and (bool(stalled_at) or inactivity_msg)
    close_by = ("merged" if merged else "open" if p["state"] == "OPEN" else "stale-bot" if auto_closed
                else "author" if closer == author else "owner" if closer in owners
                else "maintainer" if closer else "unknown")

    # ---- feedback by source
    def src(x):
        a = login(x)
        if a == GREPTILE:
            return "greptile"
        if a in BOTS or a == author or not a:
            return None
        if a in owners:
            return "owner"
        if x.get("authorAssociation") in MAINT_ASSOC:
            return "maintainer"
        return "other"

    events = []  # (time, source, kind) for every review/comment by someone other than the author
    for r in reviews:
        s, t = src(r), dt(r["submittedAt"])
        if s and t and t <= end:
            events.append((t, s, r["state"], r))
    for c in comments:
        s, t = src(c), dt(c["createdAt"])
        if s and t <= end:
            events.append((t, s, "COMMENT", c))
    events.sort(key=lambda e: e[0])
    cutoff = merged - timedelta(minutes=1) if merged else datetime.max  # the merge comment isn't feedback
    fb = [e for e in events if e[2] != "APPROVED" and e[0] < cutoff and (e[1] != "other" or e[2] == "CHANGES_REQUESTED")]
    fb_sources = sorted({e[1] for e in fb})
    first_fb = fb[0][0] if fb else None
    last_fb = fb[-1] if fb else None
    human_resp = [e[0] for e in events if e[1] in ("maintainer", "owner")]
    maint_resp = [e[0] for e in events if e[1] == "maintainer"]

    g_reviews = [r for r in reviews if login(r) == GREPTILE]
    g_comments = [c for c in comments if login(c) == GREPTILE]
    g_summaries = [x for x in g_reviews + g_comments if G_SUMMARY.search(x["body"] or "")]
    g_times = [dt(r["submittedAt"]) for r in g_reviews if r["submittedAt"]] + [dt(c["createdAt"]) for c in g_comments]
    scores = [int(m.group(1)) for x in g_summaries for m in [G_SCORE.search(x["body"] or "")] if m]
    g_inline = sum(r["comments"]["totalCount"] for r in g_reviews)

    activity = sorted(
        [dt(c["createdAt"]) for c in comments if login(c) == author]
        + [dt(r["submittedAt"]) for r in reviews if login(r) == author and r["submittedAt"]]
        # only the author's own commits; a null user is an unlinked email, most often the author's
        + [dt(t["commit"]["committedDate"]) for t in tl if t["__typename"] == "PullRequestCommit"
           and (((t["commit"].get("author") or {}).get("user") or {}).get("login") in (author, None))]
        + [dt(t["createdAt"]) for t in tl if t["__typename"] == "HeadRefForcePushedEvent"
           and ((t.get("actor") or {}).get("login") == author)])
    activity = [a for a in activity if a <= end]
    responded = bool(first_fb and any(first_fb < a for a in activity))
    last_author = activity[-1] if activity else created
    # the ball was in the reviewers' court when the PR closed: the author acted after the last feedback
    waiting_on_reviewer = closed_unmerged and bool(last_fb) and last_author > last_fb[0]

    dup_text = [e[3]["body"] for e in events if e[1] in ("maintainer", "greptile", "owner")] + \
               [ic["body"] for r in reviews if src(r) in ("maintainer", "greptile")
                for ic in r["comments"]["nodes"]]
    # code blocks carry suggested package.json snippets ($schema URLs), not references to other extensions
    dup_hits = [m.group(0) for b in dup_text for m in [DUP_PHRASE.search(re.sub(r"```.*?```", "", b or "", flags=re.S))] if m]
    new_folder = added_pkgs[0] if added_pkgs else (touched[0] if is_new and touched else "")
    dup_heur = dup_candidates(new_folder, p["title"], created, df) if is_new and new_folder else []

    # Raycast reviews a PR only once it is out of draft; `ray publish` opens PRs as drafts
    # replay draft transitions: the first transition reveals the opening state (a PR can open ready, be
    # converted to draft by a reviewer, and be readied again); with none, the state never changed
    trans = sorted((dt(t["createdAt"]), t["__typename"]) for t in tl
                   if t["__typename"] in ("ReadyForReviewEvent", "ConvertToDraftEvent"))
    trans = [x for x in trans if x[0] <= end]
    opened_draft = trans[0][1] == "ReadyForReviewEvent" if trans else bool(p.get("isDraft"))
    draft_at_close = trans[-1][1] == "ConvertToDraftEvent" if trans else opened_draft
    readies = [t for t, k in trans if k == "ReadyForReviewEvent"]
    ready_at = created if not opened_draft else (readies[0] if readies else None)
    human_after_ready = [t for t in human_resp if ready_at and t >= ready_at]
    days = lambda a, b: round((b - a).total_seconds() / 86400, 2) if a and b else ""
    return {
        "number": p["number"], "url": p["url"], "title": p["title"], "author": author,
        "author_association": p["authorAssociation"], "created_at": p["createdAt"], "closed_at": p["closedAt"] or "",
        "merged_at": p["mergedAt"] or "", "state": p["state"], "period": period(created), "kind": kind,
        "bot_author": author in BOTS or author.endswith("[bot]"),
        "new_folder": new_folder, "extensions": "|".join(ext_labels or touched), "owners": "|".join(sorted(owners)),
        "close_by": close_by, "closer": closer,
        "auto_closed": auto_closed, "closed_unmerged": closed_unmerged, "stalled_ever": bool(stalled_at),
        "stale_clock": rule_at(stalled_at[0] if stalled_at else created),
        "greptile": bool(g_times), "greptile_first_at": min(g_times).isoformat() if g_times else "",
        "greptile_rounds": len(g_summaries), "greptile_inline": g_inline,
        "greptile_score_first": scores[0] if scores else "", "greptile_score_last": scores[-1] if scores else "",
        "feedback": bool(fb), "feedback_sources": "|".join(fb_sources),
        "fb_greptile": "greptile" in fb_sources, "fb_maintainer": "maintainer" in fb_sources,
        "fb_owner": "owner" in fb_sources, "fb_other": "other" in fb_sources,
        "last_feedback_source": last_fb[1] if last_fb else "",
        "changes_requested_by": "|".join(sorted({e[1] for e in events if e[2] == "CHANGES_REQUESTED"})),
        "author_responded_after_feedback": responded,
        "first_feedback_at": first_fb.isoformat() if first_fb else "",
        "last_author_activity_at": activity[-1].isoformat() if activity else "",
        "waiting_on_reviewer_at_close": waiting_on_reviewer,
        "days_to_merge": days(created, merged), "days_to_first_maint": days(created, maint_resp[0] if maint_resp else None),
        "days_to_first_human": days(created, human_resp[0] if human_resp else None),
        "days_to_first_feedback": days(created, first_fb),
        "opened_as_draft": opened_draft, "draft_at_close": draft_at_close, "ever_ready": bool(ready_at), "ready_at": ready_at.isoformat() if ready_at else "",
        "days_ready_to_first_human": days(ready_at, human_after_ready[0] if human_after_ready else None),
        "days_ready_to_merge": days(ready_at, merged),
        "days_last_feedback_to_close": days(last_fb[0], closed) if closed_unmerged and last_fb else "",
        "dup_phrase": bool(dup_hits) and is_new, "dup_phrase_hit": (dup_hits or [""])[0][:80],
        "dup_heur": bool(dup_heur), "dup_candidates": "|".join(dup_heur[:5]),
        "comments_truncated": p["comments"]["totalCount"] > len(comments),
    }


def chains(rows):
    """Group new-extension PRs by author + folder into submissions. A submission ends at its first merge;
    later PRs to that folder are updates. The last PR carries the outcome and the whole chain's feedback."""
    by = defaultdict(list)
    for r in rows:
        if r["kind"] == "new" and r["new_folder"]:
            by[(r["author"].lower(), r["new_folder"])].append(r)
    for (a, f), rs in by.items():
        rs.sort(key=lambda r: r["number"])
        cut = next((i for i, r in enumerate(rs) if r["merged_at"]), len(rs) - 1)
        for r in rs[cut + 1:]:  # after the merge: updates to an existing extension
            r["kind"] = "existing"
        rs = rs[:cut + 1]
        final = rs[-1]
        any_fb = any(x["feedback"] for x in rs)
        sources = sorted({s for x in rs for s in x["feedback_sources"].split("|") if s})
        for r in rs:
            r["chain_id"] = f"{a}/{f}"
            r["chain_len"] = len(rs)
            r["chain_final"] = r is final
            r["superseded"] = r is not final
            r["chain_outcome"] = final["close_by"]
            r["chain_dup_phrase"] = any(x["dup_phrase"] for x in rs)
            r["chain_feedback"] = any_fb
        final["feedback"] = any_fb
        final["feedback_sources"] = "|".join(sources)
        for s_ in ("greptile", "maintainer", "owner", "other"):
            final[f"fb_{s_}"] = s_ in sources
        # feedback on one PR answered on a later one still counts as a reply
        fbs = [x["first_feedback_at"] for x in rs if x["first_feedback_at"]]
        acts_ = [x["last_author_activity_at"] for x in rs if x["last_author_activity_at"]]
        final["author_responded_after_feedback"] = bool(fbs and acts_ and max(acts_) > min(fbs))
        final["chain_ever_ready"] = any(x["ever_ready"] for x in rs)
        if not final["last_feedback_source"]:
            final["last_feedback_source"] = next((x["last_feedback_source"] for x in reversed(rs)
                                                  if x["last_feedback_source"]), "")
        human = [float(x["days_to_first_human"]) for x in rs if x["days_to_first_human"] != ""]
        final["chain_any_human_reply"] = bool(human)
    for r in rows:
        r.setdefault("chain_id", "")
        r.setdefault("chain_len", 1 if r["kind"] == "new" else "")
        r.setdefault("chain_final", True)
        r.setdefault("superseded", False)
        r.setdefault("chain_outcome", r["close_by"])
        r.setdefault("chain_dup_phrase", r["dup_phrase"])
        r.setdefault("chain_feedback", r["feedback"])
        r.setdefault("chain_any_human_reply", r["days_to_first_human"] != "")
        r.setdefault("chain_ever_ready", r["ever_ready"])


def pct(a, b):
    return round(100 * a / b, 1) if b else ""


def med(xs):
    return round(st.median(xs), 1) if xs else ""


def p75(xs):
    return round(st.quantiles(xs, n=4)[2], 1) if len(xs) >= 4 else ""


def nums(rows, k):
    return [float(r[k]) for r in rows if r[k] != ""]


def main():
    raw = [json.loads(f.read_text()) for f in sorted((DATA / "raw" / "pr").glob("*.json"))]
    # folders added after the fork's last sync (2026-08-07): take the merge date of their new-extension PR
    for p in raw:
        if p["mergedAt"]:
            for f in (p.get("files") or {}).get("nodes") or []:
                if f["changeType"] == "ADDED" and re.fullmatch(r"extensions/[^/]+/package\.json", f["path"]):
                    folder_added.setdefault(f["path"].split("/")[1], dt(p["mergedAt"]))
    df = build_df(set(folder_added) | set(titles))
    rows = [derive(p, df) for p in raw]
    all_rows = rows
    rows = [r for r in rows if not r["bot_author"]]
    chains(rows)
    with open(DATA / "prs.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["number"]))

    by = defaultdict(list)
    for r in rows:
        by[r["period"]].append(r)
    out = []
    for per in sorted(by):
        R = by[per]
        rec = {"period": per, "prs": len(R), "prs_incl_bots": sum(1 for r in all_rows if r["period"] == per)}
        S = [r for r in R if r["chain_final"]]  # one row per submission
        rec["submissions"] = len(S)
        for k, v in (("merged", "merged"), ("auto_closed", "stale-bot"), ("author_closed", "author"),
                     ("open", "open"), ("unknown", "unknown")):
            rec[k] = sum(r["close_by"] == v for r in S)
        rec["rejected"] = sum(r["close_by"] in ("maintainer", "owner") for r in S)
        N = [r for r in S if r["kind"] == "new"]
        NA = [r for r in N if r["auto_closed"]]
        rec["new_auto_draft"] = sum(r["draft_at_close"] for r in NA)
        rec["new_auto_draft_pct"] = pct(rec["new_auto_draft"], len(NA)) if len(NA) >= 10 else ""
        rec["new_never_ready_pct"] = pct(sum(not r["chain_ever_ready"] and r["state"] != "OPEN" for r in N), len(N))
        rec["new_auto_never_ready"] = sum(not r["chain_ever_ready"] for r in NA)
        rec["new_auto_never_ready_pct"] = pct(rec["new_auto_never_ready"], len(NA)) if len(NA) >= 10 else ""  # too few to be a share
        NR = [r for r in N if r["ever_ready"]]
        rec["new_ready_first_human_median"] = med(nums(NR, "days_ready_to_first_human"))
        rec["new_ready_ttm_median"] = med(nums([r for r in NR if r["merged_at"]], "days_ready_to_merge"))
        # cohort: closed PRs, plus open ones ready for at least 21 days before the data date
        obs = [r for r in NR if r["state"] != "OPEN" or dt(r["ready_at"]) <= DATA_DATE - timedelta(days=21)]
        rec["new_ready_no_human_in_21d_pct"] = pct(sum(r["days_ready_to_first_human"] == "" or float(r["days_ready_to_first_human"]) > 21
                                                       for r in obs), len(obs))
        rec["new_ready_auto_no_human"] = sum(r["chain_ever_ready"] and not r["chain_any_human_reply"] for r in NA)
        rec["new_ready_auto_human"] = sum(r["chain_ever_ready"] and r["chain_any_human_reply"] for r in NA)
        rec["new_auto_no_human"] = sum(not r["chain_any_human_reply"] for r in NA)
        rec["new_auto_no_human_pct"] = pct(rec["new_auto_no_human"], len(NA))
        rec["new_auto_no_human_greptile"] = sum(not r["chain_any_human_reply"] and r["fb_greptile"] for r in NA)
        rec["new_human_reply_pct"] = pct(sum(r["chain_any_human_reply"] for r in N), len(N))
        rec["new_no_human_in_21d_pct"] = pct(sum(r["days_to_first_human"] == "" or float(r["days_to_first_human"]) > 21
                                                 for r in N if r["state"] != "OPEN"), sum(r["state"] != "OPEN" for r in N))
        for k in ("new", "existing"):
            K = [r for r in R if r["kind"] == k]
            S = [r for r in K if r["chain_final"]]  # submissions: resubmission chains collapsed
            rec[f"{k}_prs"] = len(K)
            rec[f"{k}_submissions"] = len(S)
            rec[f"{k}_merged"] = sum(1 for r in S if r["merged_at"])
            rec[f"{k}_merged_pct"] = pct(rec[f"{k}_merged"], len(S))
            rec[f"{k}_auto_closed"] = sum(r["auto_closed"] for r in S)
            rec[f"{k}_auto_closed_pct"] = pct(rec[f"{k}_auto_closed"], len(S))
            rec[f"{k}_author_closed_pct"] = pct(sum(r["close_by"] == "author" for r in S), len(S))
            rec[f"{k}_rejected_pct"] = pct(sum(r["close_by"] in ("maintainer", "owner") for r in S), len(S))
            ttm = nums([r for r in S if r["merged_at"]], "days_to_merge")
            rec[f"{k}_ttm_median"], rec[f"{k}_ttm_p75"] = med(ttm), p75(ttm)
            rec[f"{k}_first_human_median"] = med(nums(S, "days_to_first_human"))
            rec[f"{k}_first_maint_median"] = med(nums(S, "days_to_first_maint"))
        S = [r for r in R if r["chain_final"]]
        fb = [r for r in S if r["feedback"]]
        rec["opened_as_draft_pct"] = pct(sum(r["opened_as_draft"] for r in R), len(R))
        rec["greptile_pct"] = pct(sum(r["greptile"] for r in R), len(R))
        sc = nums([r for r in R if r["greptile"]], "greptile_score_first")
        rec["greptile_scored_prs"] = len(sc)
        rec["greptile_score_mean"] = round(sum(sc) / len(sc), 2) if len(sc) >= 20 else ""
        rec["greptile_rounds_mean"] = round(st.mean(int(r["greptile_rounds"]) for r in R if r["greptile"]), 2) \
            if any(r["greptile"] for r in R) else ""
        rec["feedback_pct"] = pct(len(fb), len(S))
        for s in ("greptile", "maintainer", "owner", "other"):
            rec[f"fb_{s}_pct"] = pct(sum(r[f"fb_{s}"] for r in S), len(S))
        rec["auto_closed_after_feedback"] = sum(r["auto_closed"] for r in fb)
        rec["auto_closed_after_feedback_new"] = sum(r["auto_closed"] for r in fb if r["kind"] == "new")
        rec["auto_closed_after_feedback_existing"] = sum(r["auto_closed"] for r in fb if r["kind"] == "existing")
        drop = [r for r in fb if r["closed_unmerged"]]
        rec["dropped_after_feedback_pct"] = pct(len(drop), len(fb))
        # closed unmerged with no author reply after feedback, as a share of everyone who got feedback
        rec["ghosted_after_feedback_pct"] = pct(sum(not r["author_responded_after_feedback"] for r in drop), len(fb))
        rec["auto_closed_waiting_on_reviewer"] = sum(r["auto_closed"] and r["waiting_on_reviewer_at_close"] for r in S)
        for s in ("greptile", "maintainer", "owner", "other"):
            rec[f"dropped_last_fb_{s}"] = sum(r["last_feedback_source"] == s for r in drop)
        N = [r for r in S if r["kind"] == "new"]
        rec["new_closed_unmerged"] = sum(r["closed_unmerged"] for r in N)
        rec["new_dup_phrase"] = sum(r["chain_dup_phrase"] for r in N)
        rec["new_dup_phrase_closed"] = sum(r["closed_unmerged"] and r["chain_dup_phrase"] for r in N)
        rec["new_dup_heur"] = sum(r["dup_heur"] for r in N)
        rec["new_dup_both"] = sum(r["dup_heur"] and r["chain_dup_phrase"] for r in N)
        rec["new_dup_heur_closed"] = sum(r["closed_unmerged"] and r["dup_heur"] for r in N)
        rec["superseded_prs"] = sum(r["superseded"] for r in R)
        out.append(rec)
    with open(DATA / "periods.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)

    # ---- most active existing extensions: merged PRs per extension per month
    act = defaultdict(Counter)
    for r in rows:
        if r["merged_at"] and r["kind"] == "existing":
            for e in r["extensions"].split("|"):
                if e:
                    act[e][r["merged_at"][:7]] += 1
    with open(DATA / "extensions_activity.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["extension", "title", "month", "merged_prs"])
        for e in sorted(act, key=lambda e: -sum(act[e].values())):
            for m in sorted(act[e]):
                w.writerow([e, titles.get(e, ""), m, act[e][m]])

    # ---- maintainer review/comment actions by person and year (excludes raycastbot and the PR's author)
    acts = Counter()
    for p in raw:
        a_ = (p.get("author") or {}).get("login")
        for x in p["reviews"]["nodes"] + p["comments"]["nodes"]:
            who = login(x)
            if x.get("authorAssociation") in MAINT_ASSOC and who not in BOTS and who and who != a_:
                acts[((x.get("submittedAt") or x.get("createdAt") or p["createdAt"])[:4], who)] += 1
    with open(DATA / "maintainer_actions.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["year", "maintainer", "actions", "share_pct"])
        for y in sorted({k[0] for k in acts}):
            tot_y = sum(v for k, v in acts.items() if k[0] == y)
            for (yy, who), v in sorted(acts.items(), key=lambda kv: -kv[1]):
                if yy == y:
                    w.writerow([y, who, v, round(100 * v / tot_y, 1)])

    # ---- raw Greptile inline findings, for clustering
    with open(DATA / "greptile_findings_raw.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["number", "created_at", "finding_at", "kind", "close_by", "chain_outcome", "path", "tag", "first_line"])
        meta = {r["number"]: r for r in rows}
        for p in raw:
            r = meta.get(p["number"])
            if not r:
                continue
            for rv in p["reviews"]["nodes"]:
                if login(rv) != GREPTILE:
                    continue
                for ic in rv["comments"]["nodes"]:
                    body = (ic["body"] or "").strip()
                    # two formats: early "style: ..." / "logic: ..." prefixes, later P0-P3 badge images or "[P1]"
                    badge = re.match(r'(?:<a[^>]*>)?\s*<img alt="(P\d)"[^>]*>\s*(?:</a>)?\s*|\[(P\d)\]\s*', body)
                    if badge:
                        tag, rest = (badge.group(1) or badge.group(2)), body[badge.end():]
                    else:
                        m = re.match(r"\**(style|logic|syntax|typo|bug|critical)\**:\s*", body, re.I)
                        tag, rest = (m.group(1).lower(), body[m.end():]) if m else ("", body)
                    first = re.sub(r"\s+", " ", rest.replace("**", "")).split("```")[0].strip()[:240]
                    w.writerow([p["number"], p["createdAt"], ic.get("createdAt") or rv["submittedAt"] or "", r["kind"],
                                r["close_by"], r["chain_outcome"], ic["path"] or "", tag, first])
    print(f"{len(rows)} human PRs, {len(out)} periods")


if __name__ == "__main__":
    main()
