"""Snapshot every Raycast Store listing (downloads, contributors) to data/store_listings.json.

Uses the public endpoint the Store website itself calls. Sequential, one page at a time.
"""
import json, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL = "https://www.raycast.com/api/v1/store_listings?page={}&per_page=100"


def get(page):
    req = urllib.request.Request(URL.format(page), headers={"User-Agent": "raycast-pr-research (personal analysis)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["data"]


def slim(x):
    folder = (x.get("relative_path") or "").rstrip("/").split("/")[-1]
    return {"name": x["name"], "folder": folder, "title": x.get("title"), "owner": (x.get("owner") or {}).get("handle"),
            "author": (x.get("author") or {}).get("handle"), "downloads": x.get("download_count") or 0,
            "created_at": x.get("created_at"), "updated_at": x.get("updated_at"), "status": x.get("status"),
            "platforms": x.get("platforms"), "categories": x.get("categories"),
            "contributors": [c.get("handle") for c in x.get("contributors") or []],
            "past_contributors": [c.get("handle") for c in x.get("past_contributors") or []],
            "store_url": x.get("store_url"), "has_mcp": x.get("has_mcp"), "tools": len(x.get("tools") or [])}


def main():
    out, page = [], 1
    while True:
        rows = get(page)
        if not rows:
            break
        out += [slim(x) for x in rows]
        print(f"page {page}: {len(out)} listings", flush=True)
        page += 1
        time.sleep(0.5)
    snap = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "listings": out}
    (ROOT / "data" / "store_listings.json").write_text(json.dumps(snap))
    print(len(out), "listings")


if __name__ == "__main__":
    main()
