"""End-to-end wiring with a fake LLM: candidates -> filter -> write/critic -> render -> 'upload' (dry run)."""
import os
import pytest

os.environ["DRY_RUN"] = "true"

from engine import __main__ as cli, config, filter as topic_filter, llm, state, writer  # noqa: E402

SLIDES = [
    ["Gill is No. 1 now. Half the group chat went quiet.", "Swipe to read →"],
    ["Fans picked a side.", "Nobody wanted to say the old king was slipping, so they argued strike rates."],
    ["This generation grew up with one hero on every poster and every phone wallpaper.", "Now he's slipping."],
    ["Read the comments.", "Half are about the old numbers, not the match on Sunday night. The other half are screenshots of a 2016 scorecard, posted like evidence in court."],
    ["It's not cricket. It is about the years you spent watching him, the exams you skipped for a Test match, now behind you."],
    ["The posters came down one by one. The wallpapers changed. The arguments stayed exactly the same, just louder.",
     "Every fan has a version of the same defence ready."],
    ["And underneath the stats is something simpler. You were fourteen when he scored that hundred, and you still remember the room."],
    ["So the chat stays quiet for a day, maybe two, while everyone pretends to be busy at work.", "Then someone posts a meme. Everyone argues again."],
]


def fake_call_json(model, user, stage="", **kw):
    if stage == "select":
        import re
        ids = re.findall(r'"id": "([^"]+)"', user)
        return {"picks": [{"id": i, "why": "fits the taste", "format_fit": "either"} for i in ids]}
    if stage == "factcheck":
        return {"unsupported": []}
    if stage == "seen-check":
        return {"verdicts": []}
    if stage == "write":
        slides = SLIDES[:1] if "a single slide of 30-70 words" in user else SLIDES
        return {"slides": [{"paragraphs": p, "why_swipe": "what happens next"} for p in slides], "caption": "Which room was off-limits?",
                "cover": {"headline": "Gill is No. 1 and the [group chat] went quiet", "sub": "s"},
                "alt_text": "A text post", "claims": []}
    if stage == "critic":
        return {"pass": True, "violations": [], "notes": [],
                "scores": {k: 5 for k in ("hook", "relatable", "fresh_angle", "pull", "payoff", "voice", "eq", "iq", "story", "tight")}}
    if stage == "varun":
        return {"pass": True, "score": 5, "misses": [], "best": "Half the group chat went quiet."}
    if stage == "ledger":
        return {"claims": []}
    if stage == "sources":
        return {"sources": []}
    if stage == "repeat-check":
        return {"repeat": False, "of": "", "shared": ""}
    if stage == "blindtest":
        return {"ai_post": 99, "confidence": 0.3, "tells": []}  # judge fails to spot it
    raise AssertionError(stage)


def test_month_end_to_end(tmp_path, monkeypatch):
    # a month far ahead: the planner skips days already gone, so a near date breaks the test once it passes
    monkeypatch.setattr(config, "STATE", tmp_path / "state")
    monkeypatch.setattr(config, "OUT", tmp_path / "out")
    monkeypatch.setattr(llm, "call_json", fake_call_json)
    monkeypatch.setattr(config, "OUTPUT", "carousel")  # the reel step has its own test; ffmpeg per post is slow here
    territories = list(config.TERRITORY_MIX)
    cands = [{"id": f"2099-10-{i:03d}", "title": f"t{i}", "claim": f"claim {i}", "behaviour": "b", "mechanism": "m",
              "group": "g", "territory": territories[i % 5], "real_details": ["d"], "evidence": [], "needs_facts": False}
             for i in range(30)]
    state.write(cands, "2099-10", "candidates.json")
    plan = topic_filter.run("2099-10", "2099-11")
    n = len(topic_filter.slots_for_month("2099-11"))
    assert n == 21  # Monday to Friday
    assert len([p for p in plan if p["due"]]) == n
    cli.produce("2099-11")
    done = state.posts("uploaded")
    assert len(done) == n
    assert all(1 <= len(p["image_urls"]) <= 10 for p in done)
    assert (tmp_path / "out" / done[0]["id"] / "slide_01.jpg").exists()


def test_scout_is_culture_first_and_uses_reddit_as_evidence(tmp_path, monkeypatch):
    from engine import scout
    monkeypatch.setattr(config, "STATE", tmp_path / "state")
    news = [{"source": "news", "title": f"item {i}", "url": f"https://news.example/{i}", "body": "b"} for i in range(3)]
    reddit = [{"id": f"r{i}", "sub": "india", "rank": i + 1, "title": f"thread {i}", "body": "people talk",
               "url": f"https://www.reddit.com/r/india/comments/r{i}/x/", "top_comments": ["c1", "c2"]} for i in range(5)]
    monkeypatch.setattr(scout, "_fetch_news", lambda: news)
    monkeypatch.setattr(scout, "fetch_reddit", lambda month=None: reddit)
    seen = []

    whole = {"moment": "m", "because": "b", "turn": {"believed": "x", "actually": "y"}}
    proof = [{"fact": "f", "source_url": "https://news.example/0", "date": "2026-10-01"}]

    def fake(model, user, stage="", **kw):
        seen.append(stage)
        if stage == "scout":
            assert "reddit.com" not in user  # Reddit never feeds topic creation
            return {"topics": [{"claim": "news claim", "real_details": ["a fact"], "territory": "money_status", "proof": proof,
                                "evidence": [{"url": "https://news.example/0"}], **whole},
                               {"claim": "money claim without proof", "territory": "money_status", **whole},
                               {"claim": "recognition only", "territory": "life_relationships"}]}
        if stage == "scout-evergreen":
            return {"topics": [{"claim": "evergreen claim", "territory": "life_relationships", **whole}]}
        if stage == "evidence-match":
            return {"matches": [{"topic": 2, "threads": [2, 99]}]}
        if stage == "evidence-details":
            return {"topics": [{"topic": 2, "real_details": ["someone said x"]}]}
        raise AssertionError(stage)

    monkeypatch.setattr(llm, "call_json", fake)
    topics = scout.run("2026-10")
    # facts are never required; a take with no turn or because is dropped
    assert [t["claim"] for t in topics] == ["news claim", "money claim without proof", "evergreen claim"]
    ids = [t["id"] for t in topics]
    assert len(set(ids)) == 3 and all(i.startswith("2026-10-") and i.endswith(f"-00{n}") for n, i in enumerate(ids, 1))
    evergreen = topics[2]
    assert evergreen["news_peg"] is None
    assert evergreen["real_details"] == ["someone said x"]
    assert evergreen["evidence"] == [{"url": reddit[2]["url"], "sub": "india", "rank": 3}]  # out-of-range id 99 dropped
    assert topics[0]["real_details"] == ["a fact"] and "evidence-details" in seen


def test_approve_and_reject_teach_the_engine(tmp_path, monkeypatch):
    import json, shutil
    data = tmp_path / "data"
    shutil.copytree(config.DATA, data)
    monkeypatch.setattr(config, "DATA", data)
    monkeypatch.setattr(config, "STATE", tmp_path / "state")
    draft = {"slides": [{"paragraphs": ["one", "two"]}, {"paragraphs": ["three"]}]}
    state.save_post({"id": "2026-11-01", "status": "written", "topic": {"claim": "a good take", "title": "good"}, "draft": draft})
    state.save_post({"id": "2026-11-02", "status": "written", "topic": {"claim": "a bad take"}, "draft": draft})
    with pytest.raises(SystemExit, match="Varun check"):  # no Varun pass on this text yet
        cli.verdict("approve", "2026-11-01", "named thing, sharp")
    post = state.read("posts", "2026-11-01.json")
    post["varun"] = writer.varun_stamp({"pass": True, "score": 5, "misses": []}, draft)
    state.save_post(post)
    cli.verdict("approve", "2026-11-01", "named thing, sharp")
    cli.verdict("reject", "2026-11-02", "sociology essay")
    t = json.loads((data / "taste.json").read_text())
    assert t["approved"][-1]["take"] == "a good take" and t["rejected"][-1]["why"] == "sociology essay"
    bank = json.loads((data / "approved_posts.json").read_text())
    assert bank[-1]["slides"] == ["one\ntwo", "three"]
    post["draft"] = {"slides": [{"paragraphs": ["edited after the check"]}]}
    state.save_post(post)
    assert not writer.varun_valid(post)  # any edit needs a fresh check


def test_owner_approved_drafts_skip_the_writer_but_not_the_fact_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE", tmp_path / "state")
    monkeypatch.setattr(config, "OUT", tmp_path / "out")
    stages = []
    def gate_only(model, user, stage="", **kw):
        stages.append(stage)
        if stage == "ledger":
            return {"claims": []}
        raise AssertionError("an approved draft must not be rewritten")
    monkeypatch.setattr(llm, "call_json", gate_only)
    draft = {"slides": [{"paragraphs": p} for p in SLIDES], "caption": "c", "alt_text": "a", "claims": []}
    state.save_post({"id": "2099-11-01", "status": "approved", "due": "2099-11-02T19:30:00+05:30", "format": "carousel",
                     "topic": {"claim": "x"}, "draft": draft, "history": []})
    cli.produce("2099-11")
    assert state.posts("uploaded")[0]["id"] == "2099-11-01" and stages == ["ledger"]


def test_scorecard_rows_and_per_thousand(tmp_path, monkeypatch):
    from engine import scorecard
    monkeypatch.setattr(config, "STATE", tmp_path / "state")
    monkeypatch.setattr(scorecard, "PATH", tmp_path / "scorecard.csv")
    draft = {"slides": [{"paragraphs": ["A hook", "Swipe to read →"]}], "hook_type": "rant", "caption_style": "pov"}
    state.save_post({"id": "2026-10-23x", "status": "scheduled", "due": "2026-10-23T19:30:00+05:30", "format": "carousel",
                     "topic": {"claim": "x", "format_name": "price_tells"}, "draft": draft, "history": []})
    rows = scorecard.sync()
    assert rows[0]["format"] == "price_tells" and rows[0]["test"] == "baseline"
    rows[0].update(reached="2000", shares="30", saves="10", follows="4", non_follower_pct="60")
    scorecard.write(rows)
    assert scorecard.per_k(scorecard.read()[0], "shares") == 15.0
    assert "1 of 1 posts have numbers" in scorecard.summary()
