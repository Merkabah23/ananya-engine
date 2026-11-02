import os

os.environ["DRY_RUN"] = "true"

from engine import buffer, corpus, filter as topic_filter, writer  # noqa: E402


def draft(slides, claims=None):
    return {"slides": [{"paragraphs": p, "why_swipe": "the reader wants to see where this goes next"} for p in slides],
            "cover": {"headline": "Every Indian home keeps its [best room] for guests", "sub": "s"},
            "caption": "Which one are you?",
            "alt_text": "A text post", "claims": claims or []}


GOOD = [
    ["Every Indian home has one room nobody is allowed to sit in.", "Swipe to read →"],
    ["Think about who that room is for. Not the family. The family lives in the bedroom, TV on the bed, dinner on a steel plate, cousins on the floor on Sundays."],
    ["The best furniture and the best light are kept for people who don't live there. It is how a family is seen by relatives who visit twice a year."],
    ["No one in the family ever decided this out loud. It just happened, one sofa cover and one locked glass cabinet at a time, until the room became a stage for visitors.", "The visitors know it. They sip tea in the good cups."],
    ["This generation said it was done with all of that. But look at the Instagram grid. The best angle of the best corner, kept for an audience that will never live in it either."],
    ["The drawing room didn't die. It just moved into our phones, and we still keep the best of ourselves for the people who are only visiting."],
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
    src = [{"fact": "Indians spent ₹10 lakh crore on weddings in 2025", "url": "https://example.com/report"}]
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
    bad[2] = ["You know the scene: that room, and it is not about the furniture or the light at all, honestly."]
    bad[4] = [" ".join(["word"] * 44) + "."]
    bad[3] = ["Short one, nothing more here."]
    problems = " ".join(writer.hard_checks(draft(bad), "carousel", []))
    assert "you know the scene" in problems.lower() and "too thin" in problems


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
            slides.append({"paragraphs": paras, "why_swipe": "approved by the owner"})
        d = {"slides": slides, "claims": [], "cover": {"headline": "A placeholder cover headline with a [key phrase]"}}
        assert writer.hard_checks(d, "carousel", evidence) + writer.readability_problems(d, "carousel") == [], post["title"]


def test_voice_examples_rotate_from_the_bank():
    assert writer.voice_examples(1).count("### Example:") == min(3, len(writer.approved_posts()))


def test_wrong_slide_count():
    assert any("4 to 7 slides" in p for p in writer.hard_checks(draft(GOOD[:3]), "carousel", []))


def test_slots_cover_month_in_ist():
    slots = topic_filter.slots_for_month("2026-11")
    assert len(slots) == 30  # one a day
    assert all(s["due"][11:16] == "20:30" and s["format"] == "carousel" for s in slots)
    assert slots[0]["due"].endswith("+05:30")


def test_assign_respects_format_and_no_repeat():
    from engine import config
    ranked = [{"id": str(i), "territory": t, "score": {"format_fit": "either" if i % 4 == 0 else "carousel"}}
              for i, t in enumerate(list(config.TERRITORY_MIX) * 7)]
    plan = topic_filter._assign(ranked, topic_filter.slots_for_month("2026-11"))
    dated = [p for p in plan if p["due"]]
    assert len(dated) == 30
    for a, b in zip(dated, dated[1:]):
        assert a["topic"]["territory"] != b["topic"]["territory"]
    for p in dated:
        if p["format"] == "single":
            assert p["topic"]["score"]["format_fit"] in ("single", "either")


def test_assign_skips_unfillable_single_slot():
    slots = [{"due": "2026-11-07T11:00:00+05:30", "format": "single"}, {"due": "2026-11-08T20:30:00+05:30", "format": "carousel"}]
    ranked = [{"id": str(i), "territory": "money_status", "score": {"format_fit": "carousel"}} for i in range(3)]
    dated = [p for p in topic_filter._assign(ranked, slots) if p["due"]]
    assert [p["due"][:10] for p in dated] == ["2026-11-08"]  # the single slot stays empty instead of ending the plan


def test_buffer_input_shape():
    os.environ["BUFFER_CHANNEL_ID"] = "ch_1"  # explicit id wins over handle lookup
    post = {"due": "2026-11-02T19:30:00+05:30", "draft": draft(GOOD), "image_urls": [f"https://x/{i}.jpg" for i in range(12)]}
    inp = buffer.build_input(post, post["image_urls"])
    assert inp["dueAt"] == "2026-11-02T14:00:00.000Z"
    assert len(inp["assets"]) == 10
    assert inp["metadata"]["instagram"]["type"] == "post"
    assert inp["mode"] == "customScheduled" and inp["needsApproval"] is False  # the channel itself lands posts in drafts


def test_sentence_split_keeps_abbreviations():
    assert writer.sentences("Gill is No. 1 now. Kohli is third.") == ["Gill is No. 1 now.", "Kohli is third."]


def test_readability_flags_long_sentences_bold_and_extra_italics():
    d = draft([["This sentence is deliberately far too long because it keeps going and going and going without any pause at all for the reader, who by now has stopped reading and moved on to a reel."],
               ["**One bold line.** And **a second one.**"], ["*One* and *two* italics."], ["Fine."]])
    problems = " ".join(writer.readability_problems(d, "carousel"))
    assert f"max {writer.MAX_SENT_WORDS}" in problems and "more than one **bold**" in problems and "2 italic" in problems


def test_italic_markers_render_and_are_stripped_from_text():
    from engine import render
    assert render._tokens("say *khana khaya* now **then**") == [("say", "regular"), ("khana", "italic"), ("khaya", "italic"),
                                                                ("now", "regular"), ("then", "bold")]
    assert writer.post_text(draft([["say *khana khaya* now"]])) == "say khana khaya now"


def test_hashtags_brand_first_clean_and_capped():
    tags = buffer.hashtags({"hashtags": ["PersonalFinanceIndia", "#Diwali 2026", "#aboveMRP", "#a", "#b", "#c", "#d"]})
    assert tags[0] == "#AboveMRP" and len(tags) == 5
    assert "#Diwali2026" in tags and sum(t.lower() == "#abovemrp" for t in tags) == 1
    assert buffer.caption_with_tags({"caption": "Which one are you?", "hashtags": ["#X"]}) == "Which one are you?\n\n#AboveMRP #X"


def test_only_the_last_carousel_slide_is_the_end_card(tmp_path, monkeypatch):
    from engine import config, render
    monkeypatch.setattr(config, "OUT", tmp_path)
    post = {"id": "x", "format": "carousel", "draft": draft(GOOD)}
    shades = [render.Image.open(p).getpixel((5, 5)) for p in render.render_post(post)]
    assert shades.count(shades[-1]) == 1 and len(set(shades[:-1])) == 1


def test_one_closing_reversal_is_fine_but_repeats_mid_post_are_caught():
    closing = [list(s) for s in GOOD]
    closing[-1] = ["They didn't keep the drawing room for guests. It was never about the guests.", "It was always about being seen, by anyone at all."]
    assert not any("reversal" in p for p in writer.hard_checks(draft(closing), "carousel", []))
    repeated = [list(s) for s in GOOD]
    repeated[2] = ["The room isn't for the family. It's for the relatives who visit twice a year and judge the sofa."]
    repeated[3] = ["The good cups aren't for drinking. They're for being seen, and the visitors know it as well as you do."]
    assert any("reversal" in p for p in writer.hard_checks(draft(repeated), "carousel", []))


def test_question_hook_and_missing_swipe_reason_are_caught():
    bad = draft([["Why does every Indian home have one room nobody may sit in?", "Swipe to read →"]] + [list(s) for s in GOOD[1:]])
    bad["slides"][2]["why_swipe"] = ""
    problems = " ".join(writer.hard_checks(bad, "carousel", []))
    assert "question" in problems and "why_swipe" in problems


def test_editor_needs_real_eq_or_iq_and_a_tight_post():
    craft = {k: 4 for k in ("hook", "relatable", "fresh_angle", "pull", "payoff", "voice", "story", "tight")}
    assert writer.passes({"violations": [], "scores": {**craft, "eq": 5, "iq": 3}})
    assert not writer.passes({"violations": [], "scores": {**craft, "eq": 3, "iq": 3}})       # neither lands
    assert not writer.passes({"violations": [], "scores": {**craft, "tight": 3, "eq": 5, "iq": 5}})  # over-explained
    assert not writer.passes({"violations": [], "scores": {**craft, "story": 3, "eq": 5, "iq": 5}})  # a pattern, not the reader's story


def test_banned_phrase_on_the_cover_is_caught():
    d = {"cover": {"headline": "A [take] here", "sub": "The rules quietly stop applying."},
         "slides": [{"paragraphs": ["hook"]}, {"paragraphs": ["one two three"]}], "claims": []}
    assert any("quietly" in p for p in writer.hard_checks(d, "carousel", []))


def test_office_takes_are_spaced_out():
    office = [{"id": f"o{i}", "territory": t, "title": "appraisal season", "score": {"format_fit": "carousel"}}
              for i, t in enumerate(["money_status", "business_brands"] * 3)]
    other = [{"id": f"x{i}", "territory": t, "title": "trip photos", "score": {"format_fit": "carousel"}}
             for i, t in enumerate(["creators_internet", "pop_culture", "life_relationships"] * 3)]
    slots = topic_filter.slots_for_month("2026-11")[:9]
    plan = [p for p in topic_filter._assign(office + other, slots) if p["due"]]
    flags = [topic_filter._is_office(p["topic"]) for p in plan]
    assert not any(flags[i] and (flags[i - 1] or flags[i - 2]) for i in range(2, len(flags)))


def test_top_up_plans_open_days_once(tmp_path, monkeypatch):
    from engine import __main__ as cli, config, scout, state
    monkeypatch.setattr(config, "STATE", tmp_path / "state")
    calls = []
    monkeypatch.setattr(scout, "run", lambda month, fresh_news=False: calls.append(("scout", fresh_news)))
    monkeypatch.setattr(topic_filter, "run", lambda month, plan_month=None: calls.append(("plan", plan_month)))
    cli.top_up()
    assert calls[0] == ("scout", True) and any(c[0] == "plan" for c in calls)
    calls.clear()
    cli.top_up()  # ran moments ago: waits a few days before scouting again
    assert calls == []


def test_slide_one_becomes_the_cover():
    d = {"cover": {"headline": "The corner shop backs you harder than any [bank] will"},
         "slides": [{"paragraphs": [" ".join(["word"] * 30), "Swipe to read →"]}, {"paragraphs": ["x"]}], "claims": []}
    out, _ = writer.mechanical(d, "carousel", [])
    assert out["slides"][0]["paragraphs"][0] == "The corner shop backs you harder than any bank will."


def test_a_slide_a_few_words_long_is_split_not_failed():
    long = {"paragraphs": [" ".join(["alpha"] * 34) + ".", " ".join(["beta"] * 30) + "."], "why_swipe": "w"}
    d = {"slides": [{"paragraphs": ["hook"]}, long, {"paragraphs": ["x"]}]}
    out = writer.split_long_slides(d)
    assert len(out["slides"]) == 4 and out["slides"][1]["paragraphs"][0].startswith("alpha")
    assert out["slides"][2]["paragraphs"][0].startswith("beta") and out["slides"][2]["why_swipe"] == "w"


def test_small_wording_problems_are_polished_not_rewritten(monkeypatch):
    from engine import llm
    asked = []
    def fake(model, user, stage="", **kw):
        asked.append(stage)
        return {"slides": [{"paragraphs": ["hook"]}, {"paragraphs": ["A plain line that is long enough to count as a slide here."]}]}
    monkeypatch.setattr(llm, "call_json", fake)
    d = {"slides": [{"paragraphs": ["hook"]}, {"paragraphs": ["It quietly costs you more than you think every week."]}], "claims": []}
    writer.mechanical(d, "single", [])
    assert "polish" in asked and "repair" not in asked
