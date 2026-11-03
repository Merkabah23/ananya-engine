"""Render a draft into 1080x1350 JPEG slides: the take as the cover, calm reading slides and an end card.

Opinion first: the cover is the take in a very large headline with one teal phrase; a pinned header carries the
owner's photo and the struck-through MRP tag; reading slides have one bold teal line at most and a page count; the
end card asks for a save. Number boxes, big figures and source lines appear only on the rare post that uses them.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import config

W, H = config.CANVAS
MARGIN = 80
SAFE = 112              # Instagram's 3:4 profile grid crops ~34px off each side; cover text stays inside this
PAPER = (250, 248, 244)
INK = (17, 17, 17)
SUB = (74, 79, 76)
COUNT = (88, 93, 90)
TEAL = (15, 118, 110)
TEAL_TINT = (226, 241, 238)
WHITE = (255, 255, 255)
ON_TEAL = (240, 248, 246)   # 5.2:1 on teal: small text on the end card stays above WCAG AA
FONTS = config.ASSETS / "fonts"
BODY_SIZES = [56, 52]   # never shrink a dense slide into small print: split it instead (split_for_fit)
SWIPE = "swipe to read"
BODY_TOP, BODY_BOTTOM = 250, H - 120


class Overflow(Exception):
    pass


def _font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / f"Inter-{weight}.ttf"), size)


# --- chrome: monogram, price tag, header, page count --------------------------------------------------------

def _avatar(size: int, on_teal: bool = False) -> Image.Image:
    """The owner's photo in a circle (a thin white ring on teal), or the monogram if there is no photo."""
    photo = config.ASSETS / "avatar.png"
    if not photo.exists():
        return _monogram(size, on_teal)
    ring = 4 if on_teal else 0
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    if ring:
        ImageDraw.Draw(img).ellipse((0, 0, size - 1, size - 1), fill=WHITE)
    inner = size - 2 * ring
    face = Image.open(photo).convert("RGB").resize((inner, inner))
    mask = Image.new("L", (inner, inner), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, inner - 1, inner - 1), fill=255)
    img.paste(face, (ring, ring), mask)
    return img


def _monogram(size: int, on_teal: bool = False) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, size - 1, size - 1), fill=WHITE if on_teal else TEAL)
    d.text((size / 2, size / 2 + 2), config.MONOGRAM, font=_font("Bold", int(size * 0.34)),
           fill=TEAL if on_teal else WHITE, anchor="mm")
    return img


def _tag(d: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, on_teal: bool = False) -> None:
    """The brand mark: a price tag reading MRP, struck through."""
    fill, ink = (WHITE, TEAL) if on_teal else (TEAL, WHITE)
    notch = h // 2
    d.polygon([(x, y + notch), (x + notch, y), (x + w, y), (x + w, y + h), (x + notch, y + h)], fill=fill)
    hole = max(5, h // 6)
    d.ellipse((x + notch - hole, y + notch - hole, x + notch + hole, y + notch + hole), fill=TEAL if on_teal else PAPER)
    f = _font("Bold", int(h * 0.55))
    tx = x + notch + (w - notch) / 2
    d.text((tx, y + h / 2), "MRP", font=f, fill=ink, anchor="mm")
    half = f.getlength("MRP") / 2 + 4
    d.line((tx - half, y + h / 2 + 2, tx + half, y + h / 2 + 2), fill=ink, width=max(3, h // 14))


def _header(img: Image.Image, d: ImageDraw.ImageDraw, large: bool = False, on_teal: bool = False) -> None:
    size, y = (96, 72) if large else (72, 72)
    mark = _avatar(size, on_teal)
    img.paste(mark, (MARGIN, y), mark)
    x = MARGIN + size + 22
    d.text((x, y + (12 if large else 6)), config.DISPLAY_NAME, font=_font("Bold", 40 if large else 34),
           fill=WHITE if on_teal else INK)
    d.text((x, y + (58 if large else 44)), "@" + config.IG_HANDLE, font=_font("Regular", 30 if large else 30),
           fill=ON_TEAL if on_teal else SUB)
    tw, th = (150, 58) if large else (116, 44)
    _tag(d, W - MARGIN - tw, y + (20 if large else 8), tw, th, on_teal)


def _count(d: ImageDraw.ImageDraw, i: int, n: int, on_teal: bool = False) -> None:
    if n < 2:
        return
    d.text((W - MARGIN, H - 64), f"{i}/{n}  →" if i < n else f"{i}/{n}", font=_font("SemiBold", 36),
           fill=ON_TEAL if on_teal else COUNT, anchor="rs")


# --- text: **bold** (teal), *italic*, wrapping ----------------------------------------------------------------

def _tokens(text: str) -> list[tuple[str, str]]:
    """(word, style) with style in regular/bold/italic. Newlines become ('\\n', 'regular')."""
    out: list[tuple[str, str]] = []
    for line_no, line in enumerate(text.split("\n")):
        if line_no:
            out.append(("\n", "regular"))
        lead_on = False
        for b, chunk in enumerate(line.split("**")):
            for k, part in enumerate(chunk.split("*")):
                style = "bold" if b % 2 else ("italic" if k % 2 else "regular")
                for w in part.split():
                    if w.startswith("\x01"):
                        lead_on = True; w = w[1:]
                    closes = w.endswith("\x01")
                    w = w.rstrip("\x01")
                    if lead_on and style == "regular":
                        out.append((w, "lead")); lead_on = not closes
                        continue
                    if out and out[-1][0] != "\n" and re.match(r"^[.,;:!?)\]'’]+$", w):
                        out.append((w, style + "+glue"))  # drawn with no space, never wrapped onto its own line
                    else:
                        out.append((w, style))
    return out


def _face(style: str, size: int) -> ImageFont.FreeTypeFont:
    style = style.replace("+glue", "")
    return _font({"bold": "SemiBold", "italic": "Italic", "lead": "SemiBold"}.get(style, "Regular"), size)


def _wrap(text: str, size: int, width: int) -> list[list[tuple[str, str]]]:
    space = _font("Regular", size).getlength(" ")
    lines: list[list[tuple[str, str]]] = [[]]
    x = 0.0
    for word, style in _tokens(text):
        if word == "\n":
            lines.append([]); x = 0.0
            continue
        w = _face(style, size).getlength(word)
        glue = style.endswith("+glue")
        if lines[-1] and not glue and x + space + w > width:
            lines.append([]); x = 0.0
        x += (space if lines[-1] and not glue else 0) + w
        lines[-1].append((word, style))
    return lines


def _plain_lines(text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    """Wrap plain text measured in the font it is drawn in (bold runs wider than regular)."""
    lines, cur = [], ""
    for w in text.split():
        test = f"{cur} {w}".strip()
        if cur and font.getlength(test) > width:
            lines.append(cur); cur = w
        else:
            cur = test
    return lines + ([cur] if cur else [])


def _draw_lines(d: ImageDraw.ImageDraw, lines, x: int, y: int, size: int, color, bold_color) -> int:
    space, lh = _font("Regular", size).getlength(" "), int(size * 1.44)
    for runs in lines:
        cx = float(x)
        for k, (word, style) in enumerate(runs):
            if k and not style.endswith("+glue"):
                cx += space
            f = _face(style, size)
            d.text((cx, y), word, font=f, fill=bold_color if style.startswith("bold") else color)
            cx += f.getlength(word)
        y += lh
    return y


def _body_height(paragraphs: list[str], size: int) -> int:
    lh = int(size * 1.44)
    return sum(len(_wrap(p, size, W - 2 * MARGIN)) * lh for p in paragraphs) + int(lh * 0.6) * (len(paragraphs) - 1)


# --- slides -------------------------------------------------------------------------------------------------

def _clean(paragraphs: list[str]) -> list[str]:
    return [p for p in paragraphs if p.strip() and not p.strip().lower().startswith(SWIPE)]


def render_cover(cover: dict, n: int) -> Image.Image:
    """The take as a very large headline ([keyword] in teal, kept on one line) and a sub-line, centred on the slide.
    Only a post whose point is a number carries it in a box in the lower third."""
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    _header(img, d, large=True)
    headline = re.sub(r"\[([^\]]+)\]", lambda m: "[" + m.group(1).replace(" ", " ") + "]", cover["headline"])
    words, safe = headline.split(), W - 2 * SAFE
    proof = cover.get("proof") or {}
    for size in range(124 if not proof.get("figure") else 108, 70, -2):
        f = _font("Bold", size)
        lines, cur = [], []
        for w in words:
            test = " ".join(cur + [w]).replace("[", "").replace("]", "")
            if cur and f.getlength(test) > safe:
                lines.append(cur); cur = []
            cur.append(w)
        lines.append(cur)
        if len(lines) >= 2 and len(lines[-1]) == 1 and len(lines[-2]) >= 2:  # a lone last word: carry one more down
            moved = lines[-2][-1:] + lines[-1]
            if f.getlength(" ".join(moved).replace("[", "").replace("]", "")) <= safe:
                lines[-2], lines[-1] = lines[-2][:-1], moved
        if len(lines) <= 4 and all(f.getlength(" ".join(l).replace("[", "").replace("]", "")) <= safe for l in lines):
            break
    sub_lines = _plain_lines(cover.get("sub", ""), _font("Medium", 46), safe)
    block = len(lines) * int(size * 1.12) + 40 + 62 * len(sub_lines)
    y = 250 if proof.get("figure") else max(260, (H - block) // 2 - 20)  # no number: the take sits in the optical centre
    teal = False
    for line in lines:
        x = float(SAFE)
        for w in line:
            for piece in re.split(r"([\[\]])", w.replace(" ", " ")):  # brackets can sit inside punctuation: '[no],
                if piece in "[]":
                    teal = piece == "[" if piece else teal
                    continue
                d.text((x, y), piece, font=f, fill=TEAL if teal else INK)
                x += f.getlength(piece)
            x += f.getlength(" ")
        y += int(size * 1.12)
    y += 40
    for line in sub_lines:
        d.text((SAFE, y), line, font=_font("Medium", 46), fill=SUB)
        y += 62
    if proof.get("figure"):
        by = H - 330
        d.rounded_rectangle((MARGIN, by, W - MARGIN, by + 210), radius=24, fill=TEAL_TINT)
        d.text((MARGIN + 44, by + 28), proof["figure"], font=_font("Bold", 84), fill=TEAL)
        ly = by + 130
        for runs in _wrap(proof.get("label", ""), 32, W - 2 * (MARGIN + 44))[:2]:
            d.text((MARGIN + 44, ly), " ".join(w for w, _ in runs), font=_font("Medium", 32), fill=SUB)
            ly += 40
    _count(d, 1, n)
    return img


def render_slide(paragraphs: list[str], i: int = 1, n: int = 1, big: dict | None = None,
                 source: str | None = None) -> Image.Image:
    """A reading slide: paragraphs with at most one **bold** teal line, an optional big figure and a source line."""
    paragraphs = _clean(paragraphs)
    room = BODY_BOTTOM - BODY_TOP - (330 if big else 0)
    for size in BODY_SIZES:
        if _body_height(paragraphs, size) <= room:
            break
    else:
        raise Overflow(f"text needs {_body_height(paragraphs, BODY_SIZES[-1])}px, {room}px available")
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    _header(img, d)
    if not big and len(paragraphs) == 1 and paragraphs[0].strip().startswith("**") and paragraphs[0].strip().endswith("**"):
        _statement(d, paragraphs[0].strip().strip("*"))
        _count(d, i, n)
        return img
    paragraphs = _lead(paragraphs)
    block = _body_height(paragraphs, size)
    y = BODY_TOP if big else max(BODY_TOP, BODY_TOP + (room - block) // 2 - 40)  # optical centre, a little high
    for p in paragraphs:
        y = _draw_lines(d, _wrap(p, size, W - 2 * MARGIN), MARGIN, y, size, INK, TEAL) + int(size * 1.44 * 0.6)
    if big and big.get("figure"):
        fy = max(y + 10, H - 470)
        d.text((MARGIN, fy), big["figure"], font=_font("Bold", 150), fill=TEAL)
        d.text((MARGIN + 4, fy + 178), big.get("label", ""), font=_font("Medium", 34), fill=SUB)
    if source:
        d.text((MARGIN, H - 64), source, font=_font("Regular", 26), fill=COUNT, anchor="ls")
    _count(d, i, n)
    return img


def _lead(paragraphs: list[str]) -> list[str]:
    """The slide's first sentence, when short and plain, is set in semibold: the line the eye lands on first."""
    if not paragraphs or "*" in paragraphs[0]:
        return paragraphs
    first, *rest = re.split(r"(?<=[.!?])\s+", paragraphs[0].strip(), maxsplit=1)
    if len(first.split()) > 12 or len(paragraphs[0].split()) < 4:
        return paragraphs
    words = first.split()
    lead = "\x01" + " ".join(words) + "\x01" if len(words) > 1 else "\x01" + words[0] + "\x01"
    return [" ".join([lead] + rest)] + paragraphs[1:]


def _statement(d: ImageDraw.ImageDraw, text: str) -> None:
    """One line, large, teal, in the middle of the slide: the payoff on its own, made to be screenshotted and sent."""
    for size in range(84, 54, -4):
        lines = _plain_lines(text, _font("Bold", size), W - 2 * SAFE)
        lh = int(size * 1.22)
        if len(lines) * lh <= 640:
            break
    y = (H - len(lines) * lh) // 2 - 20
    for line in lines:
        d.text((SAFE, y), line, font=_font("Bold", size), fill=TEAL)
        y += lh


def render_end(end: dict, n: int) -> Image.Image:
    """The end card: the page's promise, one ask (save, with a reason), who to send it to, and the posting days."""
    img = Image.new("RGB", (W, H), TEAL)
    d = ImageDraw.Draw(img)
    _header(img, d, large=True, on_teal=True)
    y = 330
    for line in _plain_lines(end.get("promise") or config.END_PROMISE, _font("Bold", 84), W - 2 * MARGIN):
        d.text((MARGIN, y), line, font=_font("Bold", 84), fill=WHITE)
        y += 98
    y += 70
    send = re.sub(r"^(Send (this )?to )", "", (end.get("send") or "").strip(), flags=re.I)
    if send:
        lines = _plain_lines(send[:1].upper() + send[1:], _font("SemiBold", 48), W - 2 * MARGIN - 88)  # the box grows
        box = 150 + 64 * len(lines)
        d.rounded_rectangle((MARGIN, y, W - MARGIN, y + box), radius=28, fill=WHITE)
        d.text((MARGIN + 44, y + 42), "Send this to", font=_font("Bold", 56), fill=TEAL)
        yy = y + 124
        for line in lines:
            d.text((MARGIN + 44, yy), line, font=_font("SemiBold", 48), fill=INK)
            yy += 64
        y += box + 60
    save = (end.get("save") or "").strip()
    if save:
        for line in _plain_lines("Save it: " + save[:1].lower() + save[1:], _font("Medium", 38), W - 2 * MARGIN)[:3]:
            d.text((MARGIN, y), line, font=_font("Medium", 38), fill=WHITE)
            y += 52
    if config.END_FOLLOW_LINE:
        d.text((MARGIN, H - 64), config.END_FOLLOW_LINE, font=_font("Medium", 32), fill=ON_TEAL, anchor="ls")
    _count(d, n, n, on_teal=True)
    return img


def _fits(paragraphs: list[str], big: dict | None = None) -> bool:
    room = BODY_BOTTOM - BODY_TOP - (330 if big else 0)
    return _body_height(_clean(paragraphs), BODY_SIZES[-1]) <= room


def split_for_fit(slides: list[dict]) -> list[dict]:
    """Split any reading slide that overflows at the smallest size into two, at a paragraph boundary."""
    out: list[dict] = []
    for s in slides:
        paras = s["paragraphs"]
        if _fits(paras, s.get("big")):
            out.append(s)
            continue
        if len(paras) >= 2:
            mid = math.ceil(len(paras) / 2)
            out += split_for_fit([{"paragraphs": paras[:mid]}, {**s, "paragraphs": paras[mid:]}])
            continue
        halves = _halve(paras[0])
        if len(halves) < 2:
            raise Overflow("a single sentence is too long for a slide")
        out += split_for_fit([{"paragraphs": [halves[0]]}, {**s, "paragraphs": [halves[1]]}])
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


def cover_for(draft: dict) -> dict:
    """The draft's cover, or one built from the hook when an older draft has none."""
    cover = dict(draft.get("cover") or {})
    if not cover.get("headline"):
        hook = _clean(draft["slides"][0]["paragraphs"]) or [""]
        cover = {"headline": hook[0], "sub": " ".join(hook[1:]), **cover}
    return cover


DENSE_WORDS = 40   # above this a reading slide is split at a paragraph break, when it has one


def _words(paragraphs: list[str]) -> int:
    return len(" ".join(_clean(paragraphs)).replace("*", "").split())


def shape(slides: list[dict], room: int) -> list[dict]:
    """Give the bold payoff line its own slide, and split dense slides at a paragraph break, while slides remain."""
    out: list[dict] = []
    for k, s in enumerate(slides):
        paras = _clean(s["paragraphs"])
        left = room - len(out) - (len(slides) - k)  # slides still free under the cap
        last = paras[-1].strip() if paras else ""
        if left > 0 and len(paras) >= 2 and not s.get("big") and last.startswith("**") and last.endswith("**") \
                and len(last.split()) >= 5 and _words(paras[:-1]) >= 10:
            out += [{**s, "paragraphs": paras[:-1]}, {"paragraphs": [last]}]
            continue
        if left > 0 and len(paras) >= 2 and not s.get("big") and _words(paras) > DENSE_WORDS:
            best = min(range(1, len(paras)), key=lambda c: abs(_words(paras[:c]) - _words(paras[c:])))
            if min(_words(paras[:best]), _words(paras[best:])) >= 10:
                out += [{"paragraphs": paras[:best]}, {**s, "paragraphs": paras[best:]}]
                continue
        out.append(s)
    return out


def _alt(paragraphs: list[str]) -> str:
    return " ".join(_clean(paragraphs)).replace("**", "").replace("*", "").replace("\u00a0", " ")[:1000]


def render_post(post: dict) -> list[Path]:
    draft = post["draft"]
    outdir = config.OUT / post["id"]
    outdir.mkdir(parents=True, exist_ok=True)
    if post.get("format") == "single" or len(draft["slides"]) == 1:
        images = [render_slide(draft["slides"][0]["paragraphs"])]
    else:
        end = bool(config.END_CARD)
        body = split_for_fit(shape([s for s in draft["slides"][1:]], config.BUFFER_MAX_IMAGES - 1 - end))
        cover = cover_for(draft)
        post["alt_texts"] = ([re.sub(r"[\[\]]", "", cover.get("headline", "")) + ". " + cover.get("sub", "")]
                             + [_alt(s["paragraphs"]) for s in body]
                             + (["Send this to " + re.sub(r"^(Send (this )?to )", "", (draft.get("end") or {}).get("send", ""), flags=re.I)
                                 + " " + (draft.get("end") or {}).get("save", "")] if end else []))
        n = 1 + len(body) + end
        if n > config.BUFFER_MAX_IMAGES:
            raise Overflow(f"{n} slides after splitting; Buffer allows {config.BUFFER_MAX_IMAGES}")
        images = [render_cover(cover_for(draft), n)]
        images += [render_slide(s["paragraphs"], i, n, s.get("big"), s.get("source")) for i, s in enumerate(body, 2)]
        if end:
            images.append(render_end(draft.get("end") or {}, n))
    paths = []
    for i, img in enumerate(images, 1):
        p = outdir / f"slide_{i:02d}.jpg"
        img.save(p, "JPEG", quality=92, optimize=True)
        paths.append(p)
    return paths
