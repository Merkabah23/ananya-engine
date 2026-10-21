"""The reference corpus (@varun760, OCR text) and helpers for calibration and originality."""
from __future__ import annotations

import json
import random
import re
from functools import lru_cache

from . import config


@lru_cache(maxsize=1)
def posts() -> list[dict]:
    return json.loads((config.DATA / "varun_corpus.json").read_text())["posts"]


def organic() -> list[dict]:
    return [p for p in posts() if p["territory"] not in ("sponsored",)]


def hook(p: dict) -> str:
    return re.sub(r"\s+", " ", p["slides"][0]).strip()[:220] if p["slides"] else ""


def quartiles() -> tuple[list[dict], list[dict]]:
    o = sorted(organic(), key=lambda p: -p["likes"])
    q = len(o) // 4
    return o[:q], o[-q:]


def calibration_picks(k: int = 6, seed: int = 7) -> tuple[list[dict], list[dict]]:
    top, bottom = quartiles()
    rnd = random.Random(seed)
    return rnd.sample(top, min(k, len(top))), rnd.sample(bottom, min(k, len(bottom)))


def calibration_examples(k: int = 6, seed: int = 7) -> tuple[str, str]:
    t, b = calibration_picks(k, seed)
    fmt = lambda ps: "\n".join(f"- {hook(p)}" for p in ps)
    return fmt(t), fmt(b)


def all_hooks(limit: int = 140) -> str:
    return "\n".join(f"- {hook(p)[:120]}" for p in posts()[:limit])


def unwrap(slide: str) -> str:
    """OCR breaks lines wherever the image wrapped them and leaves stray bullets; join it back into clean running text."""
    slide = re.sub(r"(?m)^[\s•·.,C\d]{1,8}$", "", slide)  # lines that are only OCR debris like "• • •" or "1•"
    slide = slide.replace("•", " ")
    return re.sub(r"\s+", " ", slide).strip()


def rhythm_examples(k: int = 3, exclude_territory: str | None = None, seed: int | None = None,
                    fmt: str = "carousel") -> str:
    """Full text of a few of his posts in the same format, for tone. Never the same territory as the topic."""
    same = [p for p in organic() if (len(p["slides"]) == 1) == (fmt == "single")]
    pool = [p for p in same if p["territory"] != exclude_territory] or same
    rnd = random.Random(seed)
    picks = rnd.sample(pool, min(k, len(pool)))
    blocks = []
    for i, p in enumerate(picks, 1):
        body = "\n\n".join(f"[slide {j + 1}] {unwrap(s)}" for j, s in enumerate(p["slides"][:8]))
        blocks.append(f"### Example {i}\n{body}")
    return "\n\n".join(blocks)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9₹']+", text.lower())


@lru_cache(maxsize=1)
def _corpus_ngrams() -> frozenset:
    grams = set()
    n = config.NGRAM_BLOCK
    for p in posts():
        w = _words(" ".join(p["slides"]))
        grams.update(tuple(w[i:i + n]) for i in range(len(w) - n + 1))
    return frozenset(grams)


def copied_runs(text: str) -> list[str]:
    """Any run of NGRAM_BLOCK words that also appears in the reference corpus."""
    n = config.NGRAM_BLOCK
    w = _words(text)
    grams = _corpus_ngrams()
    return sorted({" ".join(w[i:i + n]) for i in range(len(w) - n + 1) if tuple(w[i:i + n]) in grams})


def blind_samples(k: int, seed: int, fmt: str = "carousel") -> list[str]:
    """Real reference posts in the same format, name stripped and OCR line breaks removed, for the AI-spotting test."""
    pool = [p for p in organic() if (len(p["slides"]) == 1) == (fmt == "single")]
    rnd = random.Random(seed)
    out = []
    for p in rnd.sample(pool, min(k, len(pool))):
        text = "\n\n".join(unwrap(s) for s in p["slides"][:8])
        out.append(re.sub(r"varun|agarwal", "", text, flags=re.I))
    return out
