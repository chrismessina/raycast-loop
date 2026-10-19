"""Cluster Greptile inline findings into themes by keyword rules; write data/greptile_findings.csv.

Rules are ordered: the first matching theme wins. `rubric` says whether the public
.github/copilot-instructions.md covers the theme; `rules` maps to Greptile's custom rule numbers
(export of 2026-09-26, mapped in raycast-extensions-skills/.../reference/greptile-rules.md).
"""
import csv, json, re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data"

BUGS_LABEL = "Behavior bugs and edge cases"
STYLE_LABEL = "Cleanup: unused code, logging, naming, duplication"
THEMES = [
    ("CHANGELOG entry or {PR_MERGE_DATE} format", r"changelog|pr_merge_date|unreleased", "yes", "02, 07, 08"),
    ("Screenshots / metadata folder", r"metadata/|screenshot", "partly", "03"),
    ("Hand-typed preferences or arguments (use generated types)", r"raycast-env|getpreferencevalues|preferences?` (interface|type)|manual(ly)? .*(preferences|arguments)|auto-?generated|generated types", "no", "01, 13"),
    ("AI tools / ai.yaml configuration", r"ai\.yaml|ai tool|\btools?\b.*(instructions|evals)|evals?\b", "yes", ""),
    ("Localization / non-English text", r"locale|locali[sz]|english|chinese|japanese|translat(e|ion)|toLocale", "yes", "06"),
    ("Error handling (showFailureToast, try/catch, unhandled)", r"showfailuretoast|error handling|try[-/ ]?catch|unhandled|catch block|rejection|error (state|message|toast)|fail(s|ure)? silently|swallow", "yes", ""),
    ("Security: injection, secrets, unsafe shell", r"inject|escap|sanitiz|shell|exec(sync)?\b|secret|token.*(log|expos|leak)|api key|password|credential|xss|eval\(", "no", "17"),
    ("package.json metadata (title, categories, platforms, $schema)", r"package\.json|categor|title case|subtitle|\$schema|platforms?\b|keywords|\bicon\b|description field|author field", "partly", "10, 11, 16, 18, 24"),
    ("Dependencies, lock files, fetch polyfills", r"node-fetch|cross-fetch|lock ?file|yarn\.lock|pnpm|bun\.lock|unused dependenc|dependency|devdependenc|registry", "partly", "04, 12"),
    ("Lint / formatting config (ESLint, Prettier)", r"eslint|prettier|printwidth|defineconfig|tsconfig", "partly", "05, 09, 14"),
    ("Raycast API idioms (getFavicon, launchCommand, trash, hooks)", r"getfavicon|favicon|launchcommand|raycast://|trash\(|usefetch|usepromise|usecachedpromise|uselocalstorage|@raycast/utils|closemainwindow|popToRoot|clipboard\.|showhud|actionpanel|action\.|list\.item|detail|keyboard shortcut|shortcut", "partly", "15, 19, 20, 21, 26, 30"),
    ("Windows / cross-platform compatibility", r"windows|macos-specific|cross-platform|applescript|platform", "no", "18, 19, 31"),
    ("Docs and README", r"readme|documentation|docs?\b", "partly", ""),
    ("Type safety (any, unsafe casts)", r"\bany\b|type assertion|\bas unknown|type safety|typescript type|non-null assertion|type guard|typed", "no", ""),
    ("Performance and re-renders", r"performance|re-?render|memo|useeffect|dependency array|infinite loop|expensive|cache|debounce|throttl|memory leak", "no", "22"),
    (BUGS_LABEL, r"incorrect|wrong|never|always|race|null|undefined|edge case|off-by|bug|will fail|breaks?|mismatch|inconsistent|missing check|not handled|stale|overflow|timezone|parse", "no", ""),
    (STYLE_LABEL, r"unused|console\.(log|error)|debug|redundant|duplicat|naming|rename|dead code|simplif|unnecessary|remove", "no", ""),
]
COMPILED = [(n, re.compile(p, re.I), rub, rules) for n, p, rub, rules in THEMES]


BUGS = "Behavior bugs and edge cases"
STYLE = "Cleanup: unused code, logging, naming, duplication"


MECHANICAL = {"CHANGELOG entry or {PR_MERGE_DATE} format", "Screenshots / metadata folder",
              "Hand-typed preferences or arguments (use generated types)",
              "package.json metadata (title, categories, platforms, $schema)", "Dependencies, lock files, fetch polyfills",
              "Lint / formatting config (ESLint, Prettier)", "Localization / non-English text"}
SEVERE = {"logic", "bug", "critical", "P0", "P1"}


def theme_of(text, path, tag):
    # match on the finding's text; the file name alone (package.json, a preferences file) says little about the issue
    for n, rx, rub, rules in COMPILED:
        if rx.search(text) or (n.startswith("CHANGELOG") and "CHANGELOG" in path):
            # a runtime defect that happens to mention preferences or locale is a bug, not a repository requirement
            if n in MECHANICAL and tag in SEVERE:
                return BUGS, "no", ""
            return n, rub, rules
    # unmatched findings are mostly extension-specific; Greptile's own severity says which kind
    if tag in ("logic", "bug", "critical", "P0", "P1", "P2"):
        return BUGS, "no", ""
    if tag in ("style", "syntax", "typo", "P3"):
        return STYLE, "no", ""
    return "Other", "no", ""


def main():
    F = list(csv.DictReader(open(D / "greptile_findings_raw.csv")))
    agg = defaultdict(lambda: {"findings": 0, "prs": set(), "ex": Counter(), "abandoned_prs": set(), "pre": 0, "post": 0})
    meta = {}
    tagged = []
    for f in F:
        n, rub, rules = theme_of(f["first_line"], f["path"].split("/")[-1], f["tag"])
        meta[n] = (rub, rules)
        a = agg[n]
        a["findings"] += 1
        a["prs"].add(f["number"])
        if f["chain_outcome"] in ("stale-bot", "author"):
            a["abandoned_prs"].add(f["number"])
        a["pre" if (f["finding_at"] or f["created_at"]) < "2025-08-29" else "post"] += 1
        a["ex"][f["first_line"][:140]] += 1
        tagged.append({**f, "theme": n})
    total = sum(a["findings"] for a in agg.values())
    pre = sum(a["pre"] for a in agg.values()) or 1
    post = sum(a["post"] for a in agg.values()) or 1
    rows = []
    for n, a in sorted(agg.items(), key=lambda kv: -kv[1]["findings"]):
        # the most common phrasing, preferring a mid-length one as the example
        ex = max(a["ex"].items(), key=lambda kv: (kv[1], -abs(len(kv[0]) - 90)))[0]
        rows.append({"theme": n, "findings": a["findings"], "share_pct": round(100 * a["findings"] / total, 1),
                     "prs": len(a["prs"]), "abandoned_prs": len(a["abandoned_prs"]),
                     "share_before_rubric_pct": round(100 * a["pre"] / pre, 1),
                     "share_after_rubric_pct": round(100 * a["post"] / post, 1),
                     "in_public_rubric": meta[n][0], "greptile_rules": meta[n][1], "example": ex})
    with open(D / "greptile_findings.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with open(D / "greptile_findings_tagged.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(tagged[0]))
        w.writeheader()
        w.writerows(tagged)
    mech = [t for t in tagged if t["theme"] in MECHANICAL]
    ab = [t for t in tagged if t["kind"] == "new" and t["chain_outcome"] in ("stale-bot", "author")]
    prs_any = defaultdict(set)
    for t in tagged:
        prs_any[t["number"]].add(t["theme"] in MECHANICAL)
    cl = lambda rows: round(100 * sum(1 for t in rows if t["theme"].startswith("CHANGELOG")) / max(len(rows), 1), 1)
    pre = [t for t in tagged if (t["finding_at"] or t["created_at"]) < "2025-08-29"]
    post = [t for t in tagged if (t["finding_at"] or t["created_at"]) >= "2025-08-29"]
    print(json.dumps({"findings": len(tagged), "prs": len(prs_any),
                      "mechanical_pct": round(100 * len(mech) / len(tagged), 1),
                      "mechanical_abandoned_new_pct": round(100 * sum(t["theme"] in MECHANICAL for t in ab) / max(len(ab), 1), 1),
                      "prs_with_mechanical": sum(True in v for v in prs_any.values()),
                      "prs_only_mechanical": sum(v == {True} for v in prs_any.values()),
                      "changelog_pct_before_rubric": cl(pre), "changelog_pct_after_rubric": cl(post)}, indent=1))
    for r in rows:
        print(f"{r['findings']:6} {r['share_pct']:5}% pre {r['share_before_rubric_pct']:5} post {r['share_after_rubric_pct']:5}"
              f" {r['in_public_rubric']:6} {r['theme']}")


if __name__ == "__main__":
    main()
