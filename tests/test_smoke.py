"""End-to-end wiring with a fake LLM: candidates -> filter -> write/critic -> render -> 'upload' (dry run)."""
import os

os.environ["DRY_RUN"] = "true"

from engine import __main__ as cli, config, filter as topic_filter, llm, state  # noqa: E402

SLIDES = [
    ["Gill is No. 1 now. Half the group chat went quiet.", "Swipe to read →"],
    ["Fans picked a side within an hour.", "Nobody wanted to say the old king was slipping."],
    ["We grew up with one hero. Letting go feels like getting old.", "So we argue about stats instead."],
    ["The quiet half is not angry.", "They are just not ready to switch posters."],
    ["Every fan base goes through this once.", "Ours is going through it now."],
]


def fake_call_json(model, user, stage="", **kw):
    if stage == "filter":
        import json, re
        ids = re.findall(r'"id": "([^"]+)"', user)
        return {"scores": [{"id": i, "mirror": 5, "group": 4, "arguable": 4, "emotion": 4, "send_to": 4, "fresh": 5,
                            "reddit_signal": 3, "reject": False, "reason": "ok", "best_hook": "x",
                            "format_fit": "either"} for i in ids]}
    if stage == "factcheck":
        return {"unsupported": []}
    if stage == "seen-check":
        return {"verdicts": []}
    if stage == "write":
        slides = SLIDES[:1] if "a single slide of at most 110 words" in user else SLIDES
        return {"slides": [{"paragraphs": p} for p in slides], "caption": "Which room was off-limits?",
                "alt_text": "A text post", "claims": []}
    if stage == "critic":
        return {"pass": True, "violations": [], "scores": {}, "edits": []}
    if stage == "blindtest":
        return {"ai_post": 99, "confidence": 0.3, "tells": []}  # judge fails to spot it
    raise AssertionError(stage)


def test_month_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE", tmp_path / "state")
    monkeypatch.setattr(config, "OUT", tmp_path / "out")
    monkeypatch.setattr(llm, "call_json", fake_call_json)
    territories = list(config.TERRITORY_MIX)
    cands = [{"id": f"2026-10-{i:03d}", "title": f"t{i}", "claim": f"claim {i}", "behaviour": "b", "mechanism": "m",
              "group": "g", "territory": territories[i % 5], "real_details": ["d"], "evidence": [], "needs_facts": False}
             for i in range(30)]
    state.write(cands, "2026-10", "candidates.json")
    plan = topic_filter.run("2026-10", "2026-11")
    assert len([p for p in plan if p["due"]]) == 17
    cli.produce("2026-11")
    done = state.posts("uploaded")
    assert len(done) == 17
    assert all(len(p["image_urls"]) in (1, 5, 6, 7) for p in done)
    assert (tmp_path / "out" / done[0]["id"] / "slide_01.jpg").exists()
