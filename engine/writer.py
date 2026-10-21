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
    "carousel": "a carousel of 4 or 5 slides. Slide 1 is at most 25 words and ends with 'Swipe to read →'.",
    "single": "a single slide of at most 110 words: either a list ('Every Indian ___ has:' then 8-10 short lines starting with '- ') or a short open letter ('Dear ___,'). No 'Swipe to read'.",
}
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
            if len(paras) > 3:
                problems.append(f"Slide {i} has {len(paras)} paragraphs; use at most 3.")
            if any("**" in p for p in paras):
                problems.append(f"Slide {i} uses bold (**). The house style has no bold; remove it.")
            italics = sum(p.count("*") // 2 for p in paras)
            if italics > 1:
                problems.append(f"Slide {i} has {italics} italic phrases; use at most one, only where it's needed.")
        for p in paras:
            if fmt == "single" and p.lstrip().startswith("-"):
                continue  # list items are fragments by design
            sents = sentences(p)
            if len(sents) > 2 and fmt == "carousel":
                problems.append(f"Slide {i}: a paragraph has more than 2 sentences; split it.")
            for x in sents:
                n = len(x.split())
                if n > 18:
                    problems.append(f"Slide {i}: this sentence has {n} words, max 18: '{x[:70]}...'")
    words = [len(x.split()) for s in draft.get("slides", []) for p in s.get("paragraphs", [])
             for x in sentences(p) if not x.lower().startswith("swipe")]
    if fmt == "carousel" and words and sum(words) / len(words) > 12:
        problems.append(f"Average sentence is {sum(words) / len(words):.1f} words; keep it at 12 or under.")
    return problems[:6]


def verify_facts(draft: dict, sources: list[dict]) -> list[str]:
    """Check every factual statement in the post against the saved source excerpts (no re-fetching)."""
    text = post_text(draft)
    if not re.search(r"\d|[A-Z][a-z]+ [A-Z][a-z]+", text):
        return []  # no numbers or proper names: nothing to verify
    excerpts = "\n\n".join(f"[{i + 1}] {s['url']}\n{s.get('excerpt') or s.get('fact', '')}" for i, s in enumerate(sources))
    ask = ("You are a strict fact checker. Below are a post and the exact text of its sources. Check EVERY factual statement "
           "in the post that a source could confirm or refute: numbers, percentages, prices, ranks, dates, names, titles and roles, "
           "product details, quotes, and specific events. It passes only if a source excerpt says it, with the same meaning and "
           "no stronger wording (\"captain\" is not \"all-format captain\"; \"in the first hour\" is not \"this sale\"). "
           "Do NOT check commentary: the writer's observations, interpretations and opinions about how people feel, behave or "
           "react (\"we were furious\", \"nobody wants to admit it\", \"the real reason is...\") are her voice, not facts. "
           "Vague time words like \"this month\" or \"lately\" are fine.\n\n"
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
           "Do not rewrite anything else. Keep every slide's meaning and voice. "
           "No bold anywhere; at most one *italic* phrase per slide. Sentences of 18 words or fewer, at most 2 sentences per paragraph, "
           "at most 3 paragraphs per slide (when you split a sentence, keep it in the same paragraph if that stays within 2 sentences), "
           "slide 1 at most 25 words plus 'Swipe to read →'.\n\n"
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
    """Join adjacent short paragraphs until each carousel slide has at most 3. Text is unchanged, only the breaks move.

    Splitting long sentences (a repair) tends to add paragraphs, so this runs after every repair."""
    if fmt != "carousel":
        return draft
    for s in draft.get("slides", []):
        paras = s.get("paragraphs", [])
        tail = [p for p in paras if p.strip().lower().startswith("swipe to read")]
        body = [p for p in paras if p not in tail]
        while len(body) > 3:
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


def hard_checks(draft: dict, fmt: str, sources: list[dict]) -> list[str]:
    problems = []
    slides = draft.get("slides", [])
    if fmt == "carousel" and not 4 <= len(slides) <= 5:
        problems.append(f"Use 4 or 5 slides, not {len(slides)}. Cut, don't pad.")
    if fmt == "single" and len(slides) != 1:
        problems.append("A single post must have exactly one slide.")
    total = 0
    for i, s in enumerate(slides, 1):
        body = [p for p in s.get("paragraphs", []) if not p.strip().lower().startswith("swipe to read")]
        words = len(" ".join(body).split())
        total += words
        limit = 110 if fmt == "single" else (25 if i == 1 else 55)
        if words > limit:
            problems.append(f"Slide {i} has {words} words; the limit is {limit}. Cut the weakest sentence.")
        if fmt == "carousel" and i > 1 and words < 12:
            problems.append(f"Slide {i} is too thin ({words} words).")
    if fmt == "carousel" and total > 220:
        problems.append(f"The post is {total} words; keep it under 220. It reads as a drag.")
    text = post_text(draft)
    for pat in _banned():
        m = pat.search(text)
        if m:
            problems.append(f"Remove the phrase '{m.group(0)}'.")
    if len(re.findall(r"\bit'?s not\b[^.]{0,60}\bit'?s\b", text, re.I)) > 1:
        problems.append("'It's not X, it's Y' appears more than once; keep at most one.")
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


def blind_test(draft: dict, seed: int, trials: int | None = None) -> tuple[bool, list[str]]:
    """True if the judge failed to spot the draft among real posts in most trials."""
    trials = trials or config.BLIND_TEST_TRIALS
    spotted, tells = 0, []
    for trial in range(trials):
        real = corpus.blind_samples(3, seed + trial)
        items = real + [post_text(draft)]
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


def write_post(post: dict) -> dict:
    topic, fmt = post["topic"], post["format"] if post["format"] != "spare" else "carousel"
    persona = llm.prompt("persona")
    sources = post.get("sources") if post.get("sources") is not None else find_sources(topic)
    post["sources"] = sources
    notes = ""
    seed = zlib.crc32(post["id"].encode()) % 10_000  # deterministic across runs, unlike hash()
    for attempt in range(config.MAX_REWRITES + 1):
        user = llm.fill(
            llm.prompt("writer"), persona=persona, format_rules=FORMAT_RULES[fmt],
            rhythm_examples=corpus.rhythm_examples(3, exclude_territory=topic.get("territory"), seed=seed + attempt),
            topic=json.dumps({k: topic.get(k) for k in ("claim", "news_peg", "why_now", "behaviour", "mechanism", "group", "real_details")},
                             ensure_ascii=False, indent=1),
            sources=json.dumps(sources, ensure_ascii=False, indent=1) if sources else "(none: use no numbers)",
            revision_notes=notes,
        )
        draft = llm.call_json(config.MODEL_WRITER, user, stage="write", max_tokens=4000)
        draft, problems = mechanical(draft, fmt, sources)
        if not problems:
            # Critic and fact check are independent: run them at the same time.
            critic_job = lambda _: llm.call_json(config.MODEL_JUDGE, llm.fill(
                llm.prompt("critic"), persona=persona, post=json.dumps(draft, ensure_ascii=False, indent=1),
                topic=json.dumps(topic, ensure_ascii=False, indent=1),
                sources=json.dumps(sources, ensure_ascii=False, indent=1) if sources else "(none)"), stage="critic")
            review, facts = llm.pmap(lambda job: job(None), [critic_job, lambda _: verify_facts(draft, sources)], workers=2)
            if isinstance(review, Exception):
                review = {"pass": False, "violations": [f"critic failed: {review}"], "edits": []}
            if isinstance(facts, Exception):
                facts = [f"Fact check failed ({facts}); remove any statement that needs a source."]
            if facts:  # targeted repair, then re-check; a full rewrite only if that fails
                draft, mech = mechanical(repair(draft, facts, sources), fmt, sources)
                facts = mech or verify_facts(draft, sources)
            post["history"].append({"attempt": attempt, "review": review, "facts": facts})
            if review.get("pass") and not facts:
                last = attempt == config.MAX_REWRITES
                human, tells = blind_test(draft, seed + attempt, trials=2 if last else None)
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
    post["status"] = "rejected"
    return post
