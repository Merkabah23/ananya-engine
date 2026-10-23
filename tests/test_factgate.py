"""Regression cases for the fact gate, built from errors that nearly shipped. Web answers are stubbed."""
import os

os.environ["DRY_RUN"] = "true"

from engine import __main__ as cli, config, factgate, llm, state  # noqa: E402

DUE = "2026-10-26T19:30:00+05:30"
PRIMARY = {"url": "https://gov.example/notice", "publisher": "CBIC", "published_date": "2026-05-12", "quote": "q", "tier": 1}
AGGREGATOR = {"url": "https://blog.example/gold", "publisher": "blog", "published_date": "2026-10-19", "quote": "q", "tier": 3}
on_page = lambda url, quote: True
not_on_page = lambda url, quote: False


def claim(text, kind="figure", core=False, framed="timeless", **kw):
    return {"id": "c1", "text": text, "type": kind, "core": core, "framed_as": framed, **kw}


def verdict(kind="supported", sources=(PRIMARY,), event_date="", correct=""):
    return {"verdict": kind, "sources": list(sources), "event_date": event_date, "correct": correct}


def test_stale_news_framed_as_current_fails():
    c = claim("Instagram is testing a Reels-first home screen in India", "event", framed="current")
    note = factgate.judge(c, verdict(event_date="2025-09-29"), DUE, on_page)
    assert note and "Framed as current" in note
    past = claim("A year ago Instagram tested a Reels-first home screen in India", "event", framed="past")
    assert factgate.judge(past, verdict(event_date="2025-09-29"), DUE, on_page) is None


def test_outdated_verdict_fails():
    assert "Old news" in factgate.judge(claim("India just cut GST on scooters", "event", framed="current"),
                                        verdict("outdated", event_date="2025-09-22"), DUE, on_page)


def test_record_backed_only_by_an_aggregator_fails():
    c = claim("Gold hit a record Rs 1,50,300 for 10 grams", "superlative", core=True)
    assert "stronger source" in factgate.judge(c, verdict(sources=(AGGREGATOR,)), DUE, on_page)


def test_loss_making_brand_called_profitable_fails():
    c = claim("DailyObjects is profitable", "entity_attribute", core=True)
    assert "Wrong" in factgate.judge(c, verdict("contradicted", correct="Rs 16 cr loss in FY25"), DUE, on_page)


def test_emi_arithmetic():
    assert factgate.arithmetic_ok({"expr": "86999/6", "stated": "14,500"}) is True
    assert factgate.arithmetic_ok({"expr": "8667*6", "stated": "77,999"}) is False
    assert factgate.arithmetic_ok({"expr": "9**9**9", "stated": "1"}) is None  # powers are refused, not evaluated
    note = factgate.judge(claim("Rs 8,667 a month for 6 months", "arithmetic", expr="8667*6", stated="77999"), None, DUE)
    assert note and "sum is wrong" in note


def test_wrong_app_for_a_feature_fails():
    c = claim("Swiggy shows a 'sale ends in 2 hours' timer", "feature")
    assert "Wrong" in factgate.judge(c, verdict("contradicted", correct="that timer is Myntra's"), DUE, on_page)


def test_quote_not_on_the_cited_page_fails():
    c = claim("Old-gold exchange is about half of Titan's sourcing")
    assert "Could not confirm" in factgate.judge(c, verdict(), DUE, not_on_page)


def test_unverified_claim_fails_and_opinion_passes():
    assert "Could not verify" in factgate.judge(claim("India has 300 million Instagram users"), None, DUE, on_page)
    assert factgate.judge(claim("Mummy's almirah is a supply chain", "anecdote"), None, DUE, on_page) is None


def test_broken_mechanism_routes_to_the_writer(monkeypatch):
    def fake(model, user, stage="", **kw):
        if stage == "ledger":
            return {"claims": [claim("Jewellers get old gold duty-free, so it is 18% cheaper for them", "mechanism", core=True)]}
        if stage == "skeptic":
            return {"holds": False, "take_survives": True, "broken_premise": "the domestic gold rate already includes duty",
                    "actual_mechanism": "old gold is bought at the domestic rate; the gain is supply and a guaranteed sale"}
        raise AssertionError(stage)
    monkeypatch.setattr(llm, "call_json", fake)
    out = factgate.verify({"due": DUE, "topic": {}}, {"slides": [{"paragraphs": ["x"]}]}, on_page)
    assert not out["passed"] and not out["take_dead"] and "premise is wrong" in out["notes"][0]


def test_text_edited_after_verification_is_not_uploaded(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE", tmp_path / "state")
    draft = {"slides": [{"paragraphs": ["A verified hook"]}], "caption": "c", "alt_text": "a"}
    post = {"id": "2026-10-50", "status": "uploaded", "due": "2026-10-26T19:30:00+05:30", "format": "single",
            "topic": {}, "draft": draft, "image_urls": ["https://x/1.jpg"], "history": [],
            "verification": {"passed": True, "text_hash": factgate.text_hash(draft)}}
    assert factgate.still_valid(post)
    post["draft"]["caption"] = "edited after the check"
    state.save_post(post)
    monkeypatch.setattr(cli, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: __import__("datetime").datetime(2026, 10, 24, tzinfo=tz)),
                                                    "fromisoformat": staticmethod(__import__("datetime").datetime.fromisoformat)}))
    cli.push()
    held = state.posts()[0]
    assert held["status"] == "failed" and "verified" in held["error"]
