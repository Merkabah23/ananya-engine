"""The caption and hashtags, written as their own step after the slides pass.

Owner, 11 Nov: the posts are good, the caption and hashtag game isn't. Before this the writer added a one-line caption
as an afterthought: it often repeated the cover, carried no words a reader would search for, had dropped the send ask,
and its "I" failed whole slide drafts. Now the caption has a fixed shape (a sharper line, at most two lines of because,
one ask), code checks, and its own small fix loop, so a caption problem never costs a slide rewrite.

Hashtags: three. One for exactly this post, one from the territory's bank (rotated so the same tag doesn't sit on the
feed all week), and the brand tag. Instagram has capped posts at five since Dec 2025, and treats tags as labels, not
reach; the words in the caption are what search reads.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from . import config, llm, state

TERRITORY_TAGS = {
    "business_brands": ["#IndianBrands", "#MarketingIndia", "#StartupIndia", "#BrandStrategy"],
    "money_status": ["#PersonalFinanceIndia", "#MiddleClassIndia", "#MoneyHabits", "#ConsumerBehaviour"],
    "world_geopolitics": ["#WorldNews", "#Geopolitics", "#IndiaAndTheWorld", "#GlobalEconomy"],
    "life_relationships": ["#IndianFamily", "#DesiParents", "#IndianSiblings", "#Friendship"],
    "sports": ["#IndianCricket", "#SportsBusiness", "#SportsIndia", "#FanCulture"],
    "pop_culture": ["#Bollywood", "#IndianCinema", "#OTTIndia", "#PopCultureIndia"],
    "creators_internet": ["#CreatorEconomy", "#InternetCulture", "#DigitalIndia", "#SocialMediaIndia"],
}
DEFAULT_TAGS = ["#IndianLife", "#EverydayIndia"]
BANNED_TAGS = {t.lower() for t in ("#viral", "#trending", "#explore", "#explorepage", "#fyp", "#foryou", "#reels",
                                   "#instagood", "#motivation", "#life", "#india", "#love", "#instadaily", "#aboveMRP")}
LINE_MAX, BODY_MAX, TOTAL_MAX = 125, 140, 450
FIRST_PERSON = re.compile(r"\b(I|I'm|I've|I'd|I'll|me|my|mine)\b")
STOCK = re.compile(r"link in bio|follow for more|comment below|tag a friend|tag someone|double tap|thoughts\?|agree\?|—", re.I)
EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")
TAG = re.compile(r"^#[A-Z][A-Za-z0-9]{2,29}$")


def _slides(draft: dict) -> list[str]:
    return [" ".join(s.get("paragraphs", [])) for s in draft.get("slides", [])]


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z₹0-9']+", text.lower()) if len(w) > 2}


def territory_tag(post: dict) -> str:
    """The territory's least-used tag among posts due within a week either side, so the feed doesn't wear one label."""
    bank = TERRITORY_TAGS.get((post.get("topic") or {}).get("territory", ""), DEFAULT_TAGS)
    try:
        due = datetime.fromisoformat(post["due"])
    except (KeyError, TypeError, ValueError):
        return bank[0]
    used: dict[str, int] = {}
    for p in state.posts():
        if p.get("id") == post.get("id") or not p.get("due") or p.get("status") in ("rejected", "cancelled"):
            continue
        try:
            near = abs(datetime.fromisoformat(p["due"]) - due) <= timedelta(days=7)
        except ValueError:
            continue
        if near:
            for t in (p.get("draft") or {}).get("hashtags") or []:
                used[str(t).lower()] = used.get(str(t).lower(), 0) + 1
    return min(bank, key=lambda t: (used.get(t.lower(), 0), bank.index(t)))


def assemble(c: dict) -> str:
    body = [b.strip() for b in (c.get("body") or []) if str(b).strip()][:2]
    return "\n\n".join([c.get("line", "").strip(), *body, c.get("ask", "").strip()]).strip()


def problems(post: dict, draft: dict, c: dict) -> list[str]:
    """Code checks on a caption. Each problem is phrased so the caption call can fix it."""
    out = []
    line, ask, body = c.get("line", "").strip(), c.get("ask", "").strip(), [str(b) for b in (c.get("body") or [])]
    text = assemble(c)
    slides = _slides(draft)
    if not line:
        return ["There is no line."]
    if len(line) > LINE_MAX:
        out.append(f"The line is {len(line)} characters; keep it under {LINE_MAX} so all of it shows before 'more'.")
    if len(body) > 2 or any(len(b) > BODY_MAX for b in body):
        out.append(f"Body: at most two lines, each under {BODY_MAX} characters.")
    if len(text) > TOTAL_MAX:
        out.append(f"The caption is {len(text)} characters; keep it under {TOTAL_MAX}.")
    if slides:
        first = _words(slides[0])
        overlap = len(_words(line) & first) / max(len(_words(line)), 1)
        if overlap > 0.6:
            out.append("The line repeats slide 1. Say the post's turn or rule in new words instead.")
    unquoted = re.sub(r'"[^"]*"|“[^”]*”', "", line + " " + " ".join(body))  # a quoted line someone says may ask
    if "?" in unquoted:
        out.append("Only the ask may be a question; make the line and body statements.")
    kind = c.get("ask_type")
    if kind not in ("send", "question", "save") or not ask:
        out.append("Give exactly one ask, with ask_type send, question or save.")
    elif kind == "send" and not ask.lower().startswith("send this to"):
        out.append("A send ask starts with 'Send this to' and names the exact person.")
    elif kind == "save" and not ask.lower().startswith("save this for"):
        out.append("A save ask starts with 'Save this for' and names the moment to come back.")
    elif kind == "question" and not ask.rstrip().endswith("?"):
        out.append("A question ask ends with a question mark.")
    phrase = str(c.get("search_phrase", "")).strip().lower()
    if not phrase or phrase not in (line + " " + " ".join(body)).lower():
        out.append("search_phrase must appear word for word in the line or body: the words someone would type into search.")
    if not (post.get("topic") or {}).get("lived") and FIRST_PERSON.search(text):
        out.append("The post is written to the reader: no I, me or my in the caption.")
    if STOCK.search(text) or EMOJI.search(text) or "#" in text:
        out.append("No stock asks (link in bio, comment below, tag a friend), no emoji, no em dashes, no hashtags in the text.")
    seen = " ".join(slides).lower()
    new_numbers = [n for n in re.findall(r"₹?\d[\d,.]*", text) if n.lower() not in seen]
    if new_numbers:
        out.append(f"{', '.join(new_numbers)} isn't in the slides. The caption adds no new numbers or facts.")
    tag = str(c.get("topic_tag", "")).strip()
    if not TAG.match(tag) or tag.lower() in BANNED_TAGS:
        out.append("topic_tag: one specific CamelCase tag for exactly this topic (#HealthInsurance), not a broad one.")
    return out


def make(post: dict, draft: dict, tries: int = 3) -> dict:
    """The caption fields for `draft`: caption text, hashtags, ask type and search phrase. Keeps the attempt with the
    fewest problems if none is clean, and says so in the log."""
    topic = post.get("topic") or {}
    base = dict(
        persona=llm.prompt("persona"),
        slides="\n".join(f"{i}. {s}" for i, s in enumerate(_slides(draft), 1)),
        topic=json.dumps({k: topic.get(k) for k in ("claim", "turn", "because", "payoff", "lived", "send_to", "territory")
                          if topic.get(k) is not None}, ensure_ascii=False, indent=1),
        send=(draft.get("end") or {}).get("send", "") or "(none)")
    best, best_left, fix = None, None, ""
    for _ in range(tries):
        try:
            c = llm.call_json(config.MODEL_WRITER, llm.fill(llm.prompt("caption"), fix=fix, **base), stage="caption")
        except SystemExit:
            raise
        except Exception as e:  # noqa: BLE001
            state.log("caption", f"{post.get('id')} caption call failed: {str(e)[:200]}")
            continue
        left = problems(post, draft, c)
        if best is None or len(left) < len(best_left):
            best, best_left = c, left
        if not left:
            break
        fix = ("\n## Fix these in your last caption, change nothing else\n" + json.dumps(c, ensure_ascii=False) + "\n"
               + "\n".join(f"- {p}" for p in left) + "\n")
    if best is None:
        return {}
    if best_left:
        state.log("caption", f"{post.get('id')} caption kept with: {best_left[:2]}")
    tags = [best.get("topic_tag", "")] if TAG.match(str(best.get("topic_tag", ""))) and \
        str(best.get("topic_tag")).lower() not in BANNED_TAGS else []
    terr = territory_tag(post)
    if terr.lower() not in {t.lower() for t in tags}:
        tags.append(terr)
    return {"caption": assemble(best), "hashtags": tags, "caption_style": best.get("ask_type", ""),
            "search_phrase": best.get("search_phrase", ""), "caption_v": 2}
