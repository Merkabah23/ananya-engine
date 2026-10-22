"""The scorecard: one row per post, Insights numbers typed in by the owner, compared with the account's own median.

The owner fills reached, non_follower_pct, shares, saves, follows (and comments) from Instagram Insights at 7 days.
Everything else is filled from the post itself.
"""
from __future__ import annotations

import csv
import statistics
from datetime import datetime, timezone

from . import config, state

PATH = config.STATE / "scorecard.csv"  # under state/ so the workflow commits it
FIELDS = ["post", "due", "format", "hook_type", "caption_style", "test", "title",
          "reached", "non_follower_pct", "shares", "saves", "follows", "comments", "decision"]
NUMBERS = ["reached", "non_follower_pct", "shares", "saves", "follows", "comments"]
PRIMARY = {"price_tells": "shares", "family_ledger": "shares", "feed_anthropology": "shares",
           "behind_the_brand": "saves", "saturday_single": "comments"}

WEEK_TESTS = [  # (first due date of the week, the one thing being tested); see the growth playbook
    ("2026-10-21", "baseline"), ("2026-10-29", "caption shape"), ("2026-11-07", "end card follow line"),
    ("2026-11-14", "cover size"),
]


def _test_for(due: str) -> str:
    current = ""
    for start, name in WEEK_TESTS:
        if due[:10] >= start:
            current = name
    return current


def read() -> list[dict]:
    if not PATH.exists():
        return []
    with PATH.open(newline="") as f:
        return list(csv.DictReader(f))


def write(rows: list[dict]) -> None:
    with PATH.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in sorted(rows, key=lambda r: r.get("due", "")):
            w.writerow({k: r.get(k, "") for k in FIELDS})


def sync() -> list[dict]:
    """Add a row for every post sent to Buffer, keeping any numbers already typed in."""
    rows = {r["post"]: r for r in read()}
    for p in state.posts():
        if p["status"] != "scheduled" or not p.get("draft") or p["id"] in rows:
            continue
        rows[p["id"]] = {"post": p["id"], "due": p["due"][:10], "format": p["topic"].get("format_name", ""),
                         "hook_type": p["draft"].get("hook_type", ""), "caption_style": p["draft"].get("caption_style", ""),
                         "test": _test_for(p["due"]), "title": p["draft"]["slides"][0]["paragraphs"][0][:70]}
    out = list(rows.values())
    write(out)
    return out


def _num(v: str) -> float | None:
    try:
        return float(str(v).replace(",", "").replace("%", ""))
    except ValueError:
        return None


def per_k(row: dict, field: str) -> float | None:
    reached, n = _num(row.get("reached", "")), _num(row.get(field, ""))
    return round(n / reached * 1000, 1) if reached and n is not None else None


def missing(rows: list[dict] | None = None) -> list[dict]:
    """Posts already published (due more than 7 days ago) with no numbers yet."""
    now = datetime.now(timezone.utc).date().isoformat()
    week_ago = datetime.fromordinal(datetime.fromisoformat(now).toordinal() - 7).date().isoformat()
    return [r for r in (rows if rows is not None else read()) if r.get("due", "") <= week_ago and not r.get("reached")]


def summary() -> str:
    rows = sync()
    filled = [r for r in rows if _num(r.get("reached", ""))]
    lines = [f"{len(filled)} of {len(rows)} posts have numbers."]
    if missing(rows):
        lines.append("Needs numbers from Insights (7 days old): " + ", ".join(r["post"] for r in missing(rows)))
    if not filled:
        return "\n".join(lines)
    med = {f: statistics.median([v for r in filled if (v := per_k(r, f)) is not None] or [0]) for f in ("shares", "saves", "follows")}
    lines.append(f"Median per 1,000 reached: shares {med['shares']}, saves {med['saves']}, follows {med['follows']}")
    for r in filled:
        primary = PRIMARY.get(r.get("format", ""), "shares")
        val = per_k(r, primary) if primary != "comments" else _num(r.get("comments", ""))
        base = med.get(primary)
        flag = "promising" if base and val is not None and val >= 1.5 * base else ""
        lines.append(f"{r['post']}  {r.get('format', ''):17} {r.get('test', ''):20} shares/1k {per_k(r, 'shares')}  "
                     f"saves/1k {per_k(r, 'saves')}  follows/1k {per_k(r, 'follows')}  non-followers {r.get('non_follower_pct', '')}%  {flag}")
    return "\n".join(lines)
