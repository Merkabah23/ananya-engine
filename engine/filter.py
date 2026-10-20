"""Agent 2, the filter: score candidates, reject weak ones, assign the month's slots."""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone

from . import config, corpus, llm, state
from .scout import tired_tropes

IST = timezone(timedelta(hours=5, minutes=30))
CRITERIA = ["mirror", "group", "arguable", "emotion", "send_to", "fresh"]
BATCH = 15


def _our_hooks() -> str:
    return "\n".join(f"- {p['topic']['claim']}" for p in state.posts() if p.get("topic")) or "(none yet)"


def _score(topics: list[dict], calibration: bool = False) -> dict[str, dict]:
    top, bottom = corpus.calibration_examples()
    skip = "(skip this check for this run)"
    template = llm.fill(llm.prompt("filter"), top_examples=top, bottom_examples=bottom,
                        varun_hooks=skip if calibration else corpus.all_hooks(),
                        our_hooks=skip if calibration else _our_hooks(), tired_tropes=tired_tropes())
    keys = ("id", "title", "claim", "behaviour", "mechanism", "group", "territory", "news_peg", "why_now",
            "counterintuitive", "evidence")
    batches = [[{k: t.get(k) for k in keys} for t in topics[i:i + BATCH]] for i in range(0, len(topics), BATCH)]
    results = llm.pmap(lambda b: llm.call_json(
        config.MODEL_JUDGE, template + "\n\n## Candidates\n" + json.dumps(b, ensure_ascii=False, indent=1), stage="filter"), batches)
    scores: dict[str, dict] = {}
    for out in results:
        if isinstance(out, Exception):
            state.log("filter", f"a scoring batch failed: {out}")
            continue
        for s in out.get("scores", []):
            s["total"] = sum(int(s.get(c, 0)) for c in CRITERIA)
            scores[s["id"]] = s
    return scores


def _seen_check(ranked: list[dict]) -> list[dict]:
    """Drop topics whose angle has already been posted widely. Web search, 5 topics per call."""
    def check(batch: list[dict]) -> set:
        ask = ("For each claim below, search the web (Instagram, X, LinkedIn, YouTube, Reddit, news) for whether this exact angle "
               "has already been posted widely in India in the last two years. Mark seen=true ONLY if you find at least two "
               "posts or articles making essentially the same argument. A familiar topic with a new angle is NOT seen.\n\n"
               + "\n".join(f'{t["id"]}: {t["claim"]}' for t in batch) +
               '\n\nReturn only JSON: {"verdicts": [{"id": "...", "seen": true/false, "evidence": "url or one line"}]}')
        out = llm.call_json(config.MODEL_JUDGE, ask, stage="seen-check", tools=[llm.web_search_tool()], timeout=1200)
        return {v["id"] for v in out.get("verdicts", []) if v.get("seen")}
    batches = [ranked[i:i + 5] for i in range(0, len(ranked), 5)]
    fresh = []
    for batch, seen in zip(batches, llm.pmap(check, batches)):
        if isinstance(seen, Exception):
            state.log("filter", f"seen-check failed, keeping batch: {seen}")
            seen = set()
        for t in batch:
            if t["id"] in seen:
                state.log("filter", f"{t['id']} dropped as already-seen: {t['claim'][:80]}")
            else:
                fresh.append(t)
    return fresh


def slots_for_month(month: str) -> list[dict]:
    y, m = map(int, month.split("-"))
    d = date(y, m, 1)
    out = []
    while d.month == m:
        for s in config.SLOTS:
            if d.weekday() == s["weekday"]:
                hh, mm = map(int, s["time"].split(":"))
                out.append({"due": datetime.combine(d, time(hh, mm), IST).isoformat(), "format": s["format"]})
        d += timedelta(days=1)
    return out


def _assign(ranked: list[dict], slots: list[dict]) -> list[dict]:
    n = len(slots)
    quota = {t: max(1, round(w * n)) for t, w in config.TERRITORY_MIX.items()}
    used = {t: 0 for t in quota}
    plan, pool, last = [], list(ranked), None
    for slot in slots:
        def ok(t: dict, strict: bool) -> bool:
            terr = t.get("territory")
            fits = slot["format"] == "carousel" or t["score"].get("format_fit") in ("single", "either")
            if not strict:
                return fits
            return fits and terr != last and used.get(terr, 0) < quota.get(terr, 0)
        pick = next((t for t in pool if ok(t, True)), None) or next((t for t in pool if ok(t, False)), None)
        if not pick:
            break
        pool.remove(pick)
        used[pick.get("territory")] = used.get(pick.get("territory"), 0) + 1
        last = pick.get("territory")
        plan.append({**slot, "topic": pick})
    spares = pool[:config.SPARE_TOPICS]
    return plan + [{"due": None, "format": "spare", "topic": t} for t in spares]


def run(month: str, plan_month: str | None = None) -> list[dict]:
    """Score this month's candidates and plan posts for plan_month (default: next month)."""
    candidates = state.read(month, "candidates.json") or []
    if not candidates:
        raise SystemExit(f"No candidates for {month}; run the scout first.")
    scores = _score(candidates)
    kept = []
    for t in candidates:
        s = scores.get(t["id"])
        if not s or s.get("reject") or s["total"] < config.MIN_TOPIC_SCORE or int(s.get("fresh", 0)) < 4:
            continue
        kept.append({**t, "score": s})
    # Rank by editorial score, Reddit evidence as tie-breaker.
    kept.sort(key=lambda t: (t["score"]["total"], t["score"].get("reddit_signal", 0)), reverse=True)
    kept = _seen_check(kept[:len(slots_for_month(plan_month or month)) * 2])
    if plan_month is None:
        y, m = map(int, month.split("-"))
        plan_month = f"{y + (m == 12)}-{(m % 12) + 1:02d}"
    plan = _assign(kept, slots_for_month(plan_month))
    state.write(plan, plan_month, "plan.json")
    for i, item in enumerate(plan, 1):
        pid = f"{plan_month}-{i:02d}"
        if state.read("posts", f"{pid}.json"):
            continue  # idempotent: never overwrite a post already in progress
        state.save_post({"id": pid, "status": "planned", "due": item["due"], "format": item["format"],
                         "topic": item["topic"], "history": []})
    state.log("filter", f"{len(candidates)} candidates -> {len(kept)} passed -> {len(plan)} planned for {plan_month}")
    return plan


def calibrate(sample: int = 28) -> dict:
    """Does the judge rank the reference creator's top quarter above his bottom quarter, blind?"""
    top, bottom = corpus.quartiles()
    shown = {p["code"] for ps in corpus.calibration_picks() for p in ps}  # never test on the prompt's own examples
    top = [p for p in top if p["code"] not in shown]
    bottom = [p for p in bottom if p["code"] not in shown]
    items = [{"id": f"t{i}", "title": "", "claim": corpus.hook(p), "behaviour": "", "mechanism": "", "group": "",
              "territory": p["territory"], "evidence": []} for i, p in enumerate(top[:sample])]
    items += [{"id": f"b{i}", "title": "", "claim": corpus.hook(p), "behaviour": "", "mechanism": "", "group": "",
               "territory": p["territory"], "evidence": []} for i, p in enumerate(bottom[:sample])]
    scores = _score(items, calibration=True)
    t = [scores[i["id"]]["total"] for i in items if i["id"].startswith("t") and i["id"] in scores]
    b = [scores[i["id"]]["total"] for i in items if i["id"].startswith("b") and i["id"] in scores]
    pairs = [(x, y) for x in t for y in b]
    acc = sum(1.0 if x > y else 0.5 if x == y else 0.0 for x, y in pairs) / max(len(pairs), 1)
    result = {"pairwise_accuracy": round(acc, 3), "top_mean": sum(t) / max(len(t), 1), "bottom_mean": sum(b) / max(len(b), 1)}
    state.log("calibrate", json.dumps(result))
    return result
