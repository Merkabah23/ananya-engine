"""Command line for the engine.

  python -m engine monthly            scout -> filter -> produce next month's posts
  python -m engine push               schedule the next 8 days of ready posts in Buffer
  python -m engine scout|filter|produce|calibrate|status|buffer-channels
  python -m engine approve|reject <post_id> --why "..."   teach the engine your taste
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone

from . import buffer, config, filter as topic_filter, llm, render, scout, state, storage, writer


def _month(offset: int = 0) -> str:
    d = datetime.now(timezone.utc).replace(day=1)
    y, m = d.year, d.month + offset
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    return f"{y}-{m:02d}"


def _take_spare(slot_post: dict) -> dict | None:
    """Move a spare topic into a slot whose draft was rejected."""
    month = slot_post["id"][:7]
    for p in state.posts("planned"):
        if p["format"] == "spare" and p["id"].startswith(month):
            p.update(due=slot_post["due"], format=slot_post["format"] if slot_post["format"] != "spare" else "carousel")
            state.save_post(p)
            state.log("produce", f"{p['id']} replaces rejected {slot_post['id']}")
            return p
    return None


def produce(month: str | None = None, limit: int | None = None) -> None:
    """Write, render and upload planned posts, soonest first. `limit` keeps each run inside
    subscription usage windows; the daily run calls this with PRODUCE_PER_RUN."""
    soon = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    queue = [p for p in state.posts("planned") + state.posts("approved") if p["format"] != "spare" and p.get("due")
             and datetime.fromisoformat(p["due"]).astimezone(timezone.utc).isoformat() > soon  # skip missed slots
             and (month is None or p["id"].startswith(month))]
    queue.sort(key=lambda p: p["due"])
    # Owner-approved drafts cost no model calls, so they render without using up the per-run writing limit.
    ready, queue = [p for p in queue if p["status"] == "approved"], [p for p in queue if p["status"] != "approved"]
    attempts = 0
    while ready or (queue and (limit is None or attempts < limit)):
        room = config.PARALLEL if limit is None else min(config.PARALLEL, limit - attempts)
        batch, queue = queue[:room], queue[room:]
        attempts += len(batch)
        batch, ready = ready + batch, []
        # Drafts the owner already approved skip the writer and go straight to rendering.
        results = llm.pmap(lambda p: p if p["status"] == "approved" else writer.write_post(p), batch)
        for post, result in zip(batch, results):
            try:
                if isinstance(result, Exception):
                    raise result
                post = result
                state.save_post(post)
                if post["status"] == "rejected":
                    spare = _take_spare(post)
                    if spare:
                        queue.append(spare)
                    continue
                paths = render.render_post(post)
                post["image_urls"] = [storage.upload(p, f"{post['id']}/{p.name}") for p in paths]
                post["status"] = "uploaded"
                state.save_post(post)
                state.log("produce", f"{post['id']} ready: {len(paths)} slides, due {post['due']}")
            except Exception as e:  # one bad post must not stop the month
                post["status"], post["error"] = "failed", str(e)[:500]
                state.save_post(post)
                state.log("produce", f"{post['id']} failed: {e}")


def sample(n: int, topics_file: str | None) -> None:
    """Tuning mode: write n posts from saved topics (no scouting), render them into samples/. Uploads nothing."""
    import shutil
    config.DRY_RUN = True
    if topics_file:
        topics = json.loads(open(topics_file).read())
    else:
        topics = [p["topic"] for p in state.posts("planned")]
    posts = [{"id": f"sample-{t.get('id', i)}", "status": "planned", "due": None, "format": "carousel",
              "topic": t, "history": [], "sources": t.get("_sources")} for i, t in enumerate(topics[:n])]
    out_root = config.ROOT / "samples"
    for post in llm.pmap(writer.write_post, posts):
        if isinstance(post, Exception):
            print("failed:", post)
            continue
        print(f"\n=== {post['id']}: {post['status']} | {post['topic'].get('claim', '')[:90]}")
        if post["status"] != "written":
            print("   last problems:", (post["history"] or [{}])[-1])
            continue
        for i, s in enumerate(post["draft"]["slides"], 1):
            print(f"   [{i}] " + " / ".join(s["paragraphs"]))
        dest = out_root / post["id"]
        dest.mkdir(parents=True, exist_ok=True)
        for path in render.render_post(post):
            shutil.copy(path, dest / path.name)
        (dest / "post.json").write_text(json.dumps(post, ensure_ascii=False, indent=1))
        print("   saved:", dest)


def push(days: int = 8) -> None:
    if config.PAUSED:
        state.log("push", "ENGINE_PAUSED is set; nothing scheduled.")
        return
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=days)
    for post in state.posts("uploaded"):
        due = datetime.fromisoformat(post["due"]) if post.get("due") else None
        if not due or not (now + timedelta(hours=1) <= due <= horizon):
            continue
        if post.get("buffer_attempted_at") and not post.get("buffer_post_id"):
            # A previous attempt may have reached Buffer without us hearing back. Never retry blind.
            post["status"], post["error"] = "failed", "Earlier Buffer call had no confirmed result; check the Buffer queue, then reset status to 'uploaded'."
            state.save_post(post)
            state.log("push", f"{post['id']} needs a manual check in Buffer")
            continue
        post["buffer_attempted_at"] = now.isoformat()
        state.save_post(post)
        try:
            post["buffer_post_id"] = buffer.schedule(post)
            post["status"] = "scheduled"
            state.log("push", f"{post['id']} scheduled in Buffer for {post['due']}")
        except Exception as e:
            post["status"], post["error"] = "failed", str(e)[:500]
            state.log("push", f"{post['id']} failed: {e}")
        state.save_post(post)


def status() -> None:
    rows = state.posts()
    counts: dict[str, int] = {}
    for p in rows:
        counts[p["status"]] = counts.get(p["status"], 0) + 1
    print(json.dumps({"by_status": counts, "model_calls_this_month": state.month_calls(),
                      "cap": config.MAX_CALLS_PER_MONTH}, indent=1))
    for p in rows[-25:]:
        print(f"{p['id']}  {p['status']:<10} {str(p.get('due'))[:16]:<16}  {p['topic'].get('claim', '')[:70]}")


def verdict(kind: str, post_id: str | None, why: str) -> None:
    """Teach the engine the owner's taste: the take goes into data/taste.json, an approved draft into the example bank."""
    if not post_id:
        raise SystemExit(f"Usage: python -m engine {kind} <post_id> --why \"...\"")
    post = state.read("posts", f"{post_id}.json")
    if not post:
        raise SystemExit(f"No post {post_id}")
    if kind == "reject" and not why:
        raise SystemExit("Say why with --why: the reason is what the engine learns from.")
    path = config.DATA / "taste.json"
    t = json.loads(path.read_text())
    t["approved" if kind == "approve" else "rejected"].append(
        {"take": post["topic"]["claim"], "why": why or "Approved by the owner.", "post": post_id})
    path.write_text(json.dumps(t, ensure_ascii=False, indent=1) + "\n")
    if kind == "approve" and post.get("draft"):
        bank_path = config.DATA / "approved_posts.json"
        bank = json.loads(bank_path.read_text())
        if all(b.get("post") != post_id for b in bank):
            bank.append({"title": post["topic"].get("title") or post["topic"]["claim"][:60], "post": post_id,
                         "territory": post["topic"].get("territory"), "mood": post["topic"].get("mood"),
                         "slides": ["\n".join(s["paragraphs"]) for s in post["draft"]["slides"]]})
            bank_path.write_text(json.dumps(bank, ensure_ascii=False, indent=1) + "\n")
    state.log("taste", f"{kind} {post_id}: {why}")
    print(f"{kind}d {post_id}; the engine will use this from the next run.")


def doctor() -> None:
    """Check every key and connection before the first real run. Prints one line per check."""
    import requests
    ok = True
    def check(name: str, fn) -> None:
        nonlocal ok
        try:
            print(f"OK    {name}: {fn()}")
        except BaseException as e:  # noqa: BLE001 - report everything, including SystemExit
            ok = False
            print(f"FAIL  {name}: {e}")
    def avatar():
        if not (config.ASSETS / "avatar.png").exists():
            raise FileNotFoundError("add assets/avatar.png")
        return "assets/avatar.png present"
    check("avatar", avatar)
    check("claude subscription", lambda: llm.call(config.MODEL_FAST, "Reply with the word ready.", stage="doctor")[:40])
    check("buffer channel", lambda: buffer.channel_id())
    def media():
        repo, tok = config.env("MEDIA_REPO"), config.env("MEDIA_REPO_TOKEN")
        r = requests.get(f"https://api.github.com/repos/{repo}", headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        r.raise_for_status()
        info = r.json()
        if info.get("private"):
            raise RuntimeError(f"{repo} is private; slides must be public for Buffer to fetch them")
        if not info.get("permissions", {}).get("push"):
            raise RuntimeError("token cannot write to the media repo")
        return f"{repo} is public and writable"
    check("media repo", media)
    check("reddit feed", lambda: f"{len(scout.Reddit().top_threads('india', 5))} threads readable")
    print("\nAll checks passed." if ok else "\nFix the FAIL lines above, then run doctor again.")
    if not ok:
        raise SystemExit(1)


def main() -> None:
    ap = argparse.ArgumentParser(prog="engine")
    ap.add_argument("command", choices=["monthly", "daily", "fetch-reddit", "scout", "filter", "produce", "push",
                                        "sample", "calibrate", "status", "buffer-channels", "doctor", "approve", "reject"])
    ap.add_argument("post_id", nargs="?", help="approve/reject: the post id, e.g. 2026-11-03")
    ap.add_argument("--why", default="", help="approve/reject: one line on why, in your own words")
    ap.add_argument("--n", type=int, default=3, help="sample: how many posts")
    ap.add_argument("--topics", help="sample: JSON file of topics to write from")
    ap.add_argument("--month", help="YYYY-MM; defaults depend on the command")
    ap.add_argument("--plan-month", help="YYYY-MM to plan posts for (filter); defaults to the month after --month")
    ap.add_argument("--days", type=int, default=8)
    a = ap.parse_args()
    if a.command == "monthly":      # 20th: scout + plan next month (writing happens daily)
        scout.run(_month(0))
        topic_filter.run(_month(0), _month(1))
    elif a.command == "daily":      # every day: write a few posts, then schedule what's due soon
        produce(limit=config.PRODUCE_PER_RUN)
        push(a.days)
    elif a.command == "fetch-reddit":  # 19th: the slow, rate-limited part, so the monthly run never waits on it
        scout.fetch_reddit(_month(0))
    elif a.command == "sample":
        sample(a.n, a.topics)
    elif a.command == "scout":
        scout.run(a.month or _month(0))
    elif a.command == "filter":
        topic_filter.run(a.month or _month(0), a.plan_month)
    elif a.command == "produce":
        produce(a.month)
    elif a.command == "push":
        push(a.days)
    elif a.command in ("approve", "reject"):
        verdict(a.command, a.post_id, a.why)
    elif a.command == "calibrate":
        print(json.dumps(topic_filter.calibrate(), indent=1))
    elif a.command == "status":
        status()
    elif a.command == "doctor":
        doctor()
    elif a.command == "buffer-channels":
        for ch in buffer.list_channels():
            print(f"{ch['service']:<12} {ch['name']:<30} {ch['id']}  ({ch['organization']})")


if __name__ == "__main__":
    main()
