"""Agent 1, the scout: once a month, turn Reddit threads into candidate topics.

Primary source: Reddit's public RSS (engine/reddit.py). If Reddit blocks the runner,
fall back to Claude's own web search over reddit.com.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from . import config, llm, state
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
    "culture": "film, OTT and music hits and their numbers, celebrity and cricket moments, viral clips and online debates",
    "money": "prices, product launches, shortages and queues, sales and spending data, gold, rents, UPI and banking changes, consumer surveys",
    "life": "work and jobs, salaries and layoffs, marriage, dating and family surveys, housing, screen time, health trends, new rules that change daily life, foreign events that say something about India",
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


def run(month: str | None = None) -> list[dict]:
    month = month or datetime.now(timezone.utc).strftime("%Y-%m")
    threads = state.read(month, "threads.json")
    if threads is None:
        threads = _fetch_news() + fetch_reddit(month)  # fresh events first; Reddit is usually cached from yesterday
        state.write(threads, month, "threads.json")
    persona = llm.prompt("persona")
    template = llm.prompt("scout")
    batches = [threads[i:i + BATCH] for i in range(0, len(threads), BATCH)]
    prompt_head = llm.fill(template, persona=persona, tired_tropes=tired_tropes()) + "\n\n## Items\n"
    results = llm.pmap(lambda b: llm.call_json(config.MODEL_JUDGE, prompt_head + json.dumps(b, ensure_ascii=False, indent=1),
                                               stage="scout"), batches)
    topics: list[dict] = []
    for n, out in enumerate(results, 1):
        if isinstance(out, Exception):
            state.log("scout", f"batch {n} failed: {out}")
            continue
        for t in out.get("topics", []):
            t["id"] = f"{month}-{len(topics) + 1:03d}"
            topics.append(t)
        state.log("scout", f"batch {n}: {len(out.get('topics', []))} topics")
    state.write(topics, month, "candidates.json")
    state.log("scout", f"{len(topics)} candidate topics from {len(threads)} threads")
    return topics
