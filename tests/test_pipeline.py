import os

os.environ["DRY_RUN"] = "true"

from engine import buffer, corpus, filter as topic_filter, writer  # noqa: E402


def draft(slides, claims=None):
    return {"slides": [{"paragraphs": p} for p in slides], "caption": "Which one are you?",
            "alt_text": "A text post", "claims": claims or []}


GOOD = [
    ["Every Indian home has one room nobody is allowed to sit in.", "Swipe to read →"],
    ["Think about who that room is for. Not the family. The family lives in the bedroom, TV on the bed, dinner on a steel plate, cousins on the floor."],
    ["The best furniture and the best light are kept for people who don't live there. It is how a family is seen by the relatives who visit twice a year."],
    ["The good dinner set. The new bedsheet saved for guests. The shirt for functions only. Indian families keep their best for the audience, every single time."],
    ["And this generation didn't drop the habit. It moved the drawing room to the Instagram grid. Curated, cleaned up, kept for visitors."],
]


def test_clean_draft_passes_hard_checks():
    assert writer.hard_checks(draft(GOOD), "carousel", []) == []


def test_banned_phrase_and_em_dash_are_caught():
    bad = [list(s) for s in GOOD]
    bad[1] = ["Here's the thing — the room is a stage and a testament to status in our journey."]
    problems = " ".join(writer.hard_checks(draft(bad), "carousel", []))
    assert "here's the thing" in problems.lower() and "—" in problems and "journey" in problems


def test_unsourced_money_figure_is_caught():
    bad = [list(s) for s in GOOD]
    bad[2] = ["Indians spent ₹10 lakh crore on weddings last year, mostly on the guest list and the decor."]
    assert any("figure" in p for p in writer.hard_checks(draft(bad), "carousel", []))


def test_sourced_money_figure_passes():
    src = [{"fact": "x", "url": "https://example.com/report"}]
    bad = [list(s) for s in GOOD]
    bad[2] = ["Indians spent ₹10 lakh crore on weddings last year, mostly on the guest list and the decor."]
    claims = [{"text": "Indians spent ₹10 lakh crore on weddings", "source_url": "https://example.com/report"}]
    assert not any("figure" in p for p in writer.hard_checks(draft(bad, claims), "carousel", src))


def test_copied_run_from_reference_is_caught():
    line = corpus.posts()[0]["slides"][1]
    copied = [list(s) for s in GOOD]
    copied[3] = [" ".join(line.split()[:14])]
    assert corpus.copied_runs(" ".join(copied[3]))


def test_merge_paragraphs_caps_slide():
    paras = ["One.", "Two here.", "Three now.", "Four.", "Five.", "Six.", "Swipe to read →"]
    out = writer.merge_paragraphs({"slides": [{"paragraphs": list(paras)}]}, "carousel")["slides"][0]["paragraphs"]
    assert len(out) == writer.MAX_PARAS + 1 and out[-1] == "Swipe to read →"
    assert " ".join(out[:-1]) == " ".join(paras[:-1])
    assert not any("paragraphs; use at most" in p for p in writer.readability_problems({"slides": [{"paragraphs": out}]}, "carousel"))


def test_explaining_signpost_and_unbalanced_slide_are_caught():
    bad = [list(s) for s in GOOD]
    bad[2] = ["Here's what's really going on with that room, and it is not about furniture or the light at all, honestly."]
    bad[4] = [" ".join(["word"] * 80) + "."]
    problems = " ".join(writer.hard_checks(draft(bad), "carousel", []))
    assert "here's what's really going on" in problems.lower() and "balance it" in problems


def test_approved_posts_pass_code_checks():
    """Posts the owner approved must never be rejected by our own rules."""
    for post in [b for b in writer.approved_posts() if b.get("source") != "reference creator"]:
        # Approved posts were fact-checked against their own sources when written; here only the style rules apply.
        evidence = [{"url": "topic", "fact": "", "excerpt": "\n".join(post["slides"])}]
        slides = []
        for slide in post["slides"]:
            paras = []
            for line in [l for l in slide.split("\n") if l.strip()]:
                if line.startswith("–") and paras:
                    paras[-1] += "\n" + line  # a dash list lives inside one paragraph
                else:
                    paras.append(line)
            slides.append({"paragraphs": paras})
        d = {"slides": slides, "claims": []}
        assert writer.hard_checks(d, "carousel", evidence) + writer.readability_problems(d, "carousel") == [], post["title"]


def test_voice_examples_rotate_from_the_bank():
    assert writer.voice_examples(1).count("### Example:") == min(3, len(writer.approved_posts()))


def test_wrong_slide_count():
    assert any("5 to 8 slides" in p for p in writer.hard_checks(draft(GOOD[:3]), "carousel", []))


def test_slots_cover_month_in_ist():
    slots = topic_filter.slots_for_month("2026-11")
    assert len(slots) == 17  # 5 Mon, 4 Wed, 4 Fri, 4 Sat in Nov 2026
    assert slots[0]["due"].endswith("+05:30")


def test_assign_respects_format_and_no_repeat():
    from engine import config
    ranked = [{"id": str(i), "territory": t, "score": {"format_fit": "either" if i % 4 == 0 else "carousel"}}
              for i, t in enumerate(list(config.TERRITORY_MIX) * 5)]
    plan = topic_filter._assign(ranked, topic_filter.slots_for_month("2026-11"))
    dated = [p for p in plan if p["due"]]
    assert len(dated) == 17
    for a, b in zip(dated, dated[1:]):
        assert a["topic"]["territory"] != b["topic"]["territory"]
    for p in dated:
        if p["format"] == "single":
            assert p["topic"]["score"]["format_fit"] in ("single", "either")


def test_assign_skips_unfillable_single_slot():
    ranked = [{"id": str(i), "territory": "money_status", "score": {"format_fit": "carousel"}} for i in range(30)]
    plan = topic_filter._assign(ranked, topic_filter.slots_for_month("2026-11"))
    dated = [p for p in plan if p["due"]]
    assert len(dated) == 13  # every carousel slot filled; the 4 Saturdays stay empty instead of ending the month
    assert dated[-1]["due"].startswith("2026-11-30")


def test_buffer_input_shape():
    os.environ["BUFFER_CHANNEL_ID"] = "ch_1"  # explicit id wins over handle lookup
    post = {"due": "2026-11-02T19:30:00+05:30", "draft": draft(GOOD), "image_urls": [f"https://x/{i}.jpg" for i in range(12)]}
    inp = buffer.build_input(post, post["image_urls"])
    assert inp["dueAt"] == "2026-11-02T14:00:00.000Z"
    assert len(inp["assets"]) == 10
    assert inp["metadata"]["instagram"]["type"] == "post"
    assert inp["mode"] == "customScheduled" and inp["needsApproval"] is True  # owner approves in Buffer by default


def test_sentence_split_keeps_abbreviations():
    assert writer.sentences("Gill is No. 1 now. Kohli is third.") == ["Gill is No. 1 now.", "Kohli is third."]


def test_readability_flags_long_sentences_bold_and_extra_italics():
    d = draft([["This sentence is deliberately far too long because it keeps going and going and going without any pause at all for the reader, who by now has stopped reading and moved on to a reel."],
               ["**Bold is not house style.**"], ["*One* and *two* italics."], ["Fine."]])
    problems = " ".join(writer.readability_problems(d, "carousel"))
    assert "max 32" in problems and "uses bold" in problems and "2 italic" in problems


def test_italic_markers_render_and_are_stripped_from_text():
    from engine import render
    assert render._tokens("say *khana khaya* now") == [("say", False), ("khana", True), ("khaya", True), ("now", False)]
    assert writer.post_text(draft([["say *khana khaya* now"]])) == "say khana khaya now"
