"""Agent 3, the writer (Ananya persona), with its critic loop.

sources (searched and fetched once) -> draft -> code checks -> critic + fact check (in parallel)
-> blind AI-spotting test
Fails send specific notes back to the writer, up to MAX_REWRITES times.
"""
from __future__ import annotations

import json
import random
import re
import zlib

from . import config, corpus, llm, state

FORMAT_RULES = {
    "carousel": "a carousel of 5 to 8 slides. Slide 1 is at most 55 words and ends with 'Swipe to read →'.",
    "single": "a single slide of 30-120 words, like a post someone types straight out of their head: a blunt take or "
              "prediction about India or this generation, a short rant, a satire list ('Literally everyone around me is:' "
              "then short lines starting with '- '), or a short open letter ('Dear ___,'). No 'Swipe to read'.",
}
MAX_PARAS = 5            # per carousel slide
MAX_SENTS_PER_PARA = 6
MAX_SENT_WORDS = 32
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
            if any("**" in p for p in paras):
                problems.append(f"Slide {i} uses bold (**). The house style has no bold; remove it.")
            italics = sum(p.count("*") // 2 for p in paras)
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
    if fmt == "carousel" and words and sum(words) / len(words) > 15:
        problems.append(f"Average sentence is {sum(words) / len(words):.1f} words; keep it at 15 or under.")
    return problems[:6]


def verify_facts(draft: dict, sources: list[dict]) -> list[str]:
    """Check every factual statement in the post against the saved source excerpts (no re-fetching)."""
    text = post_text(draft)
    if not re.search(r"\d|[A-Z][a-z]+ [A-Z][a-z]+", text):
        return []  # no numbers or proper names: nothing to verify
    excerpts = "\n\n".join(f"[{i + 1}] {s['url']}\n{s.get('excerpt') or s.get('fact', '')}" for i, s in enumerate(sources))
    ask = ("You are a strict fact checker. Below are a post and the exact text of its sources. Many posts are a standalone "
           "observation about everyday Indian life and need no source at all. Check ONLY specific, checkable claims about the "
           "world: statistics and percentages, prices and amounts presented as real figures, ranks, dates, named people, "
           "companies, products and their details, titles and roles, quotes, and specific events (a launch, a rule, a release). "
           "Those pass only if a source excerpt says it, with the same meaning and no stronger wording (\"captain\" is not "
           "\"all-format captain\"; \"in the first hour\" is not \"this sale\").\n"
           "Do NOT check, and never flag: observations and opinions about how people live, feel, behave or react; typical "
           "scenarios framed as typical (\"two people with normal jobs in Bangalore\", \"both paying rent for years\", \"it usually "
           "goes like this\"); cities and places used as a setting; everyday ages and durations (\"in your mid-20s\", \"for years\"); "
           "illustrative round numbers in a typical scenario; vague time words (\"this month\", \"lately\"); and what anyone can see "
           "for themselves on a named app, shop or ad (\"the sale banner never goes away\", \"five QR codes on the counter\"). Those "
           "are the writer's voice, not facts. DO check claims about how a named company works on the inside (how a badge is "
           "decided, what a team does, why a price is set) when stated as fact rather than opinion.\n\n"
           f"## Post\n{text}\n\n## Source excerpts\n{excerpts or '(no sources)'}\n\n"
           'Return only JSON: {"unsupported": [{"statement": "...", "why": "what the sources actually say, or that none covers it"}]}')
    try:
        out = llm.call_json(config.MODEL_JUDGE, ask, stage="factcheck")
    except SystemExit:
        raise
    except Exception as e:
        return [f"Fact check could not run ({e}); remove any statement that needs a source."]
    return [f"Unsupported fact: '{u.get('statement')}' ({u.get('why')}). Fix it to match the source or cut it."
            for u in out.get("unsupported", [])]


def repair(draft: dict, problems: list[str], sources: list[dict]) -> dict:
    """Smallest possible edit that fixes the listed problems. Fast model; content and voice stay as they are."""
    ask = ("Edit this Instagram carousel draft to fix ONLY the problems listed. Make the smallest change that fixes each one: "
           "split a long sentence, remove a ** bold marker, cut or reword a single phrase. For an unsupported fact, restate it "
           "exactly as a source says it, or delete the sentence; never replace it with a new scene, person, event or quote. "
           "Do not rewrite anything else. Keep every slide's meaning and voice. After any cut, re-read the slide: every "
           "sentence must still be complete and follow from the one before it. "
           f"No bold anywhere; at most one *italic* phrase per slide. Sentences of {MAX_SENT_WORDS} words or fewer, "
           f"at most {MAX_SENTS_PER_PARA} sentences per paragraph, at most {MAX_PARAS} paragraphs per slide "
           "(when you split a sentence, keep it in the same paragraph), slide 1 at most 55 words plus 'Swipe to read →'.\n\n"
           "## Problems\n" + "\n".join(f"- {p}" for p in problems) +
           "\n\n## Sources\n" + (json.dumps(sources, ensure_ascii=False, indent=1) if sources else "(none: remove unsupported facts)") +
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


def mechanical(draft: dict, fmt: str, sources: list[dict], rounds: int = 3) -> tuple[dict, list[str]]:
    """Code checks with quick repairs in between. Does not use up a rewrite attempt."""
    draft = merge_paragraphs(draft, fmt)
    problems = hard_checks(draft, fmt, sources) + readability_problems(draft, fmt)
    for _ in range(rounds):
        if not problems:
            break
        draft = merge_paragraphs(repair(draft, problems, sources), fmt)
        problems = hard_checks(draft, fmt, sources) + readability_problems(draft, fmt)
    return draft, problems


def find_sources(topic: dict) -> list[dict]:
    """Find sources AND save the relevant text of each page, once. The writer may only use these excerpts."""
    if not topic.get("needs_facts") and not topic.get("news_peg"):
        return []
    ask = ("Find 1-3 reliable, recent sources (news outlets, government data, company filings, reputable surveys) about this "
           "topic in India. Use WebSearch, then open each page with WebFetch. Include at least one source that confirms the "
           "news peg itself, if there is one. From each page, copy the passages that contain the key facts word for word.\n\n"
           f"Claim: {topic['claim']}\nNews peg: {topic.get('news_peg') or 'none'}\nBehaviour: {topic.get('behaviour', '')}\n\n"
           'Return only JSON: {"sources": [{"url": "...", "fact": "the key fact in one sentence", '
           '"excerpt": "verbatim passages from the page, up to 1200 characters"}]}')
    try:
        out = llm.call_json(config.MODEL_JUDGE, ask, stage="sources", tools=["WebSearch", "WebFetch"], timeout=1200)
        return [s for s in out.get("sources", []) if s.get("url", "").startswith("http") and s.get("excerpt")]
    except SystemExit:
        raise
    except Exception as e:
        state.log("writer", f"source search failed: {e}")
        return []


def balance_problems(slides: list[dict]) -> list[str]:
    """Slides after the hook should carry similar weight. Bounds cover 90% of the reference creator's slides."""
    words = [len(" ".join(s.get("paragraphs", [])).split()) for s in slides[1:]]
    if len(words) < 3:
        return []
    mid = sorted(words)[len(words) // 2]
    return [f"Slide {i} has {w} words while most slides have about {mid}; balance it with the others."
            for i, w in enumerate(words, 2) if w > 1.8 * mid or w < 0.4 * mid]


def hard_checks(draft: dict, fmt: str, sources: list[dict]) -> list[str]:
    problems = []
    slides = draft.get("slides", [])
    if fmt == "carousel" and not 5 <= len(slides) <= 8:
        problems.append(f"Use 5 to 8 slides, not {len(slides)}.")
    if fmt == "single" and len(slides) != 1:
        problems.append("A single post must have exactly one slide.")
    total = 0
    for i, s in enumerate(slides, 1):
        body = [p for p in s.get("paragraphs", []) if not p.strip().lower().startswith("swipe to read")]
        words = len(" ".join(body).split())
        total += words
        limit = 120 if fmt == "single" else (55 if i == 1 else 85)
        if words > limit:
            problems.append(f"Slide {i} has {words} words; the limit is {limit}. Cut the explaining, keep the example.")
        if fmt == "carousel" and i > 1 and words < 20:
            problems.append(f"Slide {i} is too thin ({words} words); give it a real example.")
    if fmt == "carousel" and total > 550:
        problems.append(f"The post is {total} words; keep it under 550 by cutting explanation, not examples.")
    problems += balance_problems(slides) if fmt == "carousel" else []
    text = post_text(draft)
    for pat in _banned():
        m = pat.search(text)
        if m:
            problems.append(f"Remove the phrase '{m.group(0)}'.")
    if len(re.findall(r"\bit'?s not\b[^.]{0,60}\bit'?s\b", text, re.I)) > 2:
        problems.append("'It's not X, it's Y' appears more than twice; keep at most two.")
    copied = corpus.copied_runs(text)
    if copied:
        problems.append(f"These word runs copy the reference creator; rewrite them: {copied[:5]}")
    # Every money/percentage figure must trace to the sources: its digits must appear in a source fact
    # or in a claim that cites a source URL we actually have.
    source_urls = {s["url"] for s in sources}
    backed = " ".join(s.get("fact", "") + " " + s.get("excerpt", "") for s in sources) + " " + " ".join(
        c.get("text", "") for c in draft.get("claims", []) if c.get("source_url") in source_urls)
    backed_digits = set(re.findall(r"\d[\d,.]*", backed.replace(",", "")))
    for m in MONEY.finditer(text):
        digits = re.findall(r"\d[\d,.]*", m.group(0).replace(",", ""))
        if digits and not all(d.rstrip(".") in {b.rstrip(".") for b in backed_digits} for d in digits):
            problems.append(f"The figure '{m.group(0).strip()}' isn't in the sources; source it or remove it.")
            break
    return problems


def blind_test(draft: dict, seed: int, trials: int | None = None, fmt: str = "carousel") -> tuple[bool, list[str]]:
    """True if the judge failed to spot the draft among real posts in most trials."""
    trials = trials or config.BLIND_TEST_TRIALS
    spotted, tells = 0, []
    ours = "\n\n".join(" ".join(s["paragraphs"]) for s in draft.get("slides", [])).replace("*", "")
    for trial in range(trials):
        real = corpus.blind_samples(3, seed + trial, fmt)
        items = real + [ours]
        order = list(range(len(items)))
        random.Random(seed + trial).shuffle(order)
        shown = "\n\n".join(f"=== Post {n + 1} ===\n{items[i]}" for n, i in enumerate(order))
        out = llm.call_json(config.MODEL_JUDGE, llm.fill(llm.prompt("blindtest"), n=str(len(items)), posts=shown),
                            stage="blindtest", max_tokens=800)
        guess = int(out.get("ai_post", 0)) - 1
        if 0 <= guess < len(order) and order[guess] == len(items) - 1:
            spotted += 1
            tells += out.get("tells", [])
    return spotted <= trials // 2 if trials > 1 else spotted == 0, tells


def approved_posts() -> list[dict]:
    return json.loads((config.DATA / "approved_posts.json").read_text())


def voice_examples(seed: int, k: int = 3) -> str:
    """A rotating few examples: one owner-approved post plus top posts by the reference creator, so no single
    example's scaffolding takes over."""
    bank, rnd = approved_posts(), random.Random(seed)
    owner = [b for b in bank if b.get("source") != "reference creator"]
    ref = [b for b in bank if b.get("source") == "reference creator"]
    picks = rnd.sample(owner, min(1, len(owner)))
    picks += rnd.sample(ref, min(k - len(picks), len(ref)))
    return "\n\n".join(f"### Example: {p['title']}\n" + "\n\n".join(f"[slide {i}] {s}" for i, s in enumerate(p["slides"], 1))
                       for p in picks)


def write_post(post: dict) -> dict:
    topic, fmt = post["topic"], post["format"] if post["format"] != "spare" else "carousel"
    persona = llm.prompt("persona")
    sources = post.get("sources") if post.get("sources") is not None else find_sources(topic)
    post["sources"] = sources
    # The topic's real_details are the post's evidence too: checks treat them as a source, so texture
    # taken from them ("the portfolio crosses 25 lakhs") isn't rejected as unsourced.
    details = topic.get("real_details") or []
    evidence = sources + ([{"url": "topic", "fact": "What people reported (real_details)", "excerpt": "\n".join(details)}]
                          if details else [])
    notes = ""
    seed = zlib.crc32(post["id"].encode()) % 10_000  # deterministic across runs, unlike hash()
    for attempt in range(config.MAX_REWRITES + 1):
        user = llm.fill(
            llm.prompt("writer"), persona=persona, format_rules=FORMAT_RULES[fmt],
            rhythm_examples=corpus.rhythm_examples(3, exclude_territory=topic.get("territory"), seed=seed + attempt, fmt=fmt),
            topic=json.dumps({k: topic.get(k) for k in ("claim", "mood", "news_peg", "why_now", "behaviour", "mechanism", "group", "territory", "real_details")},
                             ensure_ascii=False, indent=1),
            sources=json.dumps(sources, ensure_ascii=False, indent=1) if sources else "(none: use no statistics)",
            voice_examples=voice_examples(seed + attempt),
            revision_notes=notes,
        )
        draft = llm.call_json(config.MODEL_WRITER, user, stage="write", max_tokens=4000)
        draft, problems = mechanical(draft, fmt, evidence)
        if not problems:
            # Critic and fact check are independent: run them at the same time.
            critic_job = lambda _: llm.call_json(config.MODEL_JUDGE, llm.fill(
                llm.prompt("critic"), persona=persona, post=json.dumps(draft, ensure_ascii=False, indent=1),
                tone_examples=corpus.rhythm_examples(2, seed=seed + 101, fmt=fmt),
                voice_examples=voice_examples(seed + attempt),
                topic=json.dumps(topic, ensure_ascii=False, indent=1),
                sources=json.dumps(sources, ensure_ascii=False, indent=1) if sources else "(none)"), stage="critic")
            review, facts = llm.pmap(lambda job: job(None), [critic_job, lambda _: verify_facts(draft, evidence)], workers=2)
            if isinstance(review, Exception):
                review = {"pass": False, "violations": [f"critic failed: {review}"], "edits": []}
            if isinstance(facts, Exception):
                facts = [f"Fact check failed ({facts}); remove any statement that needs a source."]
            if facts:  # targeted repair, then re-check; a full rewrite only if that fails
                draft, mech = mechanical(repair(draft, facts, evidence), fmt, evidence)
                facts = mech or verify_facts(draft, evidence)
            post["history"].append({"attempt": attempt, "review": review, "facts": facts})
            scores = review.get("scores", {})
            strong = (not review.get("violations") and _score(scores, "hook") >= 3 and _score(scores, "mechanism") >= 3)
            if strong and not facts and review.get("edits"):
                # Polish notes get one quick edit, never a full rewrite that invents new problems.
                polished, mech = mechanical(repair(draft, review["edits"][:5], evidence), fmt, evidence)
                if not mech:
                    draft = polished
            if (review.get("pass") or strong) and not facts:
                last = attempt == config.MAX_REWRITES
                human, tells = (blind_test(draft, seed + attempt, trials=2 if last else None, fmt=fmt)
                                if config.USE_BLIND_TEST else (True, []))
                if human:
                    post.update(status="written", draft=draft, format=fmt)
                    state.log("writer", f"{post['id']} passed on attempt {attempt + 1}")
                    return post
                problems = [f"An editor could tell this was AI-written: {t}" for t in tells[:4]]
            else:
                problems = facts + review.get("violations", []) + ([] if review.get("pass") else review.get("edits", [])[:5])
        post["history"].append({"attempt": attempt, "problems": problems})
        notes = ("## Your previous draft\n" + json.dumps(draft, ensure_ascii=False, indent=1) +
                 "\n\n## Revision notes from the editor (fix every one, keep what works)\n" + "\n".join(f"- {p}" for p in problems))
        state.log("writer", f"{post['id']} attempt {attempt + 1} failed: {problems[:2]}")
    post.update(status="rejected", draft=draft)  # keep the last draft so a person can read what was rejected
    return post


def _score(scores: dict, key: str) -> int:
    try:
        return int(scores.get(key, 0))
    except (TypeError, ValueError):
        return 0
