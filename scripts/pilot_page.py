"""Render site/pilot.html from data/prs.csv and data/periods.csv (run analyze.py --period month first)."""
import csv, html, json, random
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
R = list(csv.DictReader(open(ROOT / "data" / "prs.csv")))
M = list(csv.DictReader(open(ROOT / "data" / "periods.csv")))
stamp = json.loads(next((ROOT / "data" / "raw").glob("collect_*.json")).read_text())
T = lambda r, k: r[k] == "True"
e = html.escape
rnd = random.Random(42)


def link(r):
    return f'<a href="{e(r["url"])}">#{r["number"]}</a>'


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "–"


def sample(rows, n):
    rows = list(rows)
    return sorted(rnd.sample(rows, min(n, len(rows))), key=lambda r: int(r["number"]))


OUT_LABEL = {"merged": "merged", "stale-bot": "auto-closed", "author": "closed by author",
             "maintainer": "closed by maintainer", "open": "open", "unknown": "unknown"}


def chip(r):
    return f'<span class="chip c-{r["close_by"]}">{OUT_LABEL[r["close_by"]]}</span>'


# ---- monthly table
cols = [("PRs (humans)", "prs"), ("Greptile coverage", "greptile_pct", "%"),
        ("New: PRs", "new_prs"), ("New: merged", "new_merged_pct", "%"), ("New: auto-closed", "new_auto_closed_pct", "%"),
        ("New: median days to merge", "new_ttm_median"), ("New: p75 days to merge", "new_ttm_p75"),
        ("New: median days to first maintainer reply", "new_first_maint_median"),
        ("Existing: PRs", "existing_prs"), ("Existing: merged", "existing_merged_pct", "%"),
        ("Existing: auto-closed", "existing_auto_closed_pct", "%"),
        ("Existing: median days to merge", "existing_ttm_median"), ("Existing: p75 days to merge", "existing_ttm_p75"),
        ("Existing: median days to first maintainer reply", "existing_first_maint_median"),
        ("PRs that got feedback", "feedback_prs"), ("Auto-closed after feedback", "auto_closed_after_feedback"),
        ("Feedback, then closed unmerged", "dropped_after_feedback_pct", "%"),
        ("Feedback, then no author activity before close", "ghosted_after_feedback_pct", "%")]
thead = "".join(f"<th>{m['period']}</th>" for m in M)
trows = ""
for c in cols:
    cells = "".join(f"<td>{m[c[1]]}{c[2] if len(c) > 2 and m[c[1]] != '' else ''}</td>" for m in M)
    trows += f"<tr><th scope='row'>{c[0]}</th>{cells}</tr>"

# ---- outcome table by kind
outcome_rows = ""
for k, label in (("new", "New extension"), ("existing", "Existing extension")):
    K = [r for r in R if r["kind"] == k]
    c = Counter(r["close_by"] for r in K)
    outcome_rows += (f"<tr><th scope='row'>{label}</th><td>{len(K)}</td>"
                     + "".join(f"<td>{c[x]} <span class='dim'>({pct(c[x], len(K))})</span></td>"
                               for x in ("merged", "stale-bot", "author", "maintainer")) + "</tr>")

# ---- resubmissions
N = [r for r in R if r["kind"] == "new"]
chain = defaultdict(list)
for r in N:
    chain[(r["author"], r["new_folder"])].append(r)
author_closed = [r for r in N if r["close_by"] == "author"]
resub = [r for r in author_closed if any(int(o["number"]) > int(r["number"]) for o in chain[(r["author"], r["new_folder"])])]

# ---- Greptile contemporaneous comparison (Feb-Mar)
gcmp = ""
for k, label in (("new", "New"), ("existing", "Existing")):
    for g in ("True", "False"):
        K = [r for r in R if r["kind"] == k and r["greptile"] == g and r["created_at"] >= "2025-02-01"]
        gcmp += (f"<tr><th scope='row'>{label}, {'reviewed' if g == 'True' else 'not reviewed'} by Greptile</th>"
                 f"<td>{len(K)}</td><td>{pct(sum(bool(r['merged_at']) for r in K), len(K))}</td>"
                 f"<td>{pct(sum(T(r, 'auto_closed') for r in K), len(K))}</td></tr>")


def table(rows, cols):
    head = "".join(f"<th>{h}</th>" for h, _ in cols)
    body = "".join("<tr>" + "".join(f"<td>{f(r)}</td>" for _, f in cols) + "</tr>" for r in rows)
    return f'<div class="scroll"><table class="list"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


auto = [r for r in R if T(r, "auto_closed")]
spot_auto = table(sample(auto, 10), [
    ("PR", link), ("Title", lambda r: e(r["title"])), ("Type", lambda r: r["kind"]),
    ("Feedback", lambda r: r["feedback_kind"] or "none"),
    ("Author replied after it", lambda r: "yes" if T(r, "author_responded_after_feedback") else "no"),
    ("Clock", lambda r: r["stale_rule"] or "–")])
dp = [r for r in N if T(r, "dup_phrase")]
spot_phrase = table(sample(dp, 15), [
    ("PR", link), ("New folder", lambda r: f"<code>{e(r['new_folder'])}</code>"),
    ("What the reviewer linked or said", lambda r: f"<code>{e(r['dup_phrase_hit'])}</code>"), ("Outcome", chip)])
dh = [r for r in N if T(r, "dup_heur") and not T(r, "dup_phrase")]
spot_heur = table(sample(dh, 15), [
    ("PR", link), ("New folder", lambda r: f"<code>{e(r['new_folder'])}</code>"),
    ("Existing folders it matched", lambda r: " ".join(f"<code>{e(x)}</code>" for x in r["dup_candidates"].split("|"))),
    ("Outcome", chip)])
spot_resub = table(sample(resub, 10), [
    ("Closed PR", link), ("Folder", lambda r: f"<code>{e(r['new_folder'])}</code>"),
    ("Resubmitted as", lambda r: " ".join(link(o) for o in chain[(r["author"], r["new_folder"])]
                                          if int(o["number"]) > int(r["number"]))),
    ("Final outcome", lambda r: chip(max(chain[(r["author"], r["new_folder"])], key=lambda o: int(o["number"]))))])

S = dict(
    total=len(R), new=len(N), existing=sum(r["kind"] == "existing" for r in R), auto=len(auto),
    auto_fb=sum(T(r, "feedback") for r in auto), auto_new=sum(r["kind"] == "new" for r in auto),
    auto_fb_replied=sum(T(r, "author_responded_after_feedback") for r in auto),
    dp=len(dp), dh=len(dh) + sum(T(r, "dup_heur") for r in dp), both=sum(T(r, "dup_heur") for r in dp),
    ac=len(author_closed), resub=len(resub),
    new_closed=sum(T(r, "closed_unmerged") for r in N),
    rule2114=sum(r["stale_rule"] == "21+14" for r in auto))

page = f"""<title>Raycast PR Pilot</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Fraunces:opsz,wght@9..144,600&display=swap">
<style>
/* Layout: one reading column; wide tables scroll inside their own frames. */
:root {{
  --bg: #f6f6f3; --surface: #ffffff; --fg: #1d1f24; --muted: #5f6470; --rule: #dcdcd6;
  --accent: #c8352b; --merged: #2f7d4f; --stale: #c8352b; --author: #8a6d1f; --maint: #4b5a8c;
  --display: "Fraunces", Georgia, serif; --body: "IBM Plex Sans", system-ui, sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg: #15171b; --surface: #1d2026; --fg: #e8e8e4; --muted: #a0a5b0; --rule: #33373f;
  --accent: #ff6b5e; --merged: #5fc48a; --stale: #ff6b5e; --author: #e0bd5a; --maint: #9aa8e0; color-scheme: dark }} }}
:root[data-theme="dark"] {{
  --bg: #15171b; --surface: #1d2026; --fg: #e8e8e4; --muted: #a0a5b0; --rule: #33373f;
  --accent: #ff6b5e; --merged: #5fc48a; --stale: #ff6b5e; --author: #e0bd5a; --maint: #9aa8e0; color-scheme: dark }}
body {{ background: var(--bg); color: var(--fg); font: 15px/1.55 var(--body); }}
main {{ max-width: 980px; margin: 0 auto; padding-block: 40px 80px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
  display: grid; gap: 44px; }}
section {{ display: grid; gap: 14px; min-width: 0; }}
h1 {{ font: 600 clamp(28px, 5vw, 40px)/1.1 var(--display); margin: 0; text-wrap: balance; }}
h2 {{ font: 600 22px/1.25 var(--display); margin: 0; text-wrap: balance; }}
p {{ margin: 0; max-width: 68ch; }}
.eyebrow {{ font: 500 12px var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }}
.dim {{ color: var(--muted); }}
a {{ color: var(--accent); }}
a:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
code {{ font: 13px var(--mono); }}
.facts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 1px; background: var(--rule);
  border: 1px solid var(--rule); }}
.facts div {{ background: var(--surface); padding: 14px 16px; display: grid; gap: 2px; }}
.facts b {{ font: 600 26px/1.1 var(--display); font-variant-numeric: tabular-nums; }}
.facts span {{ color: var(--muted); font-size: 13px; }}
.scroll {{ overflow-x: auto; border: 1px solid var(--rule); background: var(--surface); }}
table {{ border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }}
th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--rule); vertical-align: top; }}
thead th {{ font: 500 12px var(--mono); letter-spacing: .04em; text-transform: uppercase; color: var(--muted); white-space: nowrap; }}
table.grid td {{ text-align: right; white-space: nowrap; }}
table.grid tbody th {{ font-weight: 400; }}
tr:last-child td, tr:last-child th {{ border-bottom: 0; }}
.chip {{ display: inline-block; font: 500 12px var(--mono); padding: 1px 8px; border-radius: 3px; white-space: nowrap;
  border: 1px solid currentColor; }}
.c-merged {{ color: var(--merged); }} .c-stale-bot {{ color: var(--stale); }} .c-author {{ color: var(--author); }}
.c-maintainer {{ color: var(--maint); }} .c-open, .c-unknown {{ color: var(--muted); }}
ol.decide {{ margin: 0; padding-left: 22px; display: grid; gap: 14px; max-width: 72ch; }}
ol.decide b {{ display: block; }}
.callout {{ border-left: 3px solid var(--accent); padding: 4px 0 4px 14px; max-width: 72ch; }}
</style>
<main>
<header style="display:grid;gap:10px">
  <span class="eyebrow">raycast/extensions · pilot · PRs created {stamp['window'][0]} to {stamp['window'][1]}</span>
  <h1>What the first Greptile quarter looks like</h1>
  <p class="dim">Collected {stamp['collected_at'][:10]} through GitHub GraphQL. {stamp['prs']:,} PRs, which matches the
  validation target for Jan–Mar 2025 (374 + 413 + 515) exactly. Bot-authored PRs are excluded below, leaving {S['total']:,}.
  The point of this page is to check the definitions against real PRs before collecting 2024–2026.</p>
</header>

<section>
  <div class="facts">
    <div><b>{S['new']}</b><span>new-extension PRs</span></div>
    <div><b>{S['existing']}</b><span>PRs to existing extensions</span></div>
    <div><b>{S['auto']}</b><span>auto-closed by the stale bot</span></div>
    <div><b>{S['auto_fb']}</b><span>of those had feedback first</span></div>
    <div><b>{S['auto_fb_replied']}</b><span>of those, the author had replied at least once</span></div>
  </div>
</section>

<section>
  <h2>Decisions before the full run</h2>
  <ol class="decide">
    <li><b>Count resubmissions as one submission.</b> {S['resub']} of {S['ac']} new-extension PRs "closed by author" were
    reopened as a fresh PR for the same folder, most within minutes. Counting them as dropout inflates question 6.
    Proposal: group by author + folder and score the chain by its last PR.</li>
    <li><b>Tighten the duplicate heuristic.</b> The reviewer-link signal ({S['dp']} PRs) mostly finds real duplicates.
    The folder-name match ({S['dh']} PRs) fires on generic lead words like <code>time</code>, <code>text</code> and
    <code>project</code>. Proposal: only match on a lead word that is rare across folders, then hand-check 30.</li>
    <li><b>Decide whether extension owners count as feedback.</b> Today feedback means Greptile or a Raycast maintainer.
    Extension owners (association CONTRIBUTOR) also file "changes requested" reviews on PRs to their extension; they're
    tracked in a separate column for now.</li>
    <li><b>Measure Greptile before and after, not with and without.</b> Inside Feb–Mar the PRs Greptile skipped are mostly
    the ones opened before it was switched on, so the comparison below is confounded. The full run gives a clean
    2024 baseline.</li>
    <li><b>Tag each PR with the stale clock in force.</b> {S['rule2114']} of the {S['auto']} auto-closes here ran on the
    21 + 14 day clock (Feb 25 – Mar 26, 2025); the rest on 14 + 7. The clock changed six times in the window.</li>
  </ol>
</section>

<section>
  <h2>By month</h2>
  <p class="dim">Greptile's first review was on #16482, opened Jan 19. Coverage went from 1% in January to 92% in March.
  "Feedback" is a Greptile review or a maintainer comment or non-approval review before the PR closed.</p>
  <div class="scroll"><table class="grid"><thead><tr><th></th>{thead}</tr></thead><tbody>{trows}</tbody></table></div>
</section>

<section>
  <h2>How PRs end</h2>
  <p class="dim">Only about a third of new-extension PRs merge. Existing-extension PRs merge almost nine times out of ten.</p>
  <div class="scroll"><table class="grid"><thead><tr><th></th><th>PRs</th><th>Merged</th><th>Auto-closed</th>
  <th>Closed by author</th><th>Closed by maintainer</th></tr></thead><tbody>{outcome_rows}</tbody></table></div>
</section>

<section>
  <h2>Greptile vs. not, Feb–Mar (confounded)</h2>
  <div class="scroll"><table class="grid"><thead><tr><th></th><th>PRs</th><th>Merged</th><th>Auto-closed</th></tr></thead>
  <tbody>{gcmp}</tbody></table></div>
</section>

<section>
  <h2>Spot-check: auto-closed</h2>
  <p class="dim">Random 10 of {S['auto']}. Auto-closed means closed unmerged by raycastbot with the stalled label or the
  inactivity message. raycastbot also closes every merged PR, so the closer alone isn't enough.</p>
  {spot_auto}
</section>

<section>
  <h2>Spot-check: duplicates, reviewer signal</h2>
  <p class="dim">Random 15 of {S['dp']} new-extension PRs where a maintainer or Greptile linked a store extension or said
  one exists. {S['both']} of them also match the folder-name heuristic.</p>
  {spot_phrase}
</section>

<section>
  <h2>Spot-check: duplicates, folder-name only</h2>
  <p class="dim">Random 15 of the PRs only the heuristic caught. Expect noise; this is the upper bound.</p>
  {spot_heur}
</section>

<section>
  <h2>Spot-check: author-closed, then resubmitted</h2>
  <p class="dim">Random 10 of {S['resub']}.</p>
  {spot_resub}
</section>
</main>
"""
(ROOT / "site").mkdir(exist_ok=True)
(ROOT / "site" / "pilot.html").write_text(page)
print("wrote site/pilot.html", S)
