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

TERRITORY_MIX = {
    "money_status": 0.30,
    "family_identity": 0.25,
    "social_media": 0.20,
    "pop_culture": 0.15,
    "cities_generations": 0.10,
}

# Gates
MIN_TOPIC_SCORE = 20          # out of 30 (six criteria x 5), plus fresh >= 4
MAX_REWRITES = 3
NGRAM_BLOCK = 6               # any shared 6-word run with Varun's corpus blocks a draft
BLIND_TEST_TRIALS = 1         # per attempt; the final attempt uses 2

# Rendering
CANVAS = (1080, 1350)
DISPLAY_NAME = os.getenv("DISPLAY_NAME", "Ananya Mishra")
IG_HANDLE = os.getenv("IG_HANDLE", "ananyakrishnan47")  # used to find the Instagram channel in Buffer
VERIFIED = False              # never draw a tick unless the account is verified

# Publishing
PAUSED = os.getenv("ENGINE_PAUSED", "false").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
BUFFER_API = "https://api.buffer.com"
BUFFER_MAX_IMAGES = 10        # Buffer's limit for Instagram carousels
IS_AI_GENERATED_FLAG = os.getenv("IG_AI_FLAG", "false").lower() == "true"


def env(name: str, required: bool = True) -> str:
    v = os.getenv(name, "")
    if required and not v and not DRY_RUN:
        raise SystemExit(f"Missing environment variable {name}. Add it as a GitHub secret.")
    return v
