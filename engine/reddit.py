"""Read the month's top threads and their top comments from Reddit's public RSS feeds.

No app or key needed. Feeds are listed best-first, so a thread's rank stands in for its
upvotes (RSS doesn't carry vote counts). Requests are spaced out because Reddit rate-limits
anonymous clients hard; a 429 triggers a long back-off.
"""
from __future__ import annotations

import html
import re
import time

import requests

UA = "Mozilla/5.0 (compatible; ananya-engine/0.2; monthly topic research)"
GAP_SECONDS = 30          # between any two requests (Reddit 429s anonymous clients after ~10s gaps)
BACKOFF = [90, 240, 600]  # after a 429


class Blocked(Exception):
    pass


def _get(url: str) -> str:
    for wait in [0] + BACKOFF:
        if wait:
            time.sleep(wait)
        r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
        time.sleep(GAP_SECONDS)
        if r.status_code == 200:
            return r.text
        if r.status_code in (403, 401):
            raise Blocked(f"{r.status_code} for {url}")
        if r.status_code != 429:
            r.raise_for_status()
    raise Blocked(f"still rate-limited after back-off: {url}")


def _clean(fragment: str) -> str:
    text = html.unescape(html.unescape(fragment))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"submitted by\s+/u/\S+.*$", "", text, flags=re.S)  # drop the RSS footer
    return re.sub(r"\s+", " ", text).strip()


def _entries(xml: str) -> list[dict]:
    out = []
    for e in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
        title = re.search(r"<title>(.*?)</title>", e, re.S)
        link = re.search(r'<link href="(.*?)"', e)
        content = re.search(r'<content type="html">(.*?)</content>', e, re.S)
        out.append({"title": html.unescape(title.group(1)).strip() if title else "",
                    "url": link.group(1) if link else "",
                    "text": _clean(content.group(1)) if content else ""})
    return out


class Reddit:
    def top_threads(self, sub: str, limit: int, min_upvotes: int = 0) -> list[dict]:
        xml = _get(f"https://www.reddit.com/r/{sub}/top/.rss?t=month&limit={limit}")
        out = []
        for rank, e in enumerate(_entries(xml), 1):
            if "/comments/" not in e["url"]:
                continue
            out.append({"id": e["url"].split("/comments/")[1].split("/")[0], "sub": sub, "rank": rank,
                        "title": e["title"], "body": e["text"][:1500], "url": e["url"]})
        return out

    def top_comments(self, thread_url: str, n: int) -> list[str]:
        xml = _get(thread_url.rstrip("/") + f"/.rss?sort=top&limit={n + 1}")
        ents = _entries(xml)[1:]  # first entry is the post itself
        return [e["text"][:500] for e in ents if e["text"] and e["text"] not in ("[deleted]", "[removed]")][:n]
