"""Agent 3, the writer (the Above MRP voice), with its editor loop.

sources (searched and fetched once) -> draft -> code checks -> editor + fact check (in parallel)
Every failure goes back to the writer as notes, up to MAX_REWRITES times. Nothing after the writer
rewrites content; the only automatic edit is a mechanical one (splitting sentences, removing bold).
"""
from __future__ import annotations

import json
import random
import re
import statistics
import zlib

from . import config, corpus, llm, state

FORMAT_RULES = {
    "carousel": "a reel of 6 to 8 text screens, as few as the idea needs, each read in a few seconds. Slide 1 is at "
                "most 25 words and ends with 'Swipe to read →'. The last slide is the payoff.",
    "single": "a single slide of 30-70 words, like a post someone types straight out of their head: a blunt take or "
              "prediction about India or this generation, a short rant, a satire list ('Literally everyone around me is:' "
              "then short lines starting with '- '), or a short open letter ('Dear ___,'). No 'Swipe to read'.",
}
MAX_PARAS = 2            # per slide: a reel screen holds for 8 seconds at most
MAX_SENTS_PER_PARA = 4
MAX_SENT_WORDS = 22  # 5th-grade scanability: most sentences far shorter
MIN_SLIDES, MAX_SLIDES = 6, 8  # the benchmark reel runs 8: hook, burst, generations, trick, cost, this-is-why, stance, close
SLIDE_WORDS = (8, 24)    # reel screens hold 5s each (reel.SLIDE_HOLD): short enough to take in at a glance
HOOK_WORDS = 25
POST_WORDS = (80, 190)   # reels: the benchmark's 8 beats, each cut to one screen; ~35-50 seconds
MAX_FIGURES = 6          # insider voice: everyday prices are texture; statistics still need a source
MIN_RHYTHM = 3.5         # sentence-length spread; a metronome rhythm (every sentence ~8 words) reads as AI
# "isn't X, it's Y" closes many of the reference creator's best posts; repeated mid-post it reads as a template.
REVERSAL = re.compile(r"\b(isn't|is not|wasn't|was not|aren't|never)\b[^.?!]{0,60}[.?!]\s*(it's|it is|it was|they're|"
                      r"she's|he's|that's|this is)\b|\bwas never about\b", re.I)
MONEY = re.compile(r"(₹\s?[\d,.]+(\s?(crore|cr|lakh|k))?|\brs\.?\s?[\d,.]+|[\d,.]+\s?(%|percent|crore|cr\b|lakh|lpa|million|billion))", re.I)


def _banned() -> list[re.Pattern]:
    lines = (config.DATA / "banned_phrases.txt").read_text().splitlines()
    return [re.compile(l.strip(), re.I) for l in lines if l.strip() and not l.startswith("#")]


def post_text(draft: dict) -> str:
    """Plain text of the post (bold markers removed)."""
    return "\n\n".join("\n\n".join(s["paragraphs"]) for s in draft["slides"]).replace("*", "")


_ABBREV = re.compile(r"\b(No|Mr|Mrs|Ms|Dr|Rs|vs|St|Jr|Sr|Inc|Ltd|approx|etc)\.", re.I)


def sentences(text: str) -> list[str]:
    """Split into sentences without breaking on 'No. 1', 'Rs. 500', 'Dr. Rao' and similar."""
    protected = _ABBREV.sub(lambda m: m.group(1) + "\u2024", text.replace("*", ""))
    return [x.replace("\u2024", ".") for x in re.split(r"(?<=[.!?])\s+", protected) if x.strip()]


def readability_problems(draft: dict, fmt: str) -> list[str]:
    """Scanability rules, enforced in code: short sentences, short paragraphs, no bold, at most one italic per slide."""
    problems = []
    for i, s in enumerate(draft.get("slides", []), 1):
        paras = [p for p in s.get("paragraphs", []) if not p.strip().lower().startswith("swipe to read")]
        if fmt == "carousel":
            if len(paras) > MAX_PARAS:
                problems.append(f"Slide {i} has {len(paras)} paragraphs; use at most {MAX_PARAS}.")
            if sum(p.count("**") // 2 for p in paras) > 1:
                problems.append(f"Slide {i} has more than one **bold** line; keep one at most, on the line that matters.")
            italics = sum(p.replace("**", "").count("*") // 2 for p in paras)
            if italics > 1:
                problems.append(f"Slide {i} has {italics} italic phrases; use at most one, only where it's needed.")
        for p in paras:
            lines = [l for l in p.split("\n") if l.strip() and not l.lstrip().startswith(("-", "–", "•"))]
            if not lines:
                continue  # list items are fragments by design
            sents = [x for l in lines for x in sentences(l)]
            if len(sents) > MAX_SENTS_PER_PARA and fmt == "carousel":
                problems.append(f"Slide {i}: a paragraph has more than {MAX_SENTS_PER_PARA} sentences; split it.")
            for x in sents:
                n = len(x.split())
                if n > MAX_SENT_WORDS:
                    problems.append(f"Slide {i}: this sentence has {n} words, max {MAX_SENT_WORDS}: '{x[:70]}...'")
    words = [len(x.split()) for s in draft.get("slides", []) for p in s.get("paragraphs", [])
             for x in sentences(p) if not x.lower().startswith("swipe")]
    if fmt == "carousel" and words and sum(words) / len(words) > 16:
        problems.append(f"Average sentence is {sum(words) / len(words):.1f} words; keep it at 16 or under.")
    if fmt == "carousel" and len(words) >= 8 and statistics.pstdev(words) < MIN_RHYTHM:
        problems.append("Every sentence is about the same length, which reads as a template. Put one longer, concrete "
                        "sentence next to a short punch on most slides.")
    return problems[:6]




MECHANICAL = ("sentence has", "paragraphs; use at most", "more than 4 sentences", "**bold** line", "italic phrases",
              "Average sentence is")


# Small wording problems: a targeted edit to the named line fixes them without a rewrite.
WORDING = ("Remove the phrase", "'Nobody' appears more than once", "words; the limit is", "Every sentence is about the same length",
           "isn't in the sources; source it or remove it", "The post carries", "The send line names no specific person")


def is_mechanical(problem: str) -> bool:
    """Layout problems a quick edit can fix without touching what the post says."""
    return any(m in problem for m in MECHANICAL)


def is_wording(problem: str) -> bool:
    return any(m in problem for m in WORDING)


def polish(draft: dict, problems: list[str]) -> dict:
    """Fix small wording problems by editing only the lines they name; every other line stays word for word."""
    ask = ("Make the smallest edits that fix ONLY these problems in this Instagram carousel draft. Change only the sentences "
           "they name or that cause them: swap a banned phrase for plain words, change a repeated 'nobody' to another "
           "phrasing, trim a few words from an overlong slide, make one sentence longer or shorter to vary the rhythm, "
           "write an unsourced figure out in words without a number. Keep every other sentence, the meaning and the voice "
           "exactly as they are, and keep every other field.\n\n## Problems\n" + "\n".join(f"- {p}" for p in problems) +
           "\n\n## Draft\n" + json.dumps(draft, ensure_ascii=False, indent=1) + "\n\nReturn only the corrected draft as the same JSON object.")
    try:
        fixed = llm.call_json(config.MODEL_JUDGE, ask, stage="polish")
        return fixed if fixed.get("slides") else draft
    except SystemExit:
        raise
    except Exception:
        return draft


def repair(draft: dict, problems: list[str], sources: list[dict]) -> dict:
    """Mechanical fixes only: split long sentences, move paragraph breaks, remove bold. Never deletes a sentence or
    touches a fact; anything about content goes back to the writer as a note."""
    ask = ("Fix ONLY the layout problems listed in this Instagram carousel draft, by splitting long sentences into two, "
           "moving paragraph breaks, or removing extra ** bold markers (keep at most one bold line per slide). Do not delete any sentence, idea, number or fact, do not "
           "add anything, and do not change wording beyond what a split needs. "
           f"Sentences of {MAX_SENT_WORDS} words or fewer, at most {MAX_SENTS_PER_PARA} sentences per paragraph, at most "
           f"{MAX_PARAS} paragraphs per slide, at most one *italic* phrase per slide. Keep every other field as it is.\n\n"
           "## Problems\n" + "\n".join(f"- {p}" for p in problems) +
           "\n\n## Draft\n" + json.dumps(draft, ensure_ascii=False, indent=1) +
           "\n\nReturn only the corrected draft as the same JSON object.")
    try:
        fixed = llm.call_json(config.MODEL_JUDGE, ask, stage="repair")
        return fixed if fixed.get("slides") else draft
    except SystemExit:
        raise
    except Exception:
        return draft


def merge_paragraphs(draft: dict, fmt: str) -> dict:
    """Join adjacent short paragraphs until each carousel slide has at most MAX_PARAS. Text is unchanged, only the breaks move.

    Splitting long sentences (a repair) tends to add paragraphs, so this runs after every repair."""
    if fmt != "carousel":
        return draft
    for s in draft.get("slides", []):
        paras = s.get("paragraphs", [])
        tail = [p for p in paras if p.strip().lower().startswith("swipe to read")]
        body = [p for p in paras if p not in tail]
        while len(body) > MAX_PARAS:
            i = min(range(len(body) - 1), key=lambda k: len(sentences(body[k])) + len(sentences(body[k + 1])))
            body[i:i + 2] = [body[i].rstrip() + " " + body[i + 1].lstrip()]
        s["paragraphs"] = body + tail
    return draft


def split_long_slides(draft: dict) -> dict:
    """A slide a few words over the limit becomes two slides at a paragraph break, while the post has room for one
    more. Text is unchanged; only where it sits."""
    slides = draft.get("slides", [])
    i = 1
    while i < len(slides) and len(slides) < MAX_SLIDES:
        body = slides[i].get("paragraphs", [])
        words = [len(p.split()) for p in body]
        if sum(words) > SLIDE_WORDS[1] and len(body) >= 2:
            cut = min(range(1, len(body)), key=lambda k: abs(sum(words[:k]) - sum(words[k:])))
            if min(sum(words[:cut]), sum(words[cut:])) >= SLIDE_WORDS[0]:
                first = {**slides[i], "paragraphs": body[:cut], "why_swipe": "what happens next?"}
                slides[i:i + 1] = [first, {**slides[i], "paragraphs": body[cut:]}]
        i += 1
    return draft


def mechanical(draft: dict, fmt: str, sources: list[dict], rounds: int = 2) -> tuple[dict, list[str]]:
    """Code checks. Layout problems get a quick mechanical repair; content problems are returned for the writer.
    Does not use up a rewrite attempt."""
    headline = re.sub(r"[\[\]]", "", (draft.get("cover") or {}).get("headline", "")).strip()
    if fmt == "carousel" and headline and draft.get("slides"):  # slide 1 is never shown: the cover replaces it
        draft["slides"][0]["paragraphs"] = [headline.rstrip(".") + ".", "Swipe to read →"]
    draft = merge_paragraphs(draft, fmt)
    if fmt == "carousel":
        draft = split_long_slides(draft)
    problems = hard_checks(draft, fmt, sources) + readability_problems(draft, fmt)
    for _ in range(rounds):
        layout = [p for p in problems if is_mechanical(p)]
        wording = [p for p in problems if is_wording(p)]
        if not layout and not wording:
            break
        if layout:
            draft = merge_paragraphs(repair(draft, layout, sources), fmt)
        if wording:
            draft = merge_paragraphs(polish(draft, wording), fmt)
        problems = hard_checks(draft, fmt, sources) + readability_problems(draft, fmt)
    return draft, problems


def find_sources(topic: dict) -> list[dict]:
    """Find sources AND save the relevant text of each page, once. The writer may only use these excerpts."""
    if topic.get("needs_facts") is False and not topic.get("news_peg") and not config.ALWAYS_SOURCE:
        return []
    ask = ("Find 1-3 reliable sources about this topic in India: prefer primary ones (regulators, government data, company "
           "filings and results, official announcements, research with a stated method), then major outlets that cite them. "
           "Use WebSearch, then open each page with WebFetch. Look for what is true, including anything that contradicts the "
           "claim; never pick a source only because it agrees. Record each page's publication date from the page itself. "
           "From each page, copy the passages that contain the key facts word for word.\n\n"
           f"Claim: {topic['claim']}\nNews peg: {topic.get('news_peg') or 'none'}\nBehaviour: {topic.get('behaviour', '')}\n\n"
           'Return only JSON: {"sources": [{"url": "...", "fact": "the key fact in one sentence", '
           '"excerpt": "verbatim passages from the page, up to 1200 characters", "date": "the page\'s publication date, YYYY-MM-DD"}]}')
    try:
        out = llm.call_json(config.MODEL_JUDGE, ask, stage="sources", tools=["WebSearch", "WebFetch"], timeout=1200)
        return [s for s in out.get("sources", []) if s.get("url", "").startswith("http") and s.get("excerpt")]
    except SystemExit:
        raise
    except Exception as e:
        state.log("writer", f"source search failed: {e}")
        return []


GENERIC_SEND = re.compile(r"\b(someone who needs|someone you know|(?:a friend|your friends|everyone)\b(?!\s+(?:who|whose)\b))", re.I)


def hard_checks(draft: dict, fmt: str, sources: list[dict]) -> list[str]:
    problems = []
    slides = draft.get("slides", [])
    if fmt == "carousel" and not MIN_SLIDES <= len(slides) <= MAX_SLIDES:
        problems.append(f"Use {MIN_SLIDES} to {MAX_SLIDES} slides, not {len(slides)}: as few as the idea needs.")
    if fmt == "carousel":
        head = re.sub(r"[\[\]]", "", str((draft.get("cover") or {}).get("headline", "")))
        if not 5 <= len(head.split()) <= 13:
            problems.append("The cover needs a headline of 6-12 words (cover.headline), with the key phrase in [brackets].")
        if (draft.get("cover") or {}).get("headline", "").count("[") != 1:
            problems.append("Mark exactly one key phrase in the cover headline with [brackets]; it is shown in teal.")
    if fmt == "carousel" and slides:
        hook = slides[0].get("paragraphs", [""])[0].strip()
        if hook.endswith("?"):
            problems.append("Slide 1 ends on a question. Open with a claim that contains the turn, or two facts that "
                            "shouldn't sit together.")
        dead = [i for i, s in enumerate(slides[:-1], 1) if len(str(s.get("why_swipe", "")).split()) < 3]
        if dead:
            problems.append(f"Slides {dead} have no why_swipe: say what pulls the reader to the next slide, or rewrite "
                            "the slide until something does.")
    send = str((draft.get("end") or {}).get("send", ""))
    if GENERIC_SEND.search(send):
        problems.append("The send line names no specific person: say who it's for and why it's them "
                        "(e.g. 'Send to the friend who complains about café prices from the same café every weekend.').")
    if fmt == "single" and len(slides) != 1:
        problems.append("A single post must have exactly one slide.")
    total = 0
    for i, s in enumerate(slides, 1):
        body = [p for p in s.get("paragraphs", []) if not p.strip().lower().startswith("swipe to read")]
        words = len(" ".join(body).split())
        total += words
        limit = 70 if fmt == "single" else (HOOK_WORDS if i == 1 else SLIDE_WORDS[1])
        if words > limit:
            problems.append(f"Slide {i} has {words} words; the limit is {limit}. It is too much to read on one screen: "
                            "cut an extra example or repeated line, or move a beat to its own slide.")
        if fmt == "carousel" and i > 1 and words < SLIDE_WORDS[0]:
            problems.append(f"Slide {i} is too thin ({words} words); give it a real beat.")
    if fmt == "carousel" and total > POST_WORDS[1]:
        problems.append(f"The post is {total} words; keep it under {POST_WORDS[1]} by cutting extra examples, not the thought.")
    if fmt == "carousel" and total < POST_WORDS[0]:
        problems.append(f"The post is only {total} words; the thought needs room ({POST_WORDS[0]}+).")
    text = post_text(draft)
    shown = " ".join([text, *(str(v) for v in (draft.get("cover") or {}).values() if isinstance(v, str)),
                      *(str(v) for v in (draft.get("end") or {}).values() if isinstance(v, str)), draft.get("caption") or ""])
    for pat in _banned():  # everything the reader sees, cover and end card included
        m = pat.search(shown)
        if m:
            problems.append(f"Remove the phrase '{m.group(0)}'.")
    figures = len(MONEY.findall(text))
    if figures > MAX_FIGURES:
        problems.append(f"The post carries {figures} numbers. Facts only back the opinion: keep {MAX_FIGURES} at most, "
                        "and only where they make the point land.")
    if len(re.findall(r"\bnobody\b", text, re.I)) > 1:
        problems.append("'Nobody' appears more than once; it's the account's most repeated tic. Keep at most one.")
    if fmt == "carousel" and slides:
        middle = "\n".join(" ".join(s.get("paragraphs", [])) for s in slides[1:-1])  # slide 1 restates the cover
        if len(REVERSAL.findall(middle)) > 3:  # a run of them can carry examples ("isn't about marble, it's about the guard")
            problems.append("'Isn't X, it's Y' reversals appear more than three times before the last slide; that rhythm reads "
                            "as a template. Keep the ones that carry an example.")
    copied = corpus.copied_runs(text)
    if copied:
        problems.append(f"These word runs copy the reference creator; rewrite them: {copied[:5]}")
    # Every money/percentage figure must trace to the evidence (sources and the topic's proof), or be a number the
    # writer worked out and declared with its sum (the fact gate checks the arithmetic). The writer's own claim text
    # never counts as backing.
    backed = " ".join(s.get("fact", "") + " " + s.get("excerpt", "") for s in sources) + " " + " ".join(
        c.get("text", "") for c in draft.get("claims", []) if c.get("derived_from"))
    backed_digits = set(re.findall(r"\d[\d,.]*", backed.replace(",", "")))
    for m in MONEY.finditer(text):
        digits = re.findall(r"\d[\d,.]*", m.group(0).replace(",", ""))
        if digits and not all(d.rstrip(".") in {b.rstrip(".") for b in backed_digits} for d in digits):
            problems.append(f"The figure '{m.group(0).strip()}' isn't in the sources; source it or remove it.")
            break
    return problems




CAPTION_STYLES = {
    "question": "a specific question that invites the reader's own version (not a generic 'what do you think?').",
    "pov": "a one-line point of view in his voice, a confession or a dry aside, no question mark.",
}


def caption_style(post: dict) -> str:
    """Alternate caption shapes so the feed doesn't settle into one template, and the scorecard can compare them."""
    return post.get("caption_style") or ("question" if zlib.crc32(post["id"].encode()) % 2 == 0 else "pov")


def approved_posts() -> list[dict]:
    return json.loads((config.DATA / "approved_posts.json").read_text())


def voice_examples(seed: int, k: int = 3) -> str:
    """The owner's story standard, one more owner-approved post and one top post by the reference creator, rotating
    so no single example's scaffolding takes over."""
    bank, rnd = approved_posts(), random.Random(seed)
    standard = [b for b in bank if b.get("standard")]  # the owner's story standard is always shown
    owner = [b for b in bank if b.get("source") != "reference creator" and not b.get("standard")]
    ref = [b for b in bank if b.get("source") == "reference creator"]
    picks = standard + rnd.sample(owner, min(max(2 - len(standard), 1), len(owner)))
    picks += rnd.sample(ref, min(k - len(picks), len(ref)))
    def slides(p: dict) -> list[str]:  # the reference creator's dense slides are shown lighter; owner posts as approved
        return [b for s in p["slides"] for b in corpus.light(s)][:10] if p.get("source") == "reference creator" else p["slides"]
    return "\n\n".join(f"### Example: {p['title']}\n" + "\n\n".join(f"[slide {i}] {s}" for i, s in enumerate(slides(p), 1))
                       for p in picks)


TOPIC_FIELDS = ("claim", "moment", "turn", "because", "payoff", "lived", "proof", "mood", "format_name", "send_to", "news_peg",
                "why_now", "behaviour", "mechanism", "group", "territory", "real_details",
                "feeling", "villain", "story_type")


def evidence_for(post: dict) -> list[dict]:
    """What the writer may state as fact: the saved sources and the topic's proof (each with a URL and a date).
    real_details are texture for a typical scene, never backing for a claim about the world."""
    proof = [{"url": p.get("source_url") or p.get("url", ""), "fact": p.get("fact", ""), "date": p.get("date", ""),
              "excerpt": " ".join(x for x in (p.get("fact", ""), p.get("quote", ""), p.get("date", "")) if x)}
             for p in (post["topic"].get("proof") or []) if isinstance(p, dict)]
    return (post.get("sources") or []) + proof


def length_rules(fmt: str) -> str:
    if fmt == "single":
        return "one slide of 30-70 words."
    return (f"{MIN_SLIDES} to {MAX_SLIDES} slides, as few as the idea needs. Slide 1 up to {HOOK_WORDS} words. Other slides "
            f"{SLIDE_WORDS[0]}-{SLIDE_WORDS[1]} words, at most {MAX_PARAS} short paragraphs. The whole post "
            f"{POST_WORDS[0]}-{POST_WORDS[1]} words.")


def critique(post: dict, draft: dict, seed: int) -> dict:
    topic, fmt = post["topic"], post["format"]
    try:
        return llm.call_json(config.MODEL_JUDGE, llm.fill(
            llm.prompt("critic"), persona=llm.prompt("persona"), post=json.dumps(draft, ensure_ascii=False, indent=1),
            tone_examples=corpus.rhythm_examples(2, seed=seed + 101, fmt=fmt), voice_examples=voice_examples(seed),
            topic=json.dumps({k: topic.get(k) for k in TOPIC_FIELDS}, ensure_ascii=False, indent=1),
            sources=json.dumps(evidence_for(post), ensure_ascii=False, indent=1) or "(none)"), stage="critic")
    except SystemExit:
        raise
    except Exception as e:
        return {"pass": False, "violations": [f"The editor could not run ({e})."], "notes": []}


def passes(review: dict) -> bool:
    """No hard failure, 4+ on craft, and real EQ or IQ: one of them 4+, the other at least 3."""
    scores = review.get("scores") or {}
    keys = ("hook", "relatable", "fresh_angle", "pull", "payoff", "voice", "story", "tight")
    eq, iq = _score(scores, "eq"), _score(scores, "iq")
    return (not review.get("violations") and all(_score(scores, k) >= 4 for k in keys)
            and max(eq, iq) >= 4 and min(eq, iq) >= 3
            and ("informative" not in scores or _score(scores, "informative") >= 3))  # the benchmark teaches something


def write_post(post: dict, notes: str = "") -> dict:
    """Write, check, edit and verify. The writer is the only thing that changes what the post says: the editor and
    the fact gate send notes back to it. `notes` seeds the first attempt (an owner's rewrite request)."""
    from . import factgate, published
    topic = post["topic"]
    seen = published.repeat_of(topic)
    if seen:  # never write a post the page has already made
        post.update(status="rejected", error=f"Repeats a live post: {seen}")
        state.log("writer", f"{post['id']} rejected: repeats '{seen}'")
        return post
    fmt = post["format"] = post["format"] if post["format"] != "spare" else "carousel"
    persona = llm.prompt("persona")
    if post.get("sources") is None:
        post["sources"] = find_sources(topic)
    evidence = evidence_for(post)
    draft = None
    seed = zlib.crc32(post["id"].encode()) % 10_000  # deterministic across runs, unlike hash()
    for attempt in range(config.MAX_REWRITES + 1):
        user = llm.fill(
            llm.prompt("writer"), persona=persona, format_rules=FORMAT_RULES[fmt], length_rules=length_rules(fmt),
            rhythm_examples=corpus.rhythm_examples(3, exclude_territory=topic.get("territory"), seed=seed + attempt, fmt=fmt),
            topic=json.dumps({k: topic.get(k) for k in TOPIC_FIELDS if topic.get(k)}, ensure_ascii=False, indent=1),
            sources=json.dumps(evidence, ensure_ascii=False, indent=1) if evidence else "(none: use no statistics)",
            voice_examples=voice_examples(seed + attempt),
            caption_style=CAPTION_STYLES[caption_style(post)],
            revision_notes=notes,
        )
        draft = llm.call_json(config.MODEL_WRITER, user, stage="write", max_tokens=5000)
        draft, problems = mechanical(draft, fmt, evidence)
        if not problems:
            review = critique(post, draft, seed + attempt)
            post["history"].append({"attempt": attempt, "review": review})
            cut = None if passes(review) else dead_slide(review, len(draft.get("slides", [])))
            if cut:  # one repeated middle slide: cut it and ask again, instead of spending a rewrite on it
                trimmed = json.loads(json.dumps(draft))
                del trimmed["slides"][cut - 1]
                trimmed, left = mechanical(trimmed, fmt, evidence)
                if not left and len(trimmed["slides"]) >= MIN_SLIDES:
                    again = critique(post, trimmed, seed + attempt)
                    post["history"].append({"attempt": attempt, "cut_slide": cut, "review": again})
                    if passes(again):
                        draft, review = trimmed, again
            if passes(review):
                draft["caption_style"] = caption_style(post)
                verification = factgate.verify(post, draft)
                post["history"].append({"attempt": attempt, "verification": verification})
                if verification["passed"]:
                    post.update(status="written", draft=draft, verification=verification)
                    state.log("writer", f"{post['id']} passed on attempt {attempt + 1}")
                    return post
                if verification.get("take_dead"):
                    post.update(status="rejected", draft=draft, verification=verification)
                    state.log("writer", f"{post['id']} rejected: the take's premise is false")
                    return post
                problems = verification["notes"]
            else:
                problems = review.get("violations", []) + review.get("notes", [])[:5]
                if not problems:
                    problems = [f"The editor scored it below 4 on: {', '.join(k for k, v in (review.get('scores') or {}).items() if _score(review['scores'], k) < 4)}."]
        post["history"].append({"attempt": attempt, "problems": problems})
        notes = ("## Your previous draft\n" + json.dumps(draft, ensure_ascii=False, indent=1) +
                 "\n\n## Notes from the editor and fact checker\nEdit the draft above; don't write a new one. Change only "
                 "the lines these notes name, and keep every other line word for word, so nothing that already passed "
                 "breaks. If a fact or mechanism is wrong, rebuild that point on the corrected one rather than deleting it. "
                 "If a note calls a slide dead, or says it restates the cover or another slide, delete that slide (move any "
                 "genuinely new detail into the slide before it); never reword it, because a reworded repeat is still a repeat.\n"
                 + "\n".join(f"- {p}" for p in problems))
        state.log("writer", f"{post['id']} attempt {attempt + 1} failed: {problems[:2]}")
    post.update(status="rejected", draft=draft)  # keep the last draft so a person can read what was rejected
    return post








def dead_slide(review: dict, n: int) -> int | None:
    """The middle slide to cut, when the editor's only hard failure is that one slide repeats another."""
    v = review.get("violations") or []
    if len(v) != 1 or "dead slide" not in v[0].lower():
        return None
    m = re.search(r"\bslide (\d+)", v[0], re.I)
    k = int(m.group(1)) if m else 0
    return k if 2 <= k < n else None


def _score(scores: dict, key: str) -> int:
    try:
        return int(scores.get(key, 0))
    except (TypeError, ValueError):
        return 0
