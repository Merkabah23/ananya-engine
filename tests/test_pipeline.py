import json
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
    ["Think about who that room is for. Not the family. The family lives in the bedroom."],
    ["The best furniture and the best light are kept for relatives who visit twice a year."],
    ["No one decided this. It happened one sofa cover at a time.", "Visitors get the good cups."],
    ["This generation said it was done with all that. Then look at the Instagram grid."],
    ["Look at what the room holds: the glass showcase, the cups no one drinks from, the sofa with its plastic still on.",
     "Every object waits for a guest who comes twice a year."],
    ["The family, meanwhile, eats dinner on the bed in front of the TV. The best room is the one used least, and it feels normal."],
    ["Even the AC is saved for them. It comes on when the doorbell rings and goes off the minute the last guest leaves."],
    ["The drawing room didn't die. It moved into our phones, still kept for visitors."],
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


def test_approved_posts_pass_code_checks(monkeypatch):
    """Posts the owner approved must never be rejected by our own rules. They were written as carousels before the
    page moved to reels, so the style rules apply but the carousel's length limits stand in for the reel's."""
    # the reel limits as they stood (8-10 Nov 2026), with the 24-word screens approved before the 18-word cap
    reel_limits = {"MIN_SLIDES": 6, "MAX_SLIDES": 8, "SLIDE_WORDS": (8, 24), "POST_WORDS": (80, 190), "MAX_PARAS": 2, "HOOK_WORDS": 25}
    native_limits = {n: getattr(writer, n) for n in ("MIN_SLIDES", "MAX_SLIDES", "SLIDE_WORDS", "POST_WORDS", "MAX_PARAS", "HOOK_WORDS")}
    carousel_limits = {"MIN_SLIDES": 5, "MAX_SLIDES": 9, "SLIDE_WORDS": (12, 60), "POST_WORDS": (110, 360), "MAX_PARAS": 3, "HOOK_WORDS": 25}
    for post in [b for b in writer.approved_posts() if b.get("source") != "reference creator"]:
        limits = {"reel": reel_limits, "native": native_limits}.get(post.get("format"), carousel_limits)
        for name, value in limits.items():
            monkeypatch.setattr(writer, name, value)
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
    assert any(f"{writer.MIN_SLIDES} to {writer.MAX_SLIDES} slides" in p for p in writer.hard_checks(draft(GOOD[:3]), "carousel", []))


def test_slots_cover_month_in_ist():
    slots = topic_filter.slots_for_month("2026-11")
    assert len(slots) == 21  # Monday to Friday
    assert [s["due"][:10] for s in slots[5:8]] == ["2026-11-09", "2026-11-10", "2026-11-11"]
    assert all(s["due"][11:16] == "20:30" and s["format"] == "carousel" for s in slots)
    assert slots[0]["due"].endswith("+05:30")


def test_assign_respects_format_and_no_repeat():
    from engine import config
    ranked = [{"id": str(i), "territory": t, "score": {"format_fit": "either" if i % 4 == 0 else "carousel"}}
              for i, t in enumerate(list(config.TERRITORY_MIX) * 7)]
    plan = topic_filter._assign(ranked, topic_filter.slots_for_month("2026-11"))
    dated = [p for p in plan if p["due"]]
    assert len(dated) == 21
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
    monkeypatch.setattr(config, "LOOK", "classic")
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
    assert not any("reversal" in p for p in writer.hard_checks(draft(repeated), "carousel", []))  # two can carry examples
    repeated[4] = ["The sofa isn't for sitting. It's for the photo. The rug isn't for walking. It's for the aunty who checks it."]
    assert any("reversal" in p for p in writer.hard_checks(draft(repeated), "carousel", []))


def test_question_hook_and_missing_swipe_reason_are_caught():
    bad = draft([["Why does every Indian home have one room nobody may sit in?", "Swipe to read →"]] + [list(s) for s in GOOD[1:]])
    bad["slides"][2]["why_swipe"] = ""
    problems = " ".join(writer.hard_checks(bad, "carousel", []))
    assert "question" in problems and "why_swipe" in problems


def test_editor_needs_real_eq_or_iq_and_a_strong_average():
    craft = {k: 4 for k in ("hook", "relatable", "fresh_angle", "pull", "payoff", "voice", "story", "tight")}
    assert writer.passes({"violations": [], "scores": {**craft, "eq": 5, "iq": 3}})
    assert not writer.passes({"violations": [], "scores": {**craft, "eq": 3, "iq": 3}})       # neither lands
    # one 3 no longer sinks a strong post (the old bar failed the owner's own approved posts)...
    assert writer.passes({"violations": [], "scores": {**craft, "tight": 3, "eq": 5, "iq": 5}})
    # ...but a weak average or a 2 anywhere still does
    assert not writer.passes({"violations": [], "scores": {**{k: 3 for k in craft}, "hook": 5, "eq": 5, "iq": 4}})
    assert not writer.passes({"violations": [], "scores": {**craft, "story": 2, "eq": 5, "iq": 5}})
    assert not writer.passes({"violations": ["Slide 3 is dead"], "scores": {**craft, "eq": 5, "iq": 5}})


def test_banned_phrase_on_the_cover_is_caught():
    d = {"cover": {"headline": "A [take] here", "sub": "The rules quietly stop applying."},
         "slides": [{"paragraphs": ["hook"]}, {"paragraphs": ["one two three"]}], "claims": []}
    assert any("quietly" in p for p in writer.hard_checks(d, "carousel", []))


def test_office_takes_are_spaced_out():
    office = [{"id": f"o{i}", "territory": t, "title": "appraisal season", "score": {"format_fit": "carousel"}}
              for i, t in enumerate(["money_status", "business_brands"] * 3)]
    other = [{"id": f"x{i}", "territory": t, "title": "trip photos", "score": {"format_fit": "carousel"}}
             for i, t in enumerate(["creators_internet", "pop_culture", "life_relationships", "world_geopolitics", "sports"] * 3)]
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


def test_slide_one_becomes_the_cover(monkeypatch):
    from engine import config
    monkeypatch.setattr(config, "LOOK", "classic")
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


def test_story_types_never_repeat_back_to_back():
    kinds = ["teaching"] * 6 + ["objection"] * 3
    terrs = ["money_status", "business_brands", "creators_internet", "pop_culture", "life_relationships"]
    ranked = [{"id": f"s{i}", "territory": terrs[i % 5], "title": "trip photos", "story_type": k,
               "score": {"format_fit": "carousel"}} for i, k in enumerate(kinds)]
    slots = topic_filter.slots_for_month("2099-11")[:5]
    plan = [p for p in topic_filter._assign(ranked, slots) if p["due"]]
    types = [p["topic"]["story_type"] for p in plan]
    assert all(a != b for a, b in zip(types, types[1:4]))


def test_generic_send_line_is_a_wording_fix(monkeypatch):
    from engine import config
    monkeypatch.setattr(config, "LOOK", "classic")  # the native card has no end card, so no send line
    d = {"slides": [{"paragraphs": ["x"]}], "end": {"send": "Send this to someone who needs it."}, "claims": []}
    found = [p for p in writer.hard_checks(d, "single", []) if "send line" in p]
    assert found and writer.is_wording(found[0])
    d["end"]["send"] = "Send to the friend who complains about café prices from the same café."
    assert not [p for p in writer.hard_checks(d, "single", []) if "send line" in p]


def test_dead_middle_slides_are_cut_not_rewritten():
    review = {"violations": ["Dead slide, slide 5: it restates slide 4's bold line."], "scores": {}}
    assert writer.dead_slides(review, 9) == [5]
    assert writer.dead_slides(review, 5) == []  # the last slide carries the payoff: never cut blind
    assert writer.dead_slides({"violations": ["Dead slide, slide 3", "No because"]}, 9) == []
    two = {"violations": ["Dead slide 3: restates slide 2.", "Slide 6 is a dead slide. Slide 7 says it again."]}
    assert writer.dead_slides(two, 9) == [3, 6]
    assert writer.dead_slides(two, 7) == []  # would leave fewer than the minimum
    assert writer.dead_slides({"violations": ["Slide 4 and slide 5 are partly dead"]}, 9) == []
    assert writer.dead_slides({"violations": ["Slides 4-5: dead"]}, 9) == []


def test_rewrites_are_checked_against_the_last_notes():
    assert writer.revision_block([], "critic") == ""
    block = writer.revision_block(["Dead slide 5: repeats slide 4."], "critic")
    assert "Dead slide 5" in block and "already read and accepted" in block
    assert "flag a new miss only on a line that changed" in writer.revision_block(["Not Varun (slide 2)"], "varun")


def test_near_miss_limits_are_trimmed_not_rewritten():
    assert writer.is_wording("The post is 342 words; keep it under 340 by cutting extra examples, not the thought.")
    assert writer.is_wording("Slides [9] have no why_swipe: say what pulls the reader to the next slide.")
    assert writer.is_wording("Slide 7 has 44 words; the limit is 42. It is too much to read on one screen.")


def test_a_false_take_is_dropped_before_any_draft(monkeypatch):
    calls = []
    def fake(model, prompt, stage="", **kw):
        calls.append(stage)
        return {"holds": False, "take_survives": False, "broken_premise": "premise 2", "actual_mechanism": "m"}
    monkeypatch.setattr(writer.llm, "call_json", fake)
    monkeypatch.setattr(writer, "find_sources", lambda t: [])
    post = {"id": "2099-12-001", "format": "carousel", "due": "2099-12-02T20:30:00+05:30", "history": [],
            "topic": {"claim": "a take that is false", "mechanism": "m"}}
    out = writer.write_post(post)
    assert out["status"] == "rejected" and "write" not in calls and calls.count("skeptic") == 1
    # a take that holds is checked once, and the fact gate reuses that verdict
    post2 = {"id": "2099-12-002", "topic": {"claim": "a true take"}, "due": ""}
    monkeypatch.setattr(writer.factgate, "skeptic", lambda *a: {"holds": True})
    assert writer.factgate.preflight(post2)["holds"] is True
    assert writer.factgate._take_key(post2) in post2["verification_cache"]["_skeptic_take"]


def test_review_mode_renders_only_owner_approved(tmp_path, monkeypatch):
    from engine import __main__ as cli, config, state
    monkeypatch.setattr(config, "STATE", tmp_path / "state")
    monkeypatch.setattr(config, "PAUSED", True)
    due = "2099-11-20T20:30:00+05:30"
    state.save_post({"id": "2099-11-01", "status": "planned", "due": due, "format": "carousel", "topic": {}, "history": []})
    state.save_post({"id": "2099-11-02", "status": "approved", "due": due, "format": "carousel", "topic": {}, "history": [], "owner_ok": True})
    seen = []
    monkeypatch.setattr(cli, "check_approved", lambda p: (seen.append(p["id"]), dict(p, status="failed", error="stop"))[1])
    monkeypatch.setattr(cli.writer, "write_post", lambda p: seen.append("WROTE " + p["id"]))
    cli.produce()
    assert seen == ["2099-11-02"]


def test_live_posts_are_logged_once_and_checked(tmp_path, monkeypatch):
    from engine import config, published, state
    monkeypatch.setattr(config, "STATE", tmp_path / "state")
    monkeypatch.setattr(published, "LOG", tmp_path / "published.json")
    state.save_post({"id": "2099-01-01", "status": "scheduled", "due": "2000-01-01T20:30:00+05:30", "format": "carousel",
                     "topic": {"claim": "Mummy's gold is hers", "title": "gold"}, "history": [],
                     "draft": {"cover": {"headline": "Mummy's [gold]"}}})
    assert len(published.record_live()) == 1 and published.record_live() == []
    assert published.log()[0]["headline"] == "Mummy's gold"
    monkeypatch.setattr(published.llm, "call_json", lambda *a, **k: {"repeat": True, "of": "Mummy's gold", "shared": "mummy's gold"})
    assert published.repeat_of({"claim": "Gold is the only money in her name"}) == "Mummy's gold"


def test_varun_check_gates_on_score_and_misses():
    miss = {"where": "slide 3", "line": "This reflects a culture of status.", "why": "essay voice", "try": "It's a flex."}
    assert writer.varun_passes({"pass": True, "score": 5, "misses": []})
    assert writer.varun_passes({"pass": True, "score": 4, "misses": [miss]})
    assert not writer.varun_passes({"pass": True, "score": 4, "misses": [miss, miss]})
    assert not writer.varun_passes({"pass": True, "score": 3, "misses": []})
    assert not writer.varun_passes({"pass": False, "score": 5, "misses": []})
    note = writer.varun_notes({"misses": [miss]})[0]
    assert "slide 3" in note and "culture of status" in note and "It's a flex." in note


def test_varun_misses_go_back_to_the_writer(monkeypatch):
    from engine import factgate, llm, published
    good = draft(GOOD)
    monkeypatch.setattr(published, "repeat_of", lambda topic: None)
    monkeypatch.setattr(writer, "mechanical", lambda d, fmt, ev: (d, []))
    monkeypatch.setattr(factgate, "verify", lambda post, d: {"passed": True, "notes": []})
    writes, checks = [], iter([
        {"pass": False, "score": 3, "misses": [{"where": "slide 2", "line": "x", "why": "essay voice", "try": "y"}]},
        {"pass": True, "score": 5, "misses": []}])
    def fake(model, user, stage="", **kw):
        if stage == "write":
            writes.append(user)
            return json.loads(json.dumps(good))
        if stage == "critic":
            return {"pass": True, "violations": [], "notes": [], "scores": {k: 5 for k in (
                "hook", "relatable", "fresh_angle", "pull", "payoff", "voice", "eq", "iq", "story", "tight")}}
        if stage == "varun":
            return next(checks)
        raise AssertionError(stage)
    monkeypatch.setattr(llm, "call_json", fake)
    post = {"id": "2099-11-05", "format": "carousel", "sources": [], "history": [],
            "topic": {"claim": "c", "needs_facts": False}}
    out = writer.write_post(post)
    assert out["status"] == "written" and len(writes) == 2
    assert "Not Varun (slide 2)" in writes[1]  # the second draft was written from the Varun note


def test_everyday_rupee_amounts_are_texture_but_big_unsourced_figures_are_not():
    receipt = [list(s) for s in GOOD]
    receipt[2] = ["Papa's medicines cost ₹4,000 a month, and the transfer home is ₹25,000. Everyone keeps the fiction going."]
    assert not any("figure" in p for p in writer.hard_checks(draft(receipt), "carousel", []))
    stat = [list(s) for s in GOOD]
    stat[2] = ["Indians spent ₹10 lakh crore on weddings last year, mostly on the guest list and the decor."]
    assert any("figure" in p for p in writer.hard_checks(draft(stat), "carousel", []))


def test_family_takes_are_never_planned_back_to_back():
    slots = [{"due": f"2099-11-{d:02d}T20:30:00+05:30", "format": "carousel"} for d in (2, 4, 6)]
    fam = lambda i, terr: {"id": f"f{i}", "title": "the shagun diary", "claim": "every family keeps a wedding ledger",
                           "territory": terr, "score": {"format_fit": "either"}}
    other = {"id": "o1", "title": "the creator economy", "claim": "brands pay for reach nobody can measure",
             "territory": "creators_internet", "score": {"format_fit": "either"}}
    plan = topic_filter._assign([fam(1, "life_relationships"), fam(2, "money_status"), other], slots)
    picks = [p["topic"]["id"] for p in plan if p["due"]]
    assert picks[:2] == ["f1", "o1"]  # the second family take waits until something else has run


def test_dense_writing_is_caught_but_the_approved_voice_passes(monkeypatch):
    from engine import config
    monkeypatch.setattr(config, "LOOK", "native")
    dense = [["Organisational considerations notwithstanding, comprehensive institutional accountability frameworks systematically "
              "underperform expectations, particularly regarding infrastructural deficiencies affecting metropolitan populations."]] * 8
    assert any("reads above the page's level" in p for p in writer.readability_problems(draft(dense), "carousel"))
    plain = [["The house is paid off.", "The future isn't."], ["Your mother calls it papa ki dawai ka kharcha. Everyone knows."]] * 4
    assert not any("reads above" in p for p in writer.readability_problems(draft(plain), "carousel"))


def test_native_slide_one_is_shown_as_written(monkeypatch):
    from engine import config
    monkeypatch.setattr(config, "LOOK", "native")
    d = draft([["Indian parents don't have a retirement plan.", "They have you."]] + [list(x) for x in GOOD[1:]])
    out, _ = writer.mechanical(d, "carousel", [], rounds=0)
    assert out["slides"][0]["paragraphs"] == ["Indian parents don't have a retirement plan.", "They have you."]


def test_posting_plan_is_weekdays_at_eight_thirty():
    from datetime import date
    slots = topic_filter.slots_for_month("2026-12")
    days = {date.fromisoformat(s["due"][:10]).weekday() for s in slots}
    assert days == {0, 1, 2, 3, 4} and all(s["due"][11:16] == "20:30" for s in slots)
    assert topic_filter.is_slot_day(date(2026, 12, 7)) and not topic_filter.is_slot_day(date(2026, 12, 6))  # Mon yes, Sun no


def test_new_topics_are_spaced_from_posts_already_in_the_calendar():
    slots = [{"due": "2099-11-03T20:30:00+05:30", "format": "carousel"}]
    around = {"2099-11-02": {"title": "the shagun diary", "claim": "every family keeps a wedding ledger", "territory": "life_relationships"}}
    fam = {"id": "f", "title": "your parents' bills", "claim": "paying your parents' bills from your account", "territory": "money_status",
           "score": {"format_fit": "either"}}
    other = {"id": "o", "title": "the creator economy", "claim": "brands pay for reach nobody can measure", "territory": "creators_internet",
             "score": {"format_fit": "either"}}
    plan = topic_filter._assign([fam, other], slots, around)
    assert plan[0]["topic"]["id"] == "o"
