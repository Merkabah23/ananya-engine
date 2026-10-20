"""State lives as JSON files in state/, committed back to the repo by the workflow.

Layout:
  state/<YYYY-MM>/candidates.json   scout output
  state/<YYYY-MM>/plan.json         filter output: chosen topics with slot dates
  state/posts/<post_id>.json        one file per post, carries its status through the pipeline
  state/calls.jsonl                 every model call (subscription usage)
  state/log.jsonl                   every stage event
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config

STATUSES = ["planned", "written", "rejected", "rendered", "uploaded", "scheduled", "failed"]


def path(*parts: str) -> Path:
    p = config.STATE.joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def read(*parts: str, default: Any = None) -> Any:
    p = path(*parts)
    return json.loads(p.read_text()) if p.exists() else default


def write(data: Any, *parts: str) -> None:
    p = path(*parts)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    tmp.replace(p)


_lock = threading.Lock()


def append_jsonl(name: str, row: dict) -> None:
    with _lock, path(name).open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def log(stage: str, msg: str, **extra: Any) -> None:
    row = {"at": datetime.now(timezone.utc).isoformat(), "stage": stage, "msg": msg, **extra}
    append_jsonl("log.jsonl", row)
    print(f"[{stage}] {msg}", flush=True)


def month_calls(month: str | None = None) -> int:
    month = month or datetime.now(timezone.utc).strftime("%Y-%m")
    p = path("calls.jsonl")
    if not p.exists():
        return 0
    return sum(1 for line in p.read_text().splitlines() if f'"at": "{month}' in line)


def posts(status: str | None = None) -> list[dict]:
    d = path("posts", "x").parent
    out = [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))]
    return [p for p in out if status is None or p["status"] == status]


def save_post(post: dict) -> None:
    assert post["status"] in STATUSES, post["status"]
    post["updated_at"] = datetime.now(timezone.utc).isoformat()
    write(post, "posts", f"{post['id']}.json")
