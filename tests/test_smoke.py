"""End-to-end wiring with a fake LLM: candidates -> filter -> write/critic -> render -> 'upload' (dry run)."""
import os

os.environ["DRY_RUN"] = "true"

from engine import __main__ as cli, config, filter as topic_filter, llm, state  # noqa: E402

SLIDES = [
    ["Gill is No. 1 now. Half the group chat went quiet.", "Swipe to read →"],
    ["Fans picked a side within an hour of the rankings coming out.", "Fans didn't want to say the old king was slipping, so they argued about strike rates instead."],
    ["This generation grew up with one hero on every poster and every phone wallpaper.", "Letting go of him feels like getting old, and arguing about stats is easier than saying that."],
    ["Look at the comments under any highlight clip. Half of them are about the old numbers, not the match that just happened.", "Nobody says it, but everyone can feel it."],
    ["It is not really about cricket. It is about admitting that the years you spent watching him are now behind you, and that he is not twenty-five anymore."],
    ["So the group chat stays quiet for a day or two. Then someone posts a silly meme, and everyone starts arguing again."],
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
                "scores": {k: 5 for k in ("hook", "new_to_reader", "pull", "because", "payoff", "voice")}}
    if stage == "ledger":
        return {"claims": []}
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
        if stage == "scout-research":
            return {"topics": [{"claim": "evergreen claim", "territory": "life_relationships", **whole}]}
        if stage == "evidence-match":
            return {"matches": [{"topic": 1, "threads": [2, 99]}]}
        if stage == "evidence-details":
            return {"topics": [{"topic": 1, "real_details": ["someone said x"]}]}
        raise AssertionError(stage)

    monkeypatch.setattr(llm, "call_json", fake)
    topics = scout.run("2026-10")
    assert [t["claim"] for t in topics] == ["news claim", "evergreen claim"]
    assert [t["id"] for t in topics] == ["2026-10-001", "2026-10-002"]
    evergreen = topics[1]
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
    cli.verdict("approve", "2026-11-01", "named thing, sharp")
    cli.verdict("reject", "2026-11-02", "sociology essay")
    t = json.loads((data / "taste.json").read_text())
    assert t["approved"][-1]["take"] == "a good take" and t["rejected"][-1]["why"] == "sociology essay"
    bank = json.loads((data / "approved_posts.json").read_text())
    assert bank[-1]["slides"] == ["one\ntwo", "three"]


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
    state.save_post({"id": "2026-11-01", "status": "approved", "due": "2026-11-02T19:30:00+05:30", "format": "carousel",
                     "topic": {"claim": "x"}, "draft": draft, "history": []})
    cli.produce("2026-11")
    assert state.posts("uploaded")[0]["id"] == "2026-11-01" and stages == ["ledger"]


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
