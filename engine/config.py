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
MODEL_FAST = os.getenv("MODEL_FAST", "haiku")

# Subscription limits are per usage window, so work is spread out: the monthly run only
# scouts and plans; each daily run writes a few posts.
MAX_CALLS_PER_MONTH = int(os.getenv("MAX_CALLS_PER_MONTH", "400"))
PRODUCE_PER_RUN = int(os.getenv("PRODUCE_PER_RUN", "3"))
PARALLEL = int(os.getenv("PARALLEL", "3"))  # model calls in flight at once

# Posting plan. Times are IST; weekday 0 = Monday.
SLOTS = [
    {"weekday": 0, "time": "19:30", "format": "carousel"},
    {"weekday": 2, "time": "19:30", "format": "carousel"},
    {"weekday": 4, "time": "19:30", "format": "carousel"},
    {"weekday": 5, "time": "11:00", "format": "single"},
]
SPARE_TOPICS = 5  # extra approved topics per month, used when a draft fails

TERRITORY_MIX = {  # roughly the reference creator's spread of subjects
    "business_brands": 0.25,     # brands, ads, marketing, D2C, startups, business stories
    "creators_internet": 0.20,   # Instagram, creators, reels, apps, AI, online culture
    "money_status": 0.20,        # how people spend, prices, status, salaries
    "pop_culture": 0.15,         # films, OTT, celebrities, cricket, music
    "life_relationships": 0.20,  # family, dating, friendship, work, cities, growing up
}

# Gates
MIN_TOPIC_SCORE = 22          # out of 35 (seven criteria x 5), plus fresh >= 4
MAX_REWRITES = 2             # notes from the editor and the fact gate go back to the writer; nothing else rewrites
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
END_PROMISE = "The seller's side of how India spends."
END_FOLLOW_LINE = os.getenv("END_FOLLOW_LINE", "New post every Mon · Wed · Fri")
MONOGRAM = "A/M"  # the slide-header mark; the Instagram profile picture is set separately in the app
MAX_HASHTAGS = 5  # Instagram caps posts at 5 hashtags (Dec 2025)
VERIFIED = False              # never draw a tick unless the account is verified

# Publishing
PAUSED = os.getenv("ENGINE_PAUSED", "false").lower() == "true"
# Buffer's needsApproval flag is only accepted on channels whose posting policy requires approval. This account's
# channel already lands API posts in drafts for the owner to review, so the flag stays off by default.
BUFFER_NEEDS_APPROVAL = os.getenv("BUFFER_NEEDS_APPROVAL", "false").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
BUFFER_API = "https://api.buffer.com"
BUFFER_MAX_IMAGES = 10        # Buffer's limit for Instagram carousels
IS_AI_GENERATED_FLAG = os.getenv("IG_AI_FLAG", "false").lower() == "true"


def env(name: str, required: bool = True) -> str:
    v = os.getenv(name, "")
    if required and not v and not DRY_RUN:
        raise SystemExit(f"Missing environment variable {name}. Add it as a GitHub secret.")
    return v
