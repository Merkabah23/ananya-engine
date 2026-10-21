"""Agent 1, the scout: once a month, turn Reddit threads into candidate topics.

Primary source: Reddit's public RSS (engine/reddit.py). If Reddit blocks the runner,
fall back to Claude's own web search over reddit.com.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from . import config, corpus, llm, state
from .reddit import Blocked, Reddit

BATCH = 20             # threads per scout call
COMMENT_THREADS = 40   # comments are fetched for this many of the most promising threads
MIN_THREADS = 30       # below this, also use the web-search fallback


def _informative(t: dict) -> bool:
    """Skip memes and image posts: the scout needs words."""
    return len(t["body"]) >= 200 or len(t["title"].split()) >= 9


def _fetch_rss() -> list[dict]:
    cfg = json.loads((config.DATA / "subreddits.json").read_text())
    rd = Reddit()
    threads: list[dict] = []
    for s in cfg["subreddits"]:
        try:
            got = [t for t in rd.top_threads(s["name"], cfg["per_subreddit"]) if _informative(t)]
        except Blocked as e:
            state.log("scout", f"Reddit blocked this runner ({e}); switching to web search")
            break
        except Exception as e:  # a renamed or private subreddit should not stop the month
            state.log("scout", f"skipped r/{s['name']}: {e}")
            continue
        for t in got:
            t["territory_hint"] = s["territory_hint"]
            t["top_comments"] = []
        threads += got
        state.log("scout", f"r/{s['name']}: {len(got)} usable threads")
    # Best-ranked, wordiest threads first; fetch their comments.
    threads.sort(key=lambda t: (t["rank"], -len(t["body"])))
    for t in threads[:COMMENT_THREADS]:
        try:
            t["top_comments"] = rd.top_comments(t["url"], cfg["comments_per_thread"])
        except Blocked as e:
            state.log("scout", f"comments blocked, continuing without: {e}")
            break
        except Exception as e:
            state.log("scout", f"no comments for {t['id']}: {e}")
    return threads


def _fetch_websearch() -> list[dict]:
    """Fallback: Claude finds last month's high-engagement Indian Reddit discussions itself."""
    cfg = json.loads((config.DATA / "subreddits.json").read_text())
    subs = ", ".join("r/" + s["name"] for s in cfg["subreddits"])
    ask = (f"Search reddit.com for the most-discussed threads from the last 30 days in these Indian subreddits: {subs}. "
           "Focus on everyday life: money, family, relationships, work, cities, social media, films. Skip memes, news and politics. "
           "Find 40 threads. For each, read what you can and summarise the thread and the main themes in its top comments.\n\n"
           'Return only JSON: {"threads": [{"sub": "...", "title": "...", "url": "...", "rank": 1, '
           '"body": "2-4 sentence summary of the post", "top_comments": ["theme or paraphrased comment", "..."]}]}')
    out = llm.call_json(config.MODEL_JUDGE, ask, stage="scout-search", tools=[llm.web_search_tool()], timeout=1800)
    threads = [t for t in out.get("threads", []) if "reddit.com" in t.get("url", "")]
    for t in threads:
        t.setdefault("territory_hint", "any")
        t.setdefault("id", t["url"].rstrip("/").split("/")[-2] if "/comments/" in t["url"] else t["url"])
    state.log("scout", f"web search found {len(threads)} threads")
    return threads


def tired_tropes() -> str:
    lines = (config.DATA / "tired_tropes.txt").read_text().splitlines()
    return "\n".join(f"- {l}" for l in lines if l.strip() and not l.startswith("#"))


NEWS_THEMES = {
    "business": "brand launches, ad campaigns and ad controversies, D2C and startup news, funding and shutdowns, quick commerce, product shortages and queues, brand rivalries, business stories people are discussing",
    "creators": "creator economy and influencer news, Instagram and YouTube changes, viral creators and creator deals, AI tools people actually use, apps and new features, what is trending in India online",
    "screen": "films, OTT shows and music people are watching and arguing about, box office numbers, celebrities and comebacks, cricket moments, memes and online debates",
    "money": "prices people feel (rent, flats, gold, phones, food delivery, groceries), status purchases, sales and spending data, salaries, UPI, banking and tax changes, consumer surveys",
    "life": "dating, marriage, family and friendship, work culture and office life, cities and migration, health and fitness trends, new rules that change daily life, foreign events that say something about India",
}


def _fetch_news() -> list[dict]:
    """What happened in India in the last 30 days, scanned as three themes in parallel."""
    def scan(theme: str) -> list[dict]:
        ask = (f"Search the web for what happened in India in the last 30 days in this area: {NEWS_THEMES[theme]}. "
               "Focus on what urban Indians aged 22-38 are actually talking about. Skip party politics, crime and disasters. "
               "Find 15 distinct items, each with its source.\n\n"
               'Return only JSON: {"items": [{"source": "news", "title": "...", "date": "YYYY-MM-DD", "url": "...", '
               '"body": "3-5 sentences: what happened, the key numbers, and what people are saying about it"}]}')
        return llm.call_json(config.MODEL_JUDGE, ask, stage=f"scout-news-{theme}", tools=[llm.web_search_tool()],
                             timeout=1800).get("items", [])
    results = llm.pmap(scan, list(NEWS_THEMES))
    items, seen = [], set()
    for theme, res in zip(NEWS_THEMES, results):
        if isinstance(res, Exception):
            state.log("scout", f"news scan '{theme}' failed: {res}")
            continue
        for i in res:
            url = i.get("url", "")
            if url.startswith("http") and url not in seen:
                seen.add(url)
                items.append(dict(i, id=f"news-{len(items) + 1}", rank=len(items) + 1, top_comments=[], territory_hint="any"))
    state.log("scout", f"news scan: {len(items)} items")
    return items


def fetch_reddit(month: str | None = None) -> list[dict]:
    """Slow (rate-limited) Reddit fetch, run as its own job the day before the monthly run."""
    month = month or datetime.now(timezone.utc).strftime("%Y-%m")
    cached = state.read(month, "reddit.json")
    if cached is not None:
        return cached
    threads = _fetch_rss()
    if len(threads) < MIN_THREADS:
        threads += _fetch_websearch()
    state.write(threads, month, "reddit.json")
    return threads


def _evergreen(persona: str) -> list[dict]:
    """Big everyday behaviours with a non-obvious reason. No news peg needed; the angle has to be new."""
    ask = llm.fill(llm.prompt("evergreen"), persona=persona, tired_tropes=tired_tropes(), varun_hooks=corpus.all_hooks())
    out = llm.call_json(config.MODEL_JUDGE, ask, stage="scout-evergreen")
    return [dict(t, news_peg=None, evidence=[]) for t in out.get("topics", [])]


def _attach_evidence(topics: list[dict], reddit: list[dict]) -> list[dict]:
    """Reddit as evidence: find threads where real people are living each topic, and take texture from them."""
    if not topics or not reddit:
        return topics
    index = "\n".join(f'{i}: r/{t["sub"]} | {t["title"]} | {t["body"][:140]}' for i, t in enumerate(reddit))
    batches = [topics[i:i + 15] for i in range(0, len(topics), 15)]

    def match_and_extract(batch: list[dict]) -> dict:
        claims = "\n".join(f'{k}: {t["claim"]}' for k, t in enumerate(batch))
        picks = llm.call_json(config.MODEL_JUDGE, (
            "Below are topics for Instagram posts and an index of this month's top Reddit threads from Indian subreddits. "
            "For each topic, list up to 4 threads where real people are clearly living or arguing about that pattern. "
            "Only real matches; most topics will have zero to two.\n\n## Topics\n" + claims + "\n\n## Threads\n" + index +
            '\n\nReturn only JSON: {"matches": [{"topic": 0, "threads": [12, 40]}]}'), stage="evidence-match")
        chosen = {m["topic"]: [i for i in m.get("threads", []) if isinstance(i, int) and 0 <= i < len(reddit)]
                  for m in picks.get("matches", []) if isinstance(m.get("topic"), int)}
        chosen = {k: v for k, v in chosen.items() if v and k < len(batch)}
        if not chosen:
            return {}
        material = "\n\n".join(
            f'## Topic {k}: {batch[k]["claim"]}\n' + "\n".join(
                f'- r/{reddit[i]["sub"]}: {reddit[i]["title"]}\n  {reddit[i]["body"][:900]}\n  Comments: '
                + " | ".join(reddit[i].get("top_comments", [])[:8]) for i in ids)
            for k, ids in chosen.items())
        details = llm.call_json(config.MODEL_JUDGE, (
            "For each topic, pull 2-5 concrete details from its Reddit threads that show how real people live this: "
            "numbers they mention, what was said, what they did. Paraphrase, no usernames, no verbatim quote longer than 8 words, "
            "nothing that is not in the text.\n\n" + material +
            '\n\nReturn only JSON: {"topics": [{"topic": 0, "real_details": ["..."]}]}'), stage="evidence-details")
        found = {d["topic"]: d.get("real_details", []) for d in details.get("topics", []) if isinstance(d.get("topic"), int)}
        return {k: (ids, found.get(k, [])) for k, ids in chosen.items()}

    for batch, res in zip(batches, llm.pmap(match_and_extract, batches)):
        if isinstance(res, Exception):
            state.log("scout", f"evidence step failed for a batch: {res}")
            continue
        for k, (ids, details) in res.items():
            t = batch[k]
            t["real_details"] = (t.get("real_details") or []) + details
            t["evidence"] = (t.get("evidence") or []) + [
                {"url": reddit[i]["url"], "sub": reddit[i]["sub"], "rank": reddit[i]["rank"]} for i in ids]
    return topics


def run(month: str | None = None) -> list[dict]:
    """Culture first: topics come from what India is watching, buying and arguing about, plus evergreen
    observations. Reddit is then used as evidence and texture, never as the origin of a topic."""
    month = month or datetime.now(timezone.utc).strftime("%Y-%m")
    news = state.read(month, "news.json")
    if news is None:
        news = _fetch_news()
        state.write(news, month, "news.json")
    reddit = [t for t in fetch_reddit(month) if "reddit.com" in t.get("url", "")]
    persona = llm.prompt("persona")
    prompt_head = llm.fill(llm.prompt("scout"), persona=persona, tired_tropes=tired_tropes()) + "\n\n## Items\n"
    batches = [news[i:i + BATCH] for i in range(0, len(news), BATCH)]
    jobs = [lambda b=b: llm.call_json(config.MODEL_JUDGE, prompt_head + json.dumps(b, ensure_ascii=False, indent=1),
                                      stage="scout") for b in batches] + [lambda: {"topics": _evergreen(persona)}]
    topics: list[dict] = []
    for n, out in enumerate(llm.pmap(lambda job: job(), jobs), 1):
        if isinstance(out, Exception):
            state.log("scout", f"scout job {n} failed: {out}")
            continue
        topics += out.get("topics", [])
        state.log("scout", f"scout job {n}: {len(out.get('topics', []))} topics")
    topics = _attach_evidence(topics, reddit)
    for i, t in enumerate(topics, 1):
        t["id"] = f"{month}-{i:03d}"
    state.write(topics, month, "candidates.json")
    backed = sum(1 for t in topics if any("reddit.com" in e.get("url", "") for e in t.get("evidence", [])))
    state.log("scout", f"{len(topics)} candidate topics from {len(news)} news items; {backed} backed by Reddit threads")
    return topics
