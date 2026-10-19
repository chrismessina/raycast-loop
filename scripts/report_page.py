"""Render docs/index.html (the GitHub Pages site) from data/*.csv (run analyze.py --period month first).

Narrative lives in site/narrative.json so numbers and prose can be revised independently.
"""
import base64, csv, html, json, statistics as st
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data"
P = list(csv.DictReader(open(D / "periods.csv")))
R = list(csv.DictReader(open(D / "prs.csv")))
EV = list(csv.DictReader(open(D / "events.csv")))
ACT = list(csv.DictReader(open(D / "extensions_activity.csv")))
NARR = json.loads((ROOT / "site" / "narrative.json").read_text())
N_ = NARR
THEMES = list(csv.DictReader(open(D / "greptile_findings.csv"))) if (D / "greptile_findings.csv").exists() else []
DUPCHECK = list(csv.DictReader(open(D / "dup_handcheck.csv"))) if (D / "dup_handcheck.csv").exists() else []
stamps = [json.loads(f.read_text()) for f in (D / "raw").glob("collect_*.json")]
collected = max(s["collected_at"] for s in stamps)[:10]
T = lambda r, k: r[k] == "True"
e = html.escape

months = [p["period"] for p in P]
data_date = date.fromisoformat(collected)
provisional_from = (data_date - timedelta(days=32)).strftime("%Y-%m")


def col(k, cast=float):
    return [cast(p[k]) if p[k] != "" else None for p in P]


# chart series: (label, values, slot) where slot indexes the validated palette order
auto_new = col("new_auto_closed", int)
draft_new = col("new_auto_draft", int)
ready_nohuman = col("new_ready_auto_no_human", int)
charts = {
    "volume": {"unit": "PRs", "series": [
        ["New-extension PRs", col("new_prs", int), 0], ["Existing-extension PRs", col("existing_prs", int), 3]]},
    "outcomes": {"unit": "submissions", "series": [
        ["Merged", col("merged", int), 0], ["Closed by author", col("author_closed", int), 1],
        ["Auto-closed (stale)", col("auto_closed", int), 2], ["Closed by maintainer or owner", col("rejected", int), 3],
        ["Still open", col("open", int), 4], ["Closer unknown", col("unknown", int), 0]]},
    "rates": {"unit": "%", "series": [
        ["New: merged", col("new_merged_pct"), 0], ["Existing: merged", col("existing_merged_pct"), 1],
        ["New: auto-closed", col("new_auto_closed_pct"), 2], ["Existing: auto-closed", col("existing_auto_closed_pct"), 3]]},
    "drafts": {"unit": "%", "series": [
        ["PRs opened as drafts", col("opened_as_draft_pct"), 3],
        ["New submissions never marked ready", col("new_never_ready_pct"), 1],
        ["Auto-closed new submissions never marked ready", col("new_auto_never_ready_pct"), 2]]},
    "autoclose_state": {"unit": "submissions", "series": [
        ["Had a human reply", col("new_ready_auto_human", int), 0],
        ["Never marked ready", col("new_auto_never_ready", int), 2],
        ["Ready, no human reply", ready_nohuman, 3]]},
    "velocity": {"unit": "days", "series": [
        ["New: median days, ready to merge", col("new_ready_ttm_median"), 0],
        ["Existing: median days to merge", col("existing_ttm_median"), 1],
        ["New: median days, ready to first human reply", col("new_ready_first_human_median"), 2],
        ["Existing: median days to first human reply", col("existing_first_human_median"), 3]]},
    "nohuman21": {"unit": "%", "series": [
        ["Ready new submissions with no human reply within 21 days", col("new_ready_no_human_in_21d_pct"), 2]]},
    "greptile_cov": {"unit": "%", "series": [["Share of PRs Greptile reviewed", col("greptile_pct"), 3]]},
    "greptile_score": {"unit": "/5", "series": [["Mean first confidence score", col("greptile_score_mean"), 0]]},
    "feedback_src": {"unit": "%", "series": [
        ["Greptile", col("fb_greptile_pct"), 3], ["Raycast maintainer", col("fb_maintainer_pct"), 0],
        ["Extension owner", col("fb_owner_pct"), 1], ["Other contributor", col("fb_other_pct"), 4]]},
    "dropout": {"unit": "%", "series": [
        ["Got feedback, closed unmerged", col("dropped_after_feedback_pct"), 2],
        ["Got feedback, closed unmerged without replying", col("ghosted_after_feedback_pct"), 1]]},
    "dups": {"unit": "submissions", "series": [
        ["New-extension submissions", col("new_submissions", int), 3],
        ["Reviewer pointed to an existing extension", col("new_dup_phrase", int), 2],
        ["Name matches an older extension", col("new_dup_heur", int), 1],
        ["Both signals", col("new_dup_both", int), 0]]},
}

# ---- most active existing extensions since 2025
tot = Counter()
by_ext = defaultdict(Counter)
for a in ACT:
    if a["month"] >= "2025-01":
        tot[a["extension"]] += int(a["merged_prs"])
        by_ext[a["extension"]][a["month"]] += int(a["merged_prs"])
title_of = {a["extension"]: a["title"] for a in ACT}
top = [x for x, _ in tot.most_common(20)]
act_months = [m for m in months if m >= "2025-01"]
charts["extensions"] = {"unit": "merged PRs", "months": act_months, "hidden_after": 5, "series": [
    [title_of.get(x) or x, [by_ext[x][m] for m in act_months], i % 5] for i, x in enumerate(top[:10])]}
top_rows = "".join(
    f"<tr><td class='rank'>{i + 1}</td><td><a href='https://github.com/raycast/extensions/tree/main/extensions/{e(x)}'>"
    f"{e(title_of.get(x) or x)}</a> <code>{e(x)}</code></td><td class='num'>{tot[x]}</td>"
    f"<td class='num'>{sum(by_ext[x][m] for m in act_months[-3:])}</td></tr>" for i, x in enumerate(top))

# ---- headline numbers
H = NARR["headline_numbers"]

# ---- stale clock table
clock_rows = "".join(f"<tr><td>{e(a)}</td><td>{e(b)}</td><td class='num'>{e(c)}</td></tr>" for a, b, c in NARR["clock_table"])

themes_rows = "".join(
    f"<tr><td>{e(t['theme'])}</td><td class='num'>{t['findings']}</td><td class='num'>{t['prs']}</td>"
    f"<td>{'✓' if t['in_public_rubric'] == 'yes' else ('partly' if t['in_public_rubric'] == 'partly' else '–')}</td>"
    f"<td class='dim'>{e(t['example'])}</td></tr>" for t in THEMES)

dup_rows = "".join(
    f"<tr><td><a href='https://github.com/raycast/extensions/pull/{d['number']}'>#{d['number']}</a></td>"
    f"<td><code>{e(d['new_folder'])}</code></td><td><code>{e(d['matched'])}</code></td>"
    f"<td>{e(d['verdict'])}</td><td class='dim'>{e(d['note'])}</td></tr>" for d in DUPCHECK)


def chart_block(cid, title, sub, height=320):
    return f"""<figure class="chart" id="fig-{cid}">
  <figcaption><h3>{e(title)}</h3><p>{sub}</p></figcaption>
  <div class="toggles" data-for="{cid}" role="group" aria-label="Series"></div>
  <div class="canvas-wrap" style="height:{height}px"><canvas id="c-{cid}" role="img" aria-label="{e(title)}"></canvas></div>
  <details class="tablev"><summary>Show as table</summary><div class="tscroll" data-table="{cid}"></div></details>
</figure>"""


def section(sid, eyebrow, title, body):
    return f'<section id="{sid}"><div class="sec-head"><span class="eyebrow">{eyebrow}</span><h2>{e(title)}</h2></div>{body}</section>'


N = NARR
ICONS = {f.stem: "data:image/png;base64," + base64.b64encode(f.read_bytes()).decode() for f in sorted((D / "icons").glob("*.png"))}

LT = json.loads((D / "downloads_longtail.json").read_text())
FLOW = json.loads((D / "flow_2026h1.json").read_text())
UNSHIPPED = json.loads((D / "unshipped.json").read_text())
CONTRIB = list(csv.DictReader(open(D / "extensions_contributors.csv")))

charts["lt_bands"] = {"unit": "%", "type": "bar", "labels": [b["band"] for b in LT["bands"]], "noEvents": True,
                      "xTitle": "Downloads per extension", "series": [
    ["Share of extensions", [round(100 * b["extensions"] / LT["extensions"], 1) for b in LT["bands"]], 3],
    ["Share of all downloads", [round(100 * b["downloads"] / LT["downloads"], 1) for b in LT["bands"]], 1]]}
charts["lt_cohort"] = {"unit": "downloads", "type": "bar", "labels": [str(c["year"]) for c in LT["cohorts"]],
                       "noEvents": True, "xTitle": "Year the extension was published", "series": [
    ["Median downloads", [c["median"] for c in LT["cohorts"]], 3]]}

recs_html = "".join(
    f'<article class="rec"><span class="rec-n">{i + 1}</span><div class="rec-body"><h3>{e(r["title"])}</h3>'
    f'<div class="rec-tags"><span class="tag">Reach: {e(r["reach"])}</span><span class="tag cost-{r["cost"].lower()}">Cost: {e(r["cost"])}</span></div>'
    f'<p>{r["what"]}</p><p class="rec-trade"><b>Trade-off.</b> {e(r["tradeoff"])}</p></div></article>'
    for i, r in enumerate(N_["recommendations"]["items"]))

# ---- horizontal timeline: events placed by date, stacked into rows so labels never overlap
from datetime import date as _d
T0, T1 = _d.fromisoformat(EV[0]["date"]) - timedelta(days=4), _d(2026, 11, 1)  # start just before the first event
TW = round((T1 - T0).days * 5.3)
xof = lambda iso: round((_d.fromisoformat(iso) - T0).days / (T1 - T0).days * TW)
CARD = 176
rows_end, placed = [], []
for i, v in enumerate(EV):
    x = xof(v["date"])
    row = next((k for k, end in enumerate(rows_end) if end + 12 <= x), len(rows_end))
    if row == len(rows_end):
        rows_end.append(0)
    rows_end[row] = x + CARD
    placed.append((i, v, x, row))
ticks = []
y, m = (T0.year, T0.month + 1) if T0.month < 12 else (T0.year + 1, 1)
first = True
while (y, m) < (2026, 11):
    x = xof(f"{y}-{m:02d}-01")
    mon = _d(y, m, 1).strftime("%b")
    lab = f"{mon} {y}" if first or m == 1 else mon
    ticks.append(f'<span class="tl-tick{" yr" if m == 1 or first else ""}" style="left:{x}px">{lab}</span>')
    first = False
    m += 1
    if m == 13:
        y, m = y + 1, 1
tl_height = 52 + len(rows_end) * 70
timeline_html = (
    f'<div class="tl-scroll" tabindex="0" aria-label="Timeline of events, scrolls horizontally">'
    f'<div class="tl" style="width:{TW + CARD}px;height:{tl_height}px"><div class="tl-axis"></div>{"".join(ticks)}'
    + "".join(f'<div class="tl-ev" data-layer="{e(v["layer"])}" style="left:{x}px;top:{40 + row * 70}px">'
              f'<span class="ev-i"><img src="{ICONS[v["icon"]]}" alt=""></span><span class="ev-d">{e(v["date"])}</span>'
              + (f'<a class="ev-l" href="{e(v["url"])}">{e(v["label"])}</a>' if v["url"] else f'<span class="ev-l">{e(v["label"])}</span>') + '</div>'
              for i, v, x, row in placed)
    + '</div></div>')

# ---- flow diagram of 2026-H1 new-extension submissions
F = FLOW
pc = lambda a: f"{round(100 * a / F['submissions'])}%"
flow_svg = f"""<figure class="flow">
<div class="flow-scroll"><svg viewBox="0 0 1000 470" role="img" aria-label="Path of {F['submissions']:,} new-extension submissions opened in the first half of 2026: {F['merged']} merged; {F['never_ready']} were never marked ready; {F['auto_closed'] - F['auto_never_ready']} were auto-closed after being marked ready.">
<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="currentColor"/></marker>
<marker id="ahr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="f-red"/></marker></defs>
<g class="f-node"><rect x="10" y="150" width="150" height="64" rx="10"/><text x="85" y="176" text-anchor="middle" class="f-t">Author runs</text><text x="85" y="196" text-anchor="middle" class="f-t"><tspan class="f-mono">ray publish</tspan></text></g>
<g class="f-node"><rect x="200" y="150" width="170" height="64" rx="10"/><text x="285" y="176" text-anchor="middle" class="f-t">PR opened</text><text x="285" y="196" text-anchor="middle" class="f-s">{F['opened_draft']:,} as drafts · {F['opened_ready']} ready</text></g>
<g class="f-node"><rect x="410" y="150" width="140" height="64" rx="10"/><text x="480" y="176" text-anchor="middle" class="f-t">Marked ready</text><text x="480" y="196" text-anchor="middle" class="f-s">{F['ready']:,} ({pc(F['ready'])})</text></g>
<g class="f-node"><rect x="590" y="140" width="210" height="84" rx="10"/><text x="695" y="168" text-anchor="middle" class="f-t">Review</text><text x="695" y="189" text-anchor="middle" class="f-s">Greptile: within minutes</text><text x="695" y="207" text-anchor="middle" class="f-s">first human reply: median {F['median_days_ready_to_human']:.0f} days</text></g>
<g class="f-good"><rect x="840" y="150" width="150" height="64" rx="10"/><text x="915" y="176" text-anchor="middle" class="f-t">Merged</text><text x="915" y="196" text-anchor="middle" class="f-s">{F['merged']} ({pc(F['merged'])})</text></g>
<g class="f-edge"><line x1="160" y1="182" x2="196" y2="182" marker-end="url(#ah)"/><line x1="370" y1="182" x2="406" y2="182" marker-end="url(#ah)"/>
<line x1="550" y1="182" x2="586" y2="182" marker-end="url(#ah)"/><line x1="800" y1="182" x2="836" y2="182" marker-end="url(#ah)"/></g>
<path d="M760,140 C760,80 630,80 630,136" class="f-loop" marker-end="url(#ah)"/>
<text x="695" y="62" text-anchor="middle" class="f-s">changes requested → author pushes fixes → repeat</text>
<text x="695" y="44" text-anchor="middle" class="f-s">{F['dup_flagged']} of {F['submissions']:,} were told a similar extension already exists</text>
<g class="f-drop"><path d="M285,214 L285,296" marker-end="url(#ahr)"/><path d="M740,224 L740,296" marker-end="url(#ahr)"/></g>
<path d="M640,224 L520,300" class="f-edge-grey" marker-end="url(#ah)"/>
<g class="f-bad"><rect x="160" y="300" width="250" height="90" rx="10"/><text x="285" y="326" text-anchor="middle" class="f-t">Never marked ready: {F['never_ready']}</text>
<text x="285" y="348" text-anchor="middle" class="f-s">{F['auto_never_ready']} auto-closed as drafts</text><text x="285" y="368" text-anchor="middle" class="f-s">{F['never_ready_author_closed']} closed by the author</text></g>
<g class="f-node"><rect x="430" y="304" width="160" height="82" rx="10"/><text x="510" y="330" text-anchor="middle" class="f-t">Closed by a person</text>
<text x="510" y="350" text-anchor="middle" class="f-s">{F['ready_author_closed']} by the author</text><text x="510" y="370" text-anchor="middle" class="f-s">{F['rejected']} rejected</text></g>
<g class="f-bad"><rect x="610" y="300" width="380" height="160" rx="10"/><text x="800" y="326" text-anchor="middle" class="f-t">Auto-closed after ready: {F['auto_closed'] - F['auto_never_ready']}</text>
<text x="800" y="350" text-anchor="middle" class="f-s">{F['auto_ready_no_human']} never got a human reply</text>
<text x="800" y="372" text-anchor="middle" class="f-s">{F['auto_reviewed']} got one, then went quiet:</text>
<text x="800" y="394" text-anchor="middle" class="f-s">{F['auto_reviewed_replied_then_stopped']} had answered earlier feedback; a reviewer spoke last</text>
<text x="800" y="414" text-anchor="middle" class="f-s">({F['replied_before_first_human']} of them last acted before the first human reply)</text>
<text x="800" y="436" text-anchor="middle" class="f-s">{F['auto_reviewed_never_replied']} never answered · {F['auto_reviewed_waiting_on_reviewer']} were waiting on a reviewer</text></g>
</svg></div>
<figcaption>The submission loop for new extensions opened January–June 2026 ({F['submissions']:,}). Red boxes are auto-closes. Every submission ends in Merged or in exactly one of the bottom boxes. By outcome: {F['merged']} merged, {F['auto_closed']} auto-closed, {F['author_closed']} closed by the author, {F['rejected']} rejected.</figcaption>
</figure>"""

unshipped_html = "".join(
    f'<article class="un"><div class="un-head"><h3>{e(u["name"])}</h3><a class="un-pr" href="https://github.com/raycast/extensions/pull/{u["number"]}">#{u["number"]}</a></div>'
    f'<div class="un-meta">{e(u["opened"])} · {e(u["outcome"])}</div><p>{e(u["what"])}</p><p class="dim">{e(u["story"])}</p></article>'
    for u in UNSHIPPED)

contrib_rows = "".join(
    f"<tr><td class='rank'>{i + 1}</td><td><a href='{e(c['store_url'])}'>{e(c['title'])}</a></td>"
    f"<td class='num'>{int(c['store_contributors'])}</td><td class='num'>{int(c['pr_authors_2024_2026'])}</td>"
    f"<td class='num'>{int(c['downloads']):,}</td></tr>" for i, c in enumerate(CONTRIB[:15]))

CK = N_["checklist"]
checklist_html = (
    f'<div class="cols"><div class="callout"><h3>Today</h3><ul class="ck">{"".join(f"<li>{e(x)}</li>" for x in CK["current"])}</ul>'
    f'<p class="dim">{e(CK["critique"])}</p></div>'
    f'<div class="callout"><h3>Proposed</h3><ul class="ck">{"".join(f"<li>{x}</li>" for x in CK["proposed"])}</ul>'
    f'<p class="dim">{e(CK["automated"])}</p></div></div>')

payload = json.dumps({"months": months, "provisional_from": provisional_from, "charts": charts,
                      "events": EV, "icons": ICONS}, separators=(",", ":"))

page = f"""<title>The Raycast Loop</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Geist+Mono:wght@400;500&display=swap">
<style>
/* Layout: dark single-theme page in the visual language of raycast.com; one centered column with full-width chart cards. */
:root {{
  color-scheme: dark;
  --bg: #07080a; --surface: #0c0d0f; --raised: #111214; --line: #242728; --line-soft: #1b1c1e;
  --fg: #f4f4f6; --fg-2: #c2c7ca; --fg-3: #9c9c9d; --fg-4: #6a6b6c; --accent: #ff6363;
  --s0: #1f9a66; --s1: #9478dc; --s2: #e04b4b; --s3: #2a8ccc; --s4: #bf8710;
  --sans: "Inter", system-ui, -apple-system, sans-serif; --mono: "Geist Mono", ui-monospace, "SF Mono", monospace;
}}
body {{ background: var(--bg); color: var(--fg); font: 15px/1.6 var(--sans); letter-spacing: .1px; }}
body::before {{ content: ""; position: fixed; inset: 0 0 auto; height: env(safe-area-inset-top, 0px); z-index: 10; background: var(--bg); }}
.glow {{ position: absolute; inset: 0 0 auto; height: 620px; pointer-events: none; overflow: hidden; z-index: 0; }}
.glow::before {{ content: ""; position: absolute; left: 50%; top: -340px; width: 1100px; height: 700px; transform: translateX(-50%);
  background: radial-gradient(closest-side, rgba(255,99,99,.20), rgba(255,99,99,.06) 55%, transparent); }}
main {{ position: relative; z-index: 1; max-width: 1080px; margin: 0 auto; padding-block: 72px 120px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
  display: grid; gap: 96px; }}
a {{ color: var(--fg); text-decoration-color: var(--fg-4); text-underline-offset: 3px; }}
a:hover {{ text-decoration-color: var(--accent); }}
a:focus-visible, button:focus-visible, summary:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }}
code {{ font: 12.5px var(--mono); color: var(--fg-3); }}
.hero {{ display: grid; gap: 22px; justify-items: center; text-align: center; padding-top: 24px; }}
.pill {{ font: 500 12px var(--mono); color: var(--fg-2); border: 1px solid var(--line); background: rgba(255,255,255,.03);
  border-radius: 999px; padding: 5px 14px; letter-spacing: .3px; }}
.pill b {{ color: var(--accent); font-weight: 500; }}
h1 {{ margin: 0; padding-bottom: .12em; font: 600 clamp(36px, 7vw, 64px)/1.18 var(--sans); letter-spacing: -1.5px; text-wrap: balance; max-width: 16ch;
  background: linear-gradient(180deg, #fff 30%, #9c9c9d); -webkit-background-clip: text; background-clip: text; color: transparent; }}
.lede {{ margin: 0; max-width: 62ch; color: var(--fg-3); font-size: 17px; line-height: 1.7; text-wrap: pretty; }}
.byline {{ font: 12px var(--mono); color: var(--fg-4); }}
.stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(300px, 100%), 1fr)); gap: 1px; width: 100%; margin-top: 18px;
  background: var(--line); border: 1px solid var(--line); border-radius: 16px; overflow: hidden; }}
.stat {{ background: var(--surface); padding: 22px 22px 20px; display: grid; gap: 6px; text-align: left; align-content: start; }}
.stat b {{ font: 600 34px/1 var(--sans); letter-spacing: -1px; font-variant-numeric: tabular-nums; }}
.stat span {{ color: var(--fg-3); font-size: 13.5px; line-height: 1.45; }}
section {{ display: grid; gap: 28px; min-width: 0; }}
.sec-head {{ display: grid; gap: 10px; }}
.eyebrow {{ font: 500 12px var(--mono); letter-spacing: 1px; text-transform: uppercase; color: var(--accent); }}
h2 {{ margin: 0; font: 600 clamp(26px, 4vw, 36px)/1.15 var(--sans); letter-spacing: -.8px; text-wrap: balance; max-width: 26ch; }}
h3 {{ margin: 0; font: 600 17px/1.3 var(--sans); letter-spacing: -.2px; }}
.prose {{ display: grid; gap: 14px; max-width: 68ch; color: var(--fg-2); }}
.prose p {{ margin: 0; }}
.prose strong {{ color: var(--fg); font-weight: 600; }}
.prose ul {{ margin: 0; padding-left: 20px; display: grid; gap: 8px; }}
.chart {{ margin: 0; background: linear-gradient(180deg, var(--raised), var(--surface)); border: 1px solid var(--line);
  border-radius: 16px; padding: 22px; display: grid; gap: 14px; min-width: 0; }}
.chart figcaption {{ display: grid; gap: 4px; }}
.chart figcaption p {{ margin: 0; color: var(--fg-3); font-size: 13.5px; max-width: 80ch; }}
.canvas-wrap {{ position: relative; width: 100%; min-width: 0; }}
.grid2 {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }}
.grid3 {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }}
.toggles {{ display: flex; flex-wrap: wrap; gap: 8px; }}
.tg {{ font: 500 12.5px var(--sans); color: var(--fg-2); background: rgba(255,255,255,.03); border: 1px solid var(--line);
  border-radius: 8px; padding: 5px 10px 5px 8px; display: inline-flex; align-items: center; gap: 8px; cursor: pointer; }}
.tg i {{ width: 14px; height: 2px; border-radius: 2px; background: var(--c); }}
.tg[aria-pressed="false"] {{ color: var(--fg-4); background: transparent; }}
.tg[aria-pressed="false"] i {{ background: var(--fg-4); opacity: .5; }}
.tg:hover {{ border-color: var(--fg-4); }}
.lead {{ margin: 0; max-width: 68ch; }}
.recs {{ display: grid; gap: 12px; }}
.rec {{ display: grid; grid-template-columns: 36px 1fr; gap: 14px; background: linear-gradient(180deg, var(--raised), var(--surface));
  border: 1px solid var(--line); border-radius: 16px; padding: 18px 20px; }}
.rec-n {{ font: 600 15px var(--mono); color: var(--accent); border: 1px solid rgba(255,99,99,.35); border-radius: 10px;
  width: 32px; height: 32px; display: grid; place-items: center; }}
.rec-body {{ display: grid; gap: 8px; min-width: 0; }}
.rec-body p {{ margin: 0; color: var(--fg-2); max-width: 78ch; }}
.rec-trade {{ font-size: 13.5px; color: var(--fg-3) !important; }}
.rec-trade b {{ color: var(--fg-2); font-weight: 600; }}
.rec-tags {{ display: flex; flex-wrap: wrap; gap: 6px; }}
.tag {{ font: 500 11.5px var(--mono); color: var(--fg-2); border: 1px solid var(--line); border-radius: 999px; padding: 2px 10px; }}
.cost-low {{ color: var(--s0); border-color: color-mix(in srgb, var(--s0) 45%, transparent); }}
.cost-medium {{ color: var(--s4); border-color: color-mix(in srgb, var(--s4) 45%, transparent); }}
.tl-head {{ display: flex; flex-wrap: wrap; gap: 12px 24px; justify-content: space-between; align-items: end; }}
.tl-head p {{ margin: 0; max-width: 60ch; }}
.tl-controls {{ display: grid; gap: 8px; justify-items: end; }}
.range {{ display: flex; gap: 8px; flex-wrap: wrap; }}
.tl-scroll {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 16px; background: var(--surface); }}
.tl {{ position: relative; margin: 0 24px; }}
.tl-axis {{ position: absolute; left: 0; right: 0; top: 26px; height: 1px; background: var(--line); }}
.tl-tick {{ position: absolute; top: 6px; font: 11px var(--mono); color: var(--fg-4); transform: translateX(-1px);
  border-left: 1px solid var(--line); padding-left: 4px; height: 20px; }}
.tl-tick.yr {{ color: var(--fg-2); border-color: var(--fg-4); }}
.tl-ev {{ position: absolute; width: 168px; display: grid; grid-template-columns: 20px 1fr; gap: 2px 8px; font-size: 12.5px;
  border-left: 1px dashed var(--line); padding-left: 6px; }}
.tl-ev[hidden] {{ display: none; }}
.tl-ev .ev-d {{ grid-column: 2; }}
.tl-ev .ev-l {{ grid-column: 2; color: var(--fg-2); line-height: 1.35; }}
a.ev-l {{ text-decoration-color: var(--line); }}
.ev-i {{ grid-row: 1 / span 2; width: 20px; height: 20px; border-radius: 6px; background: #fff; display: grid; place-items: center;
  box-shadow: 0 0 0 2px var(--lc); }}
.ev-i img {{ width: 14px; height: 14px; border-radius: 3px; }}
.tl-ev[data-layer="raycast"] {{ --lc: var(--accent); }}
.tl-ev[data-layer="agents"] {{ --lc: var(--s1); }}
.tl-ev[data-layer="review"] {{ --lc: var(--s3); }}
.flow {{ margin: 0; background: var(--surface); border: 1px solid var(--line); border-radius: 16px; padding: 18px; display: grid; gap: 10px; }}
.flow-scroll {{ overflow-x: auto; }}
.flow svg {{ display: block; width: 100%; min-width: 820px; height: auto; color: var(--fg-3); }}
.flow figcaption {{ color: var(--fg-3); font-size: 13.5px; }}
.f-node rect {{ fill: var(--raised); stroke: var(--line); }}
.f-good rect {{ fill: color-mix(in srgb, var(--s0) 18%, var(--surface)); stroke: var(--s0); }}
.f-bad rect {{ fill: color-mix(in srgb, var(--s2) 12%, var(--surface)); stroke: color-mix(in srgb, var(--s2) 70%, transparent); }}
.f-t {{ fill: var(--fg); font: 600 13px var(--sans); }}
.f-s {{ fill: var(--fg-3); font: 12px var(--sans); }}
.f-mono {{ font-family: var(--mono); }}
.f-edge line, .f-loop {{ stroke: currentColor; stroke-width: 1.5; fill: none; }}
.f-loop {{ stroke-dasharray: 4 4; }}
.f-drop path {{ stroke: var(--s2); stroke-width: 1.5; fill: none; }}
.f-edge-grey {{ stroke: currentColor; stroke-width: 1.5; fill: none; }}
.f-red {{ fill: var(--s2); }}
.uns {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(320px, 100%), 1fr)); gap: 12px; }}
.un {{ background: linear-gradient(180deg, var(--raised), var(--surface)); border: 1px solid var(--line); border-radius: 16px;
  padding: 18px 20px; display: grid; gap: 8px; align-content: start; }}
.un p {{ margin: 0; font-size: 14px; color: var(--fg-2); }}
.un p.dim {{ color: var(--fg-3); font-size: 13.5px; }}
.un-head {{ display: flex; justify-content: space-between; align-items: baseline; gap: 10px; }}
.un-pr {{ font: 12px var(--mono); }}
.un-meta {{ font: 12px var(--mono); color: var(--fg-4); }}
ul.ck {{ list-style: none; padding: 0; margin: 0; display: grid; gap: 8px; }}
ul.ck li {{ position: relative; padding-left: 26px; color: var(--fg-2); font-size: 14px; }}
ul.ck li::before {{ content: ""; position: absolute; left: 0; top: 3px; width: 14px; height: 14px; border: 1.5px solid var(--fg-4); border-radius: 4px; }}
.events {{ background: var(--surface); border: 1px solid var(--line); border-radius: 16px; padding: 18px 22px; display: grid; gap: 14px; }}
.events-head {{ display: flex; flex-wrap: wrap; gap: 10px 18px; align-items: center; justify-content: space-between; }}
.events ol {{ list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 6px 22px; }}
.events li {{ display: grid; grid-template-columns: 22px 84px 1fr; gap: 8px; font-size: 13px; color: var(--fg-2); align-items: baseline; }}
.events li[hidden] {{ display: none; }}
.ev-d {{ font: 12px var(--mono); color: var(--fg-4); }}
.layers {{ display: flex; flex-wrap: wrap; gap: 8px; }}
details.tablev summary {{ cursor: pointer; font: 500 12.5px var(--sans); color: var(--fg-3); width: max-content; }}
.tscroll, .scroll {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 12px; margin-top: 10px; }}
.scroll {{ margin-top: 0; background: var(--surface); }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; font-variant-numeric: tabular-nums; }}
th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--line-soft); vertical-align: top; }}
thead th {{ font: 500 11.5px var(--mono); color: var(--fg-4); letter-spacing: .3px; white-space: nowrap; }}
td.num, th.num {{ text-align: right; white-space: nowrap; }}
td.rank {{ color: var(--fg-4); font-family: var(--mono); width: 2ch; }}
tr:last-child td {{ border-bottom: 0; }}
.dim {{ color: var(--fg-3); }}
.callout {{ border: 1px solid var(--line); border-radius: 16px; padding: 22px; background: var(--surface); display: grid; gap: 12px; align-content: start; }}
.callout.verdict .prose {{ max-width: none; }}
.callout.verdict {{ border-color: rgba(255,99,99,.35); background: linear-gradient(180deg, rgba(255,99,99,.07), var(--surface)); }}
.cols {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }}
.cols ul {{ margin: 0; padding-left: 18px; display: grid; gap: 8px; color: var(--fg-2); }}
.prov {{ font: 12px var(--mono); color: var(--fg-4); }}
footer {{ color: var(--fg-4); font-size: 13px; display: grid; gap: 6px; border-top: 1px solid var(--line); padding-top: 24px; }}
@media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; animation: none !important; }} }}
</style>
<div class="glow" aria-hidden="true"></div>
<main>
<header class="hero">
  <span class="pill">raycast/extensions · {e(N['window'])} · data as of <b>{collected}</b></span>
  <h1>{e(N['title'])}</h1>
  <p class="lede">{N['lede']}</p>
  <span class="byline">Independent analysis by <a href="https://chrismessina.me">Chris Messina</a>. Not affiliated with or endorsed by Raycast.</span>
  <div class="stats">{''.join(f'<div class="stat"><b>{e(a)}</b><span>{e(b)}</span></div>' for a, b in H)}</div>
</header>

<section id="recommendations"><div class="sec-head"><span class="eyebrow">What to change</span><h2>{e(N["recommendations"]["title"])}</h2></div>
<p class="dim lead">{e(N["recommendations"]["intro"])}</p><div class="recs">{recs_html}</div></section>

<section id="timeline"><div class="sec-head"><span class="eyebrow">Timeline</span><h2>{e(N["timeline"]["title"])}</h2></div>
<div class="tl-head"><p class="dim">{e(N["timeline"]["body"])}</p>
  <div class="tl-controls">
    <div class="layers" role="group" aria-label="Event layers">
      <button class="tg" data-layer="raycast" aria-pressed="true" style="--c:var(--accent)"><i></i>Raycast releases</button>
      <button class="tg" data-layer="agents" aria-pressed="true" style="--c:var(--s1)"><i></i>Coding agents</button>
      <button class="tg" data-layer="review" aria-pressed="true" style="--c:var(--s3)"><i></i>Review process</button>
    </div>
    <div class="range" role="group" aria-label="Chart range">
      <button class="tg rg" data-from="" aria-pressed="true">All months</button>
      <button class="tg rg" data-from="2025-02" aria-pressed="false">Since Greptile (Feb 2025)</button>
    </div></div></div>
{timeline_html}
<span class="prov">Months from {provisional_from} on are provisional: those PRs haven't been open long enough to be stale-closed.</span>
</section>

{section("volume", "Volume", N["volume"]["title"],
         f'<div class="prose">{N["volume"]["body"]}</div>' + chart_block("volume", "PRs opened per month", "Human-authored PRs by type, by month opened."))}

{section("outcomes", "Outcomes", N["outcomes"]["title"],
         f'<div class="prose">{N["outcomes"]["body"]}</div>'
         + chart_block("outcomes", "How PRs opened each month ended", "Counts by month opened. Resubmitted new-extension PRs are counted once, under the final PR. Click a series to hide it.", 360)
         + chart_block("rates", "Merge and auto-close rates", "Share of submissions opened that month, new vs. existing extensions."))}

{section("drafts", "Why they close", N["drafts"]["title"],
         f'<div class="prose">{N["drafts"]["body"]}</div>' + flow_svg
         + chart_block("drafts", "Drafts", "Share of all PRs opened as drafts; share of new submissions never marked ready; share of auto-closed new submissions never marked ready.")
         + chart_block("autoclose_state", "Auto-closed new submissions, by what happened first", "Never-ready PRs were never in a reviewer's queue. The rest were."))}

{section("unshipped", "What didn't ship", N["unshipped"]["title"],
         f'<div class="prose">{N["unshipped"]["body"]}</div><div class="uns">{unshipped_html}</div>')}

{section("velocity", "Velocity", N["velocity"]["title"],
         f'<div class="prose">{N["velocity"]["body"]}</div>'
         + chart_block("velocity", "Days to merge and to first human reply (median)", "New extensions are measured from when the PR was marked ready for review. First human reply means a Raycast maintainer or the extension's owner. Medians cover PRs that got a reply.")
         + chart_block("nohuman21", "Ready new submissions with no human reply within 21 days", "Includes PRs that never got one: closed PRs, plus open ones ready for at least 21 days. 21 days is the stale bot's clock for most of the window.", 260))}

{section("greptile", "Greptile", N["greptile"]["title"],
         f'<div class="prose">{N["greptile"]["body"]}</div><div class="grid2">'
         + chart_block("greptile_cov", "Coverage", "Share of PRs with any Greptile review.", 220)
         + chart_block("greptile_score", "Confidence score", "Mean of Greptile's first confidence score per PR, from mid-2025 when it started publishing one.", 220)
         + '</div>')}

{section("friction", "Friction", N["friction"]["title"],
         f'<div class="prose">{N["friction"]["body"]}</div>'
         + chart_block("feedback_src", "Where feedback comes from", "Share of submissions that got feedback from each source before closing.")
         + chart_block("dropout", "Dropout after feedback", "Of submissions that got feedback, the share that closed unmerged, and the share that closed unmerged with no reply from the author."))}

{section("themes", "What Greptile flags", N["themes"]["title"],
         f'<div class="prose">{N["themes"]["body"]}</div>'
         + (f'<div class="scroll"><table><thead><tr><th>Theme</th><th class="num">Findings</th><th class="num">PRs</th><th>In public rubric</th><th>Example</th></tr></thead><tbody>{themes_rows}</tbody></table></div>' if THEMES else ''))}

{section("duplicates", "Duplicates", N["duplicates"]["title"],
         f'<div class="prose">{N["duplicates"]["body"]}</div>'
         + chart_block("dups", "New-extension submissions and likely duplicates", "Two imperfect signals over the same submissions: a reviewer linked or named an existing extension, and the new folder shares a rare name with an older one.")
         + (f'<details class="tablev"><summary>Hand-check of {len(DUPCHECK)} name matches</summary><div class="tscroll"><table><thead><tr><th>PR</th><th>New folder</th><th>Matched</th><th>Verdict</th><th>Note</th></tr></thead><tbody>{dup_rows}</tbody></table></div></details>' if DUPCHECK else ''))}

{section("longtail", "Popularity", N["longtail"]["title"],
         f'<div class="prose">{N["longtail"]["body"]}</div><div class="grid2">'
         + chart_block("lt_bands", "Extensions and downloads by download band", "Share of the 3,437 Store extensions in each band, and the share of all downloads they account for.", 280)
         + chart_block("lt_cohort", "Median downloads by year published", "Older extensions have had longer to collect downloads.", 280)
         + '</div>')}

{section("extensions", "Most active", N["extensions"]["title"],
         f'<div class="prose">{N["extensions"]["body"]}</div>'
         + chart_block("extensions", "Merged PRs per month, top 10 extensions since 2025", "The top five are on; switch others on to compare.", 320)
         + f'<div class="grid2"><div class="scroll"><table><thead><tr><th></th><th>Most merged PRs</th><th class="num">Since Jan 2025</th><th class="num">Last 3 mo.</th></tr></thead><tbody>{top_rows}</tbody></table></div>'
         + f'<div class="scroll"><table><thead><tr><th></th><th>Most contributors</th><th class="num">In Store</th><th class="num">PR authors 2024–26</th><th class="num">Downloads</th></tr></thead><tbody>{contrib_rows}</tbody></table></div></div>')}

{section("decision", "The decision", N["decision"]["title"],
         f'<div class="prose">{N["decision"]["body"]}</div>'
         f'<div class="cols"><div class="callout"><h3>For publishing the rules</h3><ul>{"".join(f"<li>{x}</li>" for x in N["decision"]["for"])}</ul></div>'
         f'<div class="callout"><h3>Against, or not enough</h3><ul>{"".join(f"<li>{x}</li>" for x in N["decision"]["against"])}</ul></div></div>'
         f'<div class="callout verdict"><h3>Recommendation</h3><div class="prose">{N["decision"]["verdict"]}</div></div>'
         f'<div class="sec-head" style="margin-top:12px"><h3>{e(N["checklist"]["title"])}</h3></div>' + checklist_html)}

{section("method", "Method", "How this was measured",
         f'<div class="prose">{N["method"]}</div>'
         f'<div class="scroll"><table><thead><tr><th>In effect</th><th>Stale + close (days)</th><th class="num">Auto-closes under it</th></tr></thead><tbody>{clock_rows}</tbody></table></div>')}

<footer><span>Data: GitHub GraphQL, {collected}. Scripts and derived data: <a href="https://github.com/chrismessina/raycast-loop">github.com/chrismessina/raycast-loop</a>. Raw GraphQL snapshot: <a href="https://github.com/chrismessina/raycast-loop/releases/download/data-2026-10-19/raw.tar.zst">raw.tar.zst</a> (17 MB).</span>
<span>Independent analysis by <a href="https://chrismessina.me">Chris Messina</a>. Not affiliated with or endorsed by Raycast.</span></footer>
</main>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script id="payload" type="application/json">{payload.replace("</", "<\\/")}</script>
<script>
(() => {{
const DATA = JSON.parse(document.getElementById("payload").textContent);
const css = getComputedStyle(document.documentElement);
const tok = n => css.getPropertyValue(n).trim();
const SLOTS = ["--s0", "--s1", "--s2", "--s3", "--s4"].map(tok);
const layersOn = new Set(["raycast", "agents", "review"]);
const LAYER_COLOR = {{ raycast: tok("--accent"), agents: tok("--s1"), review: tok("--s3") }};
const charts = [];
const ICON = Object.fromEntries(Object.entries(DATA.icons).map(([k, src]) => {{ const im = new Image(); im.onload = () => charts.forEach(c => c.update()); im.src = src; return [k, im]; }}));

Chart.defaults.font.family = tok("--sans");
Chart.defaults.font.size = 12;
Chart.defaults.color = tok("--fg-4");

function xPos(scale, labels, iso) {{
  const [y, m, d] = iso.split("-").map(Number);
  const i = labels.indexOf(`${{y}}-${{String(m).padStart(2, "0")}}`);
  if (i < 0) return null;
  const days = new Date(y, m, 0).getDate();
  const a = scale.getPixelForValue(i), b = i + 1 < labels.length ? scale.getPixelForValue(i + 1) : a + (a - scale.getPixelForValue(i - 1));
  return a + (b - a) * (d - 1) / days;
}}

const eventsPlugin = {{
  id: "events",
  beforeDatasetsDraw(chart) {{
    const {{ ctx, chartArea: a, scales: {{ x }} }} = chart;
    const labels = chart.data.labels;
    ctx.save();
    // provisional band
    const pi = labels.indexOf(DATA.provisional_from);
    if (pi >= 0) {{
      const px = x.getPixelForValue(pi) - (x.getPixelForValue(1) - x.getPixelForValue(0)) / 2;
      ctx.fillStyle = "rgba(255,255,255,0.035)";
      ctx.fillRect(px, a.top, a.right - px, a.bottom - a.top);
    }}
    DATA.events.forEach((ev, i) => {{
      if (!layersOn.has(ev.layer)) return;
      const px = xPos(x, labels, ev.date);
      if (px == null || px < a.left || px > a.right) return;
      ctx.strokeStyle = LAYER_COLOR[ev.layer]; ctx.globalAlpha = 0.45; ctx.setLineDash([3, 4]); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(px, a.top + 10); ctx.lineTo(px, a.bottom); ctx.stroke();
      ctx.globalAlpha = 1; ctx.setLineDash([]);
      ctx.fillStyle = "#fff"; ctx.strokeStyle = LAYER_COLOR[ev.layer]; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(px, a.top + 2, 9, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      const im = ICON[ev.icon];
      if (im && im.complete) ctx.drawImage(im, px - 6, a.top - 4, 12, 12);
    }});
    ctx.restore();
  }}
}};

function makeTable(cid, labels, series, unit, xTitle) {{
  const host = document.querySelector(`[data-table="${{cid}}"]`);
  const t = document.createElement("table");
  const hr = t.createTHead().insertRow();
  [xTitle || "Month", ...series.map(s => s[0])].forEach((h, i) => {{ const th = document.createElement("th"); th.textContent = h; if (i) th.className = "num"; hr.appendChild(th); }});
  const tb = t.createTBody();
  labels.forEach((m, j) => {{
    const r = tb.insertRow();
    const c0 = r.insertCell(); c0.textContent = m;
    series.forEach(s => {{ const c = r.insertCell(); c.className = "num"; c.textContent = s[1][j] == null ? "–" : s[1][j]; }});
  }});
  host.appendChild(t);
}}

function build(cid, cfg) {{
  const el = document.getElementById(`c-${{cid}}`);
  if (!el) return;
  const labels = cfg.labels || cfg.months || DATA.months;
  const isBar = cfg.type === "bar";
  const ds = cfg.series.map(([label, vals, slot], i) => ({{
    label, data: vals.slice(), borderColor: SLOTS[slot], backgroundColor: SLOTS[slot], borderWidth: isBar ? 0 : 2, tension: 0.25,
    borderRadius: isBar ? 4 : 0, maxBarThickness: 44,
    pointRadius: 0, pointHoverRadius: 4, pointHoverBorderWidth: 2, pointHoverBorderColor: tok("--surface"), spanGaps: true,
    borderDash: i >= 5 ? [5, 4] : [], hidden: cfg.hidden_after != null && i >= cfg.hidden_after,
  }}));
  const unit = cfg.unit;
  const chart = new Chart(el, {{
    type: isBar ? "bar" : "line",
    data: {{ labels: labels.slice(), datasets: ds }},
    plugins: cfg.noEvents ? [] : [eventsPlugin],
    options: {{
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: {{ mode: "index", intersect: isBar }},
      layout: {{ padding: {{ top: 14 }} }},
      scales: {{
        x: {{ grid: {{ display: false }}, border: {{ color: tok("--line") }},
              title: {{ display: !!cfg.xTitle, text: cfg.xTitle || "", color: tok("--fg-4") }},
              ticks: {{ maxRotation: 0, autoSkip: !isBar, autoSkipPadding: 18, color: tok("--fg-4"),
                        callback(v) {{ const m = this.chart.data.labels[v]; return isBar || m.endsWith("-01") || this.chart.data.labels.length < 16 ? m : m.slice(5); }} }} }},
        y: {{ beginAtZero: true, grid: {{ color: tok("--line-soft") }}, border: {{ display: false }},
              ticks: {{ color: tok("--fg-4"), callback: v => unit === "%" ? v + "%" : v }} }},
      }},
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          backgroundColor: tok("--raised"), borderColor: tok("--line"), borderWidth: 1, titleColor: tok("--fg"),
          bodyColor: tok("--fg-2"), padding: 10, boxWidth: 12, boxHeight: 2, usePointStyle: false, cornerRadius: 8,
          titleFont: {{ family: tok("--mono"), weight: "500" }},
          callbacks: {{
            title: items => items[0].label + (!isBar && items[0].label >= DATA.provisional_from ? "  (provisional)" : ""),
            label: c => ` ${{c.parsed.y == null ? "–" : c.parsed.y.toLocaleString("en-US")}}${{unit === "%" ? "%" : ""}}  ${{c.dataset.label}}`,
          }},
        }},
      }},
    }},
  }});
  chart.$full = {{ labels: labels.slice(), data: cfg.series.map(s => s[1].slice()), sliceable: !cfg.noEvents }};
  charts.push(chart);
  const host = document.querySelector(`.toggles[data-for="${{cid}}"]`);
  ds.forEach((d, i) => {{
    const b = document.createElement("button");
    b.className = "tg"; b.type = "button"; b.style.setProperty("--c", d.borderColor);
    b.setAttribute("aria-pressed", String(!d.hidden));
    b.append(document.createElement("i"), document.createTextNode(d.label));
    b.addEventListener("click", () => {{
      const vis = chart.isDatasetVisible(i);
      chart.setDatasetVisibility(i, !vis); b.setAttribute("aria-pressed", String(!vis)); chart.update();
    }});
    host.appendChild(b);
  }});
  if (ds.length < 2) host.remove();
  makeTable(cid, labels, cfg.series, unit, cfg.xTitle);
}}

Object.entries(DATA.charts).forEach(([cid, cfg]) => build(cid, cfg));

document.querySelectorAll(".layers .tg").forEach(b => b.addEventListener("click", () => {{
  const l = b.dataset.layer, on = b.getAttribute("aria-pressed") !== "true";
  b.setAttribute("aria-pressed", String(on));
  on ? layersOn.add(l) : layersOn.delete(l);
  document.querySelectorAll(`.tl-ev[data-layer="${{l}}"]`).forEach(li => li.hidden = !on);
  charts.forEach(c => c.update());
}}));

// narrow every time-based chart to the Greptile era, or back to the full window
document.querySelectorAll(".range .rg").forEach(b => b.addEventListener("click", () => {{
  document.querySelectorAll(".range .rg").forEach(x => x.setAttribute("aria-pressed", String(x === b)));
  const from = b.dataset.from;
  charts.forEach(c => {{
    if (!c.$full.sliceable) return;
    const i = from ? Math.max(0, c.$full.labels.findIndex(m => m >= from)) : 0;
    c.data.labels = c.$full.labels.slice(i);
    c.data.datasets.forEach((d, k) => d.data = c.$full.data[k].slice(i));
    c.update();
  }});
}}));
}})();
</script>
"""
(ROOT / "docs").mkdir(exist_ok=True)
(ROOT / "docs" / "index.html").write_text(page)
print("wrote docs/index.html", len(page) // 1024, "KB")
