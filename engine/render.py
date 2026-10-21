"""Render a draft into 1080x1350 JPEG slides in the 'Facebook post' style (section 4 of the playbook)."""
from __future__ import annotations

import math
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import config

W, H = config.CANVAS
MARGIN = 80
AVATAR = 120
TEAL = (15, 118, 110)
INK = (5, 5, 5)
GREY = (101, 103, 107)
FONTS = config.ASSETS / "fonts"
BODY_SIZES = [48, 46]  # never shrink a dense slide into small print: split it instead (split_for_fit)
SWIPE = "swipe to read"


class Overflow(Exception):
    pass


def _font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / f"Inter-{weight}.ttf"), size)


def _avatar() -> Image.Image:
    p = config.ASSETS / "avatar.png"
    if p.exists():
        img = Image.open(p).convert("RGB").resize((AVATAR, AVATAR))
    else:  # placeholder until the illustrated avatar is added
        img = Image.new("RGB", (AVATAR, AVATAR), TEAL)
        d = ImageDraw.Draw(img)
        f = _font("Medium", 46)
        initials = "".join(w[0] for w in config.DISPLAY_NAME.split()[:2]).upper()
        d.text((AVATAR / 2, AVATAR / 2), initials, font=f, fill="white", anchor="mm")
    mask = Image.new("L", (AVATAR, AVATAR), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, AVATAR - 1, AVATAR - 1), fill=255)
    img.putalpha(mask)
    return img


def _tokens(text: str) -> list[tuple[str, bool]]:
    """Split a paragraph into (word, is_italic) using *single-asterisk* markers. Any **bold** markers are
    dropped: the house style is one weight throughout. Newlines become ('\n', False)."""
    text = text.replace("**", "")
    out: list[tuple[str, bool]] = []
    for line_no, line in enumerate(text.split("\n")):
        if line_no:
            out.append(("\n", False))
        for k, part in enumerate(line.split("*")):
            out += [(w, k % 2 == 1) for w in part.split()]
    return out


def _wrap_runs(text: str, size: int, width: int) -> list[list[tuple[str, bool]]]:
    reg, ital = _font("Regular", size), _font("Italic", size)
    space = reg.getlength(" ")
    lines: list[list[tuple[str, bool]]] = [[]]
    x = 0.0
    for word, b in _tokens(text):
        if word == "\n":
            lines.append([]); x = 0.0
            continue
        w = (ital if b else reg).getlength(word)
        if lines[-1] and x + space + w > width:
            lines.append([]); x = 0.0
        x += (space if lines[-1] else 0) + w
        lines[-1].append((word, b))
    return lines


def _layout(paragraphs: list[str], size: int) -> tuple[list[tuple[list, str]], int]:
    """Return [(runs, kind)] with kind in body/swipe/gap and the total height."""
    lh = int(size * 1.38)
    rows: list[tuple[list, str]] = []
    for i, p in enumerate(paragraphs):
        kind = "swipe" if p.strip().lower().startswith(SWIPE) else "body"
        for runs in _wrap_runs(p.strip(), size, W - 2 * MARGIN):
            rows.append((runs, kind))
        if i < len(paragraphs) - 1:
            rows.append(([], "gap"))
    height = sum(lh if k != "gap" else int(lh * 0.62) for _, k in rows)
    return rows, height


def _globe(d: ImageDraw.ImageDraw, cx: int, cy: int, r: int) -> None:
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=GREY, width=3)
    d.ellipse((cx - r // 2, cy - r, cx + r // 2, cy + r), outline=GREY, width=2)
    d.line((cx - r, cy, cx + r, cy), fill=GREY, width=2)


def render_slide(paragraphs: list[str]) -> Image.Image:
    header_h, gap = AVATAR, 44
    avail = H - 2 * 70 - header_h - gap
    for size in BODY_SIZES:
        rows, text_h = _layout(paragraphs, size)
        if text_h <= avail:
            break
    else:
        raise Overflow(f"text needs {text_h}px, {avail}px available")
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    y0 = max(70, (H - (header_h + gap + text_h)) // 2)
    # Header: avatar, teal bar, name, "Just now · globe", dots
    img.paste(_avatar(), (MARGIN, y0), _avatar())
    nx = MARGIN + AVATAR + 26
    d.rectangle((nx, y0 + 14, nx + 5, y0 + AVATAR - 14), fill=TEAL)
    nx += 22
    d.text((nx, y0 + 18), config.DISPLAY_NAME, font=_font("Medium", 44), fill=INK)
    meta = _font("Regular", 32)
    d.text((nx, y0 + 72), "Just now ·", font=meta, fill=GREY)
    _globe(d, int(nx + meta.getlength("Just now ·") + 26), y0 + 72 + 19, 14)
    for k in range(3):
        d.ellipse((W - MARGIN - 52 + k * 20, y0 + 30, W - MARGIN - 42 + k * 20, y0 + 40), fill=GREY)
    # Body, at the size chosen above
    reg, ital = _font("Regular", size), _font("Italic", size)
    space = reg.getlength(" ")
    lh = int(size * 1.38)
    y = y0 + header_h + gap
    for runs, kind in rows:
        if kind == "gap":
            y += int(lh * 0.62)
            continue
        x = float(MARGIN)
        for k, (word, b) in enumerate(runs):
            f = ital if b else reg
            if k:
                x += space
            d.text((x, y), word, font=f, fill=GREY if kind == "swipe" else INK)
            x += f.getlength(word)
        y += lh
    return img


def split_for_fit(slides: list[list[str]]) -> list[list[str]]:
    """Split any slide that overflows at the smallest size into two, at a paragraph boundary."""
    out: list[list[str]] = []
    for paras in slides:
        try:
            render_slide(paras)
            out.append(paras)
        except Overflow:
            if len(paras) >= 2:
                mid = math.ceil(len(paras) / 2)
                out += split_for_fit([paras[:mid], paras[mid:]])
                continue
            halves = _halve(paras[0])
            if len(halves) < 2:
                raise
            out += split_for_fit([[h] for h in halves])
    return out


def _halve(paragraph: str) -> list[str]:
    """Split one paragraph that is too long for a slide: at the sentence nearest the middle, else at the middle word."""
    sents = [x for x in re.split(r"(?<=[.!?])\s+", paragraph.strip()) if x]
    if len(sents) >= 2:
        words, total, cut = 0, len(paragraph.split()), 1
        for i, x in enumerate(sents[:-1], 1):
            words += len(x.split())
            if words >= total / 2:
                cut = i
                break
        return [" ".join(sents[:cut]), " ".join(sents[cut:])]
    w = paragraph.split()
    return [" ".join(w[: len(w) // 2]), " ".join(w[len(w) // 2:])] if len(w) > 1 else [paragraph]


def render_post(post: dict) -> list[Path]:
    slides = split_for_fit([s["paragraphs"] for s in post["draft"]["slides"]])
    if len(slides) > config.BUFFER_MAX_IMAGES:
        raise Overflow(f"{len(slides)} slides after splitting; Buffer allows {config.BUFFER_MAX_IMAGES}")
    outdir = config.OUT / post["id"]
    outdir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, paras in enumerate(slides, 1):
        p = outdir / f"slide_{i:02d}.jpg"
        render_slide(paras).save(p, "JPEG", quality=92, optimize=True)
        paths.append(p)
    return paths
