"""Central settings. Everything tunable lives here or in data/*.json."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "prompts"
DATA = ROOT / "data"
STATE = ROOT / "state"
ASSETS = ROOT / "assets"
OUT = ROOT / "out"  # rendered slides (git-ignored; uploaded to storage)

# Models run through the Claude Code CLI on a Claude subscription (CLAUDE_CODE_OAUTH_TOKEN).
# Aliases resolve to the latest model of each family. Opus writes; Sonnet judges.
CLAUDE_BIN = os.getenv("CLAUDE_BIN", "claude")
MODEL_WRITER = os.getenv("MODEL_WRITER", "opus")
MODEL_JUDGE = os.getenv("MODEL_JUDGE", "sonnet")
# The editor and the voice check judge taste, not facts. On sonnet their notes shifted every attempt and no draft
# converged (0 of 12 on 10 Nov), so they run on the writer's model; the fact gate stays on MODEL_JUDGE.
MODEL_CRITIC = os.getenv("MODEL_CRITIC", "opus")
MODEL_FAST = os.getenv("MODEL_FAST", "haiku")

# Subscription limits are per usage window, so work is spread out: the monthly run only
# scouts and plans; each daily run writes a few posts.
MAX_CALLS_PER_MONTH = int(os.getenv("MAX_CALLS_PER_MONTH", "2000"))
PRODUCE_PER_RUN = int(os.getenv("PRODUCE_PER_RUN", "3"))
PARALLEL = int(os.getenv("PARALLEL", "3"))  # model calls in flight at once

# Posting plan (10 Nov 2026, from the research the owner asked for): five carousels a week, Monday to Friday.
# Buffer's 2.1M-post study (2025): reach per post rises with frequency (+12% at 3-5 a week, +18% at 6-9, +24% at 10+,
# vs 1-2), the biggest jump being 1-2 -> 3-5; Mosseri: posting more reaches more people, and a new post doesn't take
# reach from one that's doing well. Quality is the limit, not the algorithm: five a week at the approved bar beats
# seven with filler. Raise to daily (add 5, 6 to POST_DAYS) once the writer's drafts pass without hand edits.
# Times are IST. 20:30 lands after the commute and before dinner, just ahead of the 8-10pm peak in the large global
# studies (Buffer 9.6M posts, Metricool 24M); once the account has 100+ followers, Instagram Insights' "Most active
# times" should override it. The draft format stays "carousel" (slides of text); OUTPUT decides how it is published.
POST_TIME = "20:30"
POST_EVERY_DAYS = 1
POST_ANCHOR = "2026-11-10"
POST_DAYS = [0, 1, 2, 3, 4]  # Monday to Friday
SLOTS = [{"weekday": d, "time": POST_TIME, "format": "carousel"} for d in POST_DAYS]
# Owner, 10 Nov 2026: back to carousels. Readers set their own pace on a carousel; on a reel we set it for them, and
# the benchmarks' text reels get ~1/30th of their carousels' likes. Reels stay available for posts where something moves.
OUTPUT = os.getenv("OUTPUT", "carousel")  # "reel": the slides become one 9:16 video; "carousel": the slides go up as images
# "native": a plain post card (white, left-aligned, the owner's photo and the page name, one type size), the look of
# the posts that win this format. "classic": the older designed cover, teal accents and end card.
LOOK = os.getenv("LOOK", "native")
# Owner, 9 Nov 2026: Buffer sends a reminder at post time and the owner publishes from the Instagram app, so they can
# add a trending track (Instagram's music library can't be attached through the API). "automatic" posts silently.
BUFFER_SCHEDULING = os.getenv("BUFFER_SCHEDULING", "notification")  # reels: the owner adds music in the app
CAROUSEL_SCHEDULING = os.getenv("CAROUSEL_SCHEDULING", "automatic")  # carousels need no music, so they publish themselves
PUSH_DAYS = 7  # posts go to Buffer a week ahead: 3-4 posts, well under Buffer's 10-post queue
SPARE_TOPICS = 5  # extra approved topics per month, used when a draft fails

TERRITORY_MIX = {  # owner, 10 Nov 2026: widen to world news, geopolitics, trending things, sports, consumer behaviour, startups
    "business_brands": 0.20,     # brands, ads, marketing, D2C, startups, funding, IPOs, shutdowns, business stories
    "money_status": 0.20,        # consumer behaviour: how people spend, prices, status, salaries, what we buy and why
    "world_geopolitics": 0.15,   # world news and geopolitics as they land in Indian lives: prices, jobs, visas, travel
    "life_relationships": 0.15,  # family, dating, friendship, work, cities, growing up
    "sports": 0.10,              # cricket, football, chess, the Olympics, fandom, the business of sport
    "pop_culture": 0.10,         # films, OTT, music, celebrities, what's trending this week
    "creators_internet": 0.10,   # Instagram, creators, apps, AI, online culture, viral moments
}

# Gates
MIN_TOPIC_SCORE = 22          # out of 35 (seven criteria x 5), plus fresh >= 4
MAX_REWRITES = 4  # five attempts: the native carousel bar is higher than the reel's
NGRAM_BLOCK = 6               # any shared 6-word run with Varun's corpus blocks a draft

# Rendering
CANVAS = (1080, 1350)
DISPLAY_NAME = os.getenv("DISPLAY_NAME", "Above MRP")
IG_HANDLE = os.getenv("IG_HANDLE", "abovemrp")  # used to find the Instagram channel in Buffer
# Buffer may still show the old handle for a while after a rename, so either one matches.
IG_HANDLES = [h.strip().lower() for h in os.getenv("IG_HANDLES", f"{IG_HANDLE},ananyakrishnan47").split(",") if h.strip()]
BRAND_HASHTAG = "#AboveMRP"
TAGLINE = "How India spends, scrolls and gets sold to"
END_CARD = os.getenv("END_CARD", "true").lower() == "true"  # a teal end card after the last slide of every carousel
END_PROMISE = "The real price of things in India."  # a post can set its own line in draft.end.promise
END_FOLLOW_LINE = os.getenv("END_FOLLOW_LINE", "")  # owner removed the posting-days line from the end card
MONOGRAM = "A/M"  # fallback slide-header mark when assets/avatar.png is missing
MAX_HASHTAGS = 3  # this post's tag, a rotated territory tag, #AboveMRP (Instagram allows 5 since Dec 2025; tags are labels, not reach)
VERIFIED = False              # never draw a tick unless the account is verified

# Publishing
PAUSED = os.getenv("ENGINE_PAUSED", "false").lower() == "true"
# Buffer's needsApproval flag is only accepted on channels whose posting policy requires approval. This account's
# channel already lands API posts in drafts for the owner to review, so the flag stays off by default.
BUFFER_NEEDS_APPROVAL = os.getenv("BUFFER_NEEDS_APPROVAL", "false").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
BUFFER_API = "https://api.buffer.com"
BUFFER_MAX_IMAGES = 10        # Buffer's limit for Instagram carousels; also the most screens a reel carries
IS_AI_GENERATED_FLAG = os.getenv("IG_AI_FLAG", "false").lower() == "true"


def env(name: str, required: bool = True) -> str:
    v = os.getenv(name, "")
    if required and not v and not DRY_RUN:
        raise SystemExit(f"Missing environment variable {name}. Add it as a GitHub secret.")
    return v

ALWAYS_SOURCE = True  # the benchmark carries 2-4 sourced numbers: search for sources on every topic
