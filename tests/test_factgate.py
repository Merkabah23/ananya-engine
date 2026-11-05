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


def test_older_or_rounded_numbers_pass_but_wrong_ones_fail():
    """The page's numbers paint a picture: older, rounded or framed loosely is fine; wrong in direction or size is not."""
    c = claim("Instagram is testing a Reels-first home screen in India", "event", framed="current",
              sentence="Instagram is testing a Reels-first home screen in India.")
    assert factgate.judge(c, verdict(event_date="2025-09-29"), DUE, on_page) is None
    assert factgate.judge(claim("India just cut GST on scooters", "event", framed="current"),
                          verdict("outdated", event_date="2025-09-22"), DUE, on_page) is None
    assert factgate.judge(claim("About 40% of cars sell in rural India", "figure"), verdict("misframed"), DUE, on_page) is None
    c = claim("Gold hit a record Rs 1,50,300 for 10 grams", "superlative", core=True)
    assert factgate.judge(c, verdict(sources=(AGGREGATOR,)), DUE, on_page) is None  # one reachable source is enough
    assert "Wrong" in factgate.judge(claim("Car sales fell in Navratri 2025", "figure"), verdict("contradicted"), DUE, on_page)


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


def test_fetch_refuses_private_and_odd_addresses():
    for url in ("http://169.254.169.254/latest/meta-data/", "http://127.0.0.1/x", "http://10.0.0.5/", "file:///etc/passwd",
                "http://localhost:8080/", "ftp://example.com/x", "https://example.com:8443/x"):
        assert not factgate._public(url), url
    assert factgate.quote_on_page("http://169.254.169.254/latest/meta-data/", "anything") is None


def test_an_ongoing_trend_is_not_stale_news():
    trend = claim("Since May, old gold is a big part of what jewellers sell", "event", framed="current",
                  sentence="Since May, old gold like hers is a big part of what he sells.")
    assert factgate.judge(trend, verdict(event_date="2026-05-13"), DUE, on_page) is None


def test_same_text_gets_the_same_verdict_without_new_calls(monkeypatch):
    calls = []
    def fake(model, user, stage="", **kw):
        calls.append(stage)
        return {"claims": []} if stage == "ledger" else {}
    monkeypatch.setattr(llm, "call_json", fake)
    post, draft = {"due": DUE, "topic": {}}, {"slides": [{"paragraphs": ["He waves your phone away."]}]}
    first = factgate.verify(post, draft, on_page)
    assert factgate.verify(post, draft, on_page)["passed"] == first["passed"] and calls == ["ledger"]


def test_an_edit_only_rereads_the_changed_sentences(monkeypatch):
    asks = []
    kept = claim("Banks use credit scores", "feature", sentence="A bank goes by your score.")
    def fake(model, user, stage="", **kw):
        asks.append(user)
        if stage == "ledger":
            return {"claims": [kept]} if len(asks) == 1 else {"claims": []}
        return {"c1": verdict()}
    monkeypatch.setattr(llm, "call_json", fake)
    monkeypatch.setattr(factgate, "web_verify", lambda claims, due, leads: {c["id"]: verdict() for c in claims})
    post = {"due": DUE, "topic": {}}
    factgate.verify(post, {"slides": [{"paragraphs": ["A bank goes by your score.", "He knows why."]}]}, on_page)
    out = factgate.verify(post, {"slides": [{"paragraphs": ["A bank goes by your score.", "He knows why you didn't."]}]}, on_page)
    assert "- He knows why you didn't." in asks[-1] and "- A bank goes by your score." not in asks[-1]
    assert [c["text"] for c in out["ledger"]] == ["Banks use credit scores"] and out["passed"]
