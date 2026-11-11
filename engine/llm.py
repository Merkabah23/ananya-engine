"""Model calls through the Claude Code CLI, so the engine runs on a Claude subscription.

Auth: CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`). ANTHROPIC_API_KEY is removed
from the child environment on purpose: if present it would take precedence and bill the API.
Each call is a fresh, tool-less (or WebSearch-only) session with our own system prompt.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

from . import config
from .state import append_jsonl, month_calls

SYSTEM = ("You are part of an editorial team for an Instagram account. Follow the instructions in the user "
          "message exactly. When asked for JSON, reply with one JSON object and nothing else.")


def fill(template: str, **values: Any) -> str:
    """Replace {key} placeholders without tripping over literal JSON braces."""
    for k, v in values.items():
        template = template.replace("{" + k + "}", v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, indent=1))
    return template


def prompt(name: str) -> str:
    return (config.PROMPTS / f"{name}.md").read_text()


def call(model: str, user: str, *, stage: str = "", tools: list | None = None, timeout: int = 900,
         retries: int = 3, **_ignored: Any) -> str:
    """Run one headless Claude Code turn and return its text result."""
    if month_calls() >= config.MAX_CALLS_PER_MONTH:
        raise SystemExit(f"Monthly cap of {config.MAX_CALLS_PER_MONTH} model calls reached; stopping.")
    cmd = [config.CLAUDE_BIN, "-p", "--output-format", "json", "--model", model,
           "--system-prompt", SYSTEM, "--no-session-persistence",
           "--tools", ",".join(tools or []) or ""]
    if tools:
        cmd += ["--allowedTools", ",".join(tools), "--permission-mode", "dontAsk"]
    child_env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    last = ""
    for attempt in range(retries):
        started = time.time()
        proc = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=timeout, env=child_env)
        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError:
            out = {"is_error": True, "result": (proc.stdout or proc.stderr)[-500:]}
        append_jsonl("calls.jsonl", {
            "at": datetime.now(timezone.utc).isoformat(), "stage": stage, "model": model,
            "ok": not out.get("is_error"), "secs": round(time.time() - started, 1),
            "notional_usd": out.get("total_cost_usd"),
        })
        if proc.returncode == 0 and not out.get("is_error"):
            return out.get("result", "")
        last = str(out.get("result", ""))[:300]
        if re.search(r"usage limit|rate limit|limit reached|session limit|hit your .{0,20}limit", last, re.I):
            raise SystemExit(f"Subscription usage limit hit during {stage}; the next scheduled run will continue. ({last})")
        time.sleep(20 * (attempt + 1))
    raise RuntimeError(f"Claude call failed after {retries} attempts in {stage}: {last}")


def parse_json(text: str) -> Any:
    """Pull the outermost JSON object out of a model reply (tolerates ```json fences)."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"No JSON object in reply: {text[:300]}")
    return json.loads(m.group(0))


def call_json(model: str, user: str, **kw: Any) -> Any:
    reply = call(model, user, **kw)
    try:
        return parse_json(reply)
    except (ValueError, json.JSONDecodeError) as e:
        # Reformat the reply we already have instead of redoing the work (and any web searches).
        kw = {k: v for k, v in kw.items() if k != "tools"}
        for model_fix in (config.MODEL_FAST, config.MODEL_JUDGE):
            fixed = call(model_fix, "Convert the reply below into the single JSON object it was supposed to be, keeping all "
                         "of its content. Escape any double quotes inside string values. Return only the JSON object.\n\n"
                         f"Error: {e}\n\nReply:\n{reply}", **kw)
            try:
                return parse_json(fixed)
            except (ValueError, json.JSONDecodeError) as e2:
                e = e2
        raise ValueError(f"Reply could not be repaired into JSON: {e}")


def pmap(fn, items: list, workers: int | None = None) -> list:
    """Run fn over items in parallel (each call is its own CLI process), keeping order.
    An item whose call raises yields the exception object instead of a result."""
    from concurrent.futures import ThreadPoolExecutor
    workers = workers or config.PARALLEL
    def safe(x):
        try:
            return fn(x)
        except SystemExit:
            raise
        except Exception as e:  # noqa: BLE001 - reported per item
            return e
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        return list(ex.map(safe, items))


def web_search_tool(max_uses: int = 5) -> str:
    """Name of the Claude Code tool to allow for calls that need the web."""
    return "WebSearch"
