"""What has gone live on the page, and the check that keeps a new post from repeating one of them."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from . import config, llm, state

LOG = config.DATA / "published.json"


def log() -> list[dict]:
    return json.loads(LOG.read_text()) if LOG.exists() else []


def _save(rows: list[dict]) -> None:
    LOG.write_text(json.dumps(sorted(rows, key=lambda r: r["date"]), ensure_ascii=False, indent=1) + "\n")


def record_live() -> list[dict]:
    """Every post the engine sent whose slot has passed is live: mark it and add it to the log, once."""
    now = datetime.now(timezone.utc)
    rows, seen, added = log(), {r.get("id") for r in log()}, []
    for p in state.posts("scheduled"):
        if not p.get("due") or datetime.fromisoformat(p["due"]) > now:
            continue
        p["status"] = "published"
        state.save_post(p)
        if p["id"] in seen:
            continue
        d = p.get("draft") or {}
        row = {"date": p["due"][:10], "id": p["id"], "headline": re.sub(r"[\[\]]", "", (d.get("cover") or {}).get("headline", "")),
               "claim": p["topic"].get("claim", ""), "subject": p["topic"].get("title", "")}
        rows.append(row); added.append(row)
    if added:
        _save(rows)
        state.log("published", f"{len(added)} post(s) live: " + "; ".join(r["headline"][:50] for r in added))
    return added


def lines() -> str:
    return "\n".join(f"- {r['date']}: {r['headline']} ({r['claim']})" for r in log()) or "(nothing live yet)"


def repeat_of(topic: dict) -> str | None:
    """The live post this topic would repeat (same take, or the same object or moment at its centre), or None."""
    if not log():
        return None
    ask = ("An Instagram page never repeats itself. Below are the posts already live, then a new topic. The new topic is a "
           "repeat if it makes the same point, or if the same object, ritual or moment sits at its centre (two posts about "
           "mummy's gold are a repeat even with different takes). A shared broad theme (parents, money) is not a repeat.\n\n"
           f"## Live posts\n{lines()}\n\n## New topic\n" + json.dumps({k: topic.get(k) for k in ("title", "claim", "moment")},
                                                                    ensure_ascii=False) +
           '\n\nOnly a clear match counts; when unsure, it is not a repeat. Return only JSON: {"repeat": true|false, '
           '"of": "the live headline it repeats, or empty", "shared": "the exact point or object both are about, or empty"}')
    out = llm.call_json(config.MODEL_JUDGE, ask, stage="repeat-check")
    return (out.get("of") or "a live post") if out.get("repeat") and (out.get("shared") or "").strip() else None
