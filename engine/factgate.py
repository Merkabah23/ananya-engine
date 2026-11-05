"""The fact gate: every checkable claim in the final text is checked against the world before a post can ship.

A  claim ledger: every atomic claim in the slides, caption and alt text (judge model, no tools)
B  arithmetic, computed in code
C  web verification that tries to prove each claim wrong (judge model + web)
D  mechanism skeptic: does the take's "how it works" actually hold? (writer model + web, when the take rests on one)
E  quotes confirmed on the live page; freshness and source strength decided in code against the go-live date

A pass stores a hash of the exact text, and the upload step refuses anything that changed after it was verified.
Failures go back to the writer as notes, never to an editing step that cuts.
"""
from __future__ import annotations

import ast
import hashlib
import html
import ipaddress
import json
import operator
import re
import socket
from datetime import date, datetime, timezone

import requests
from urllib.parse import urljoin, urlsplit

from . import config, llm

CHECKED = {"figure", "event", "superlative", "entity_attribute", "feature"}
STRICT = {"superlative", "entity_attribute"}   # need a primary source or two independent major ones
FRESH_DAYS = 30
IMMEDIATE = re.compile(r"\b(just|right now|this (week|month)|is testing|today|yesterday|recently|this weekend)\b", re.I)


def final_text(draft: dict) -> str:
    """Everything a reader sees: the cover, every slide with its big figure and source line, the end card's lines,
    the caption and the alt text."""
    cover = draft.get("cover") or {}
    proof = cover.get("proof") or {}
    parts = [f"[cover] {cover.get('headline', '')}\n{cover.get('sub', '')}\n{proof.get('figure', '')} {proof.get('label', '')}"]
    for i, s in enumerate(draft.get("slides", []), 1):
        big = s.get("big") or {}
        extra = "\n".join(x for x in (f"{big.get('figure', '')} {big.get('label', '')}".strip(), s.get("source", "")) if x)
        parts.append(f"[slide {i}] " + "\n".join(s.get("paragraphs", [])) + (f"\n{extra}" if extra else ""))
    end = draft.get("end") or {}
    parts.append(f"[end card] {end.get('save', '')}\n{end.get('send', '')}")
    parts.append(f"[caption] {draft.get('caption', '')}\n\n[alt text] {draft.get('alt_text', '')}")
    return "\n\n".join(parts).replace("*", "")


def text_hash(draft: dict) -> str:
    return hashlib.sha1(final_text(draft).encode()).hexdigest()


def still_valid(post: dict) -> bool:
    """True if the post's text is exactly the text that passed the gate."""
    v = post.get("verification") or {}
    return bool(v.get("passed")) and v.get("text_hash") == text_hash(post.get("draft") or {})


# --- A: claim ledger -------------------------------------------------------------------------------------------

def _sentences(text: str) -> list[str]:
    return [x for x in re.split(r"(?<=[.!?])\s+|\n+", re.sub(r"\[(cover|slide \d+|end card|caption|alt text)\]", "", text))
            if _norm(x)]


def ledger(draft: dict, due: str, prior: dict | None = None) -> list[dict]:
    """The post's checkable claims. With `prior` (the last ledger of this post and the text it was read from), claims
    from sentences that are still in the post are kept word for word, and only new sentences go to the model, so an
    edit to one line can't change how the rest is read (or which cached verdicts apply)."""
    text, kept, changed = final_text(draft), [], None
    if prior and prior.get("text"):
        seen = {_norm(x) for x in _sentences(prior["text"])}
        changed = [x for x in _sentences(text) if _norm(x) not in seen]
        body = _norm(text)
        kept = [c for c in prior.get("claims", []) if c.get("type") != "mechanism" and c.get("sentence")
                and _norm(c["sentence"]) in body]
        if not changed:
            return _numbered(kept + [c for c in prior.get("claims", []) if c.get("type") == "mechanism"])
    ask = ("List every checkable claim about the world in this Instagram post, including implicit ones, as atomic claims. "
           "Ignore opinions, jokes, rhetorical lines (\"Nobody cancelled the weddings\"), typical scenes framed as typical, "
           "everyday practices any Indian reader has seen for themselves (udhaar written in a kirana diary, a 'Quick chat' "
           "invite after a resignation, a relative saying 'itni door yaar'), general observations about everyday life (free "
           "places to sit are scarce, people keep returnable things they never return), the writer's reading of why people or "
           "businesses behave as they do, the details of the reader's own moment told to them in 'you' (how many sat at the "
           "table, what the bill came to, what a parent did that night: narration of a typical scene, not a claim about the world), everyday prices framed as typical texture (a ₹799 app, a ₹1 lakh phone, a ₹3 crore flat: what readers see on shelves and screens, not market data), "
           "and anything about the post itself or its sources. "
           "Do check how named companies, apps, rules and markets work, and any figure. Types: figure (a number presented as real data), event (something "
           "that happened or is happening; note how it is framed), superlative (record, first, biggest, lowest, best-selling), "
           "entity_attribute (a named company or person is profitable, owned by, valued at, does X), feature (an app, "
           "platform, label or rule works a certain way, who pays what), arithmetic (a number worked out from others), "
           "mechanism (the post's central 'how this works' argument, as premises and a conclusion), anecdote (one person's "
           "experience).\n"
           f"The post goes live on {due[:10] or 'an unknown date'}.\n\n## Post\n{final_text(draft)}\n\n"
           'Return only JSON: {"claims": [{"id": "c1", "text": "the claim in one plain sentence", "sentence": "the post\'s '
           'words", "type": "...", "core": true if the take collapses when this is false, "framed_as": "current only when '
           'the post presents it as just happened or happening now (just, now, this week, this month, is testing); past for '
           'anything dated or over; timeless for how things work and annual figures", '
           '"expr": "arithmetic only: the sum in digits, e.g. 86999/6", "stated": "arithmetic only: the number the post states"}]}')
    if changed is not None:
        ask += ("\n\nThe rest of this post was already checked. List only claims whose words come from these new "
                "sentences, plus the post's mechanism claim:\n" + "\n".join(f"- {x}" for x in changed))
    out = llm.call_json(config.MODEL_JUDGE, ask, stage="ledger")
    return _numbered(kept + [c for c in out.get("claims", []) if isinstance(c, dict) and c.get("text")])


def _numbered(claims: list[dict]) -> list[dict]:
    return [{**c, "id": f"c{i}"} for i, c in enumerate(claims, 1)]


# --- B: arithmetic --------------------------------------------------------------------------------------------

def _num(s: str) -> float | None:
    m = re.search(r"-?\d[\d,]*\.?\d*", str(s or "").replace(",", ""))
    return float(m.group(0)) if m else None


def arithmetic_ok(claim: dict) -> bool | None:
    expr = re.sub(r"[,\s₹]|rs\.?", "", str(claim.get("expr") or ""), flags=re.I).replace("x", "*").replace("×", "*")
    stated = _num(claim.get("stated"))
    if not expr or stated is None or not re.fullmatch(r"[\d.+\-*/()%]+", expr):
        return None
    try:
        value = _calc(ast.parse(expr.replace("%", "/100"), mode="eval").body)
    except (ValueError, SyntaxError, ZeroDivisionError):
        return None
    return abs(value - stated) <= max(abs(value) * 0.01, 1)


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def _calc(node: ast.AST) -> float:
    """Evaluate + - * / on numbers only (no powers, names or calls)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_calc(node.left), _calc(node.right))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_calc(node.operand)
    raise ValueError("unsupported expression")


# --- C: web verification --------------------------------------------------------------------------------------

def web_verify(claims: list[dict], due: str, leads: list[dict]) -> dict:
    if not claims:
        return {}
    ask = ("You are a fact checker for an opinion page whose numbers paint a picture for readers; they are not a business "
           "deck. A claim is supported when its picture is right: the right direction and roughly the right size. Rounded, "
           "approximate or slightly older figures ('about 40%', 'around 4 in 5', last year's report) are supported. A claim is "
           "contradicted only when the picture is wrong: the opposite direction, off by more than about a quarter, or something "
           "that never happened. For each claim, use WebSearch and WebFetch to find one reliable source (a regulator, "
           "industry body, research firm or major outlet); the leads are where the writer got it, and they count if they say it.\n"
           "- event framed as current: find the FIRST report date.\n"
           "- superlative: check the full series, and whether it still holds on the go-live date.\n"
           "- entity_attribute: the latest results or filing; state the financial year.\n"
           "- feature: the app's or platform's own page or announcement.\n"
           "- anything framed as current (now, this month): check it is still true on the go-live date; if it was true "
           "earlier but no longer is, the verdict is outdated.\n"
           f"The post goes live on {due[:10] or 'an unknown date'}.\n\n## Claims\n"
           + json.dumps([{k: c.get(k) for k in ("id", "text", "type", "framed_as")} for c in claims], ensure_ascii=False, indent=1)
           + "\n\n## Leads\n" + json.dumps([{k: s.get(k) for k in ("url", "fact", "date")} for s in leads], ensure_ascii=False)
           + '\n\nReturn only JSON: {"verdicts": [{"id": "c1", "verdict": "supported|contradicted|outdated|misframed|'
           'unverifiable", "event_date": "YYYY-MM-DD when the fact or event first happened, if dated", "correct": "what is '
           'actually true, if different", "sources": [{"url": "...", "publisher": "...", "published_date": "YYYY-MM-DD", '
           '"quote": "the exact words on the page that support or contradict it", "tier": 1 for primary, 2 for a major '
           'outlet, 3 for an aggregator or blog}]}]}')
    out = llm.call_json(config.MODEL_JUDGE, ask, stage="verify", tools=["WebSearch", "WebFetch"], timeout=1500)
    return {v.get("id"): v for v in out.get("verdicts", []) if isinstance(v, dict)}


# --- D: mechanism skeptic -------------------------------------------------------------------------------------

def skeptic(draft: dict, claims: list[dict], due: str) -> dict:
    ask = ("Assume the central argument of this Instagram post is wrong, and test it. Using primary sources where you can "
           "(tax law and rates, how a price, fee or commission is actually set, how the product or process really works), "
           "explain how this actually works. Does each premise hold, and does the conclusion follow? Small wording issues are "
           "not your job; only whether the take itself stands. This page is opinion: a reading of someone's motive offered "
           "as the writer's view, an interpretation of a moment, or a generalization about everyday life is not a premise to "
           "falsify. Fail a premise only when it states something demonstrably untrue about how a product, price, fee, law, "
           "contract or market works, or who pays for what.\n"
           f"The post goes live on {due[:10] or 'an unknown date'}.\n\n## Post\n{final_text(draft)}\n\n## Its argument\n"
           + json.dumps([c.get("text") for c in claims], ensure_ascii=False)
           + '\n\nReturn only JSON: {"holds": true or false, "broken_premise": "which premise fails, if any", '
           '"actual_mechanism": "how it really works, in two or three sentences", "take_survives": true if a corrected '
           'version of the take still makes the same point, "sources": [{"url": "...", "published_date": "...", "quote": "..."}]}')
    return llm.call_json(config.MODEL_WRITER, ask, stage="skeptic", tools=["WebSearch", "WebFetch"], timeout=1500)


# --- E: evidence and the rules, in code -----------------------------------------------------------------------

def _norm(text: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"[^a-z0-9%₹.]+", " ", text.lower()).strip()


MAX_BYTES = 3_000_000


def _public(url: str) -> bool:
    """Only plain web pages on public addresses: the URLs come from model output, and the runner must never be
    steered to a private network, a loopback service or a cloud metadata endpoint."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.port not in (None, 80, 443):
        return False
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
    except OSError:
        return False
    return all(ipaddress.ip_address(i[4][0]).is_global for i in infos)


def _peer_is_global(r: requests.Response) -> bool:
    try:
        sock = r.raw.connection.sock
        return ipaddress.ip_address(sock.getpeername()[0]).is_global
    except Exception:
        return False  # can't see where we connected: don't read it


def _fetch(url: str, hops: int = 3) -> tuple[int, str, str] | None:
    """GET a public page, re-checking every redirect and reading at most MAX_BYTES. None if it can't be fetched."""
    for _ in range(hops + 1):
        if not _public(url):
            return None
        session = requests.Session()
        session.trust_env = False  # ignore proxy settings from the environment
        try:
            r = session.get(url, timeout=20, stream=True, allow_redirects=False,
                            headers={"User-Agent": "Mozilla/5.0 (fact check)"})
        except requests.RequestException:
            return None
        if not _peer_is_global(r):  # the address actually connected to, not the one checked (DNS rebinding)
            r.close()
            return None
        if r.is_redirect and r.headers.get("location"):
            url = urljoin(url, r.headers["location"])
            r.close()
            continue
        body = b""
        for chunk in r.iter_content(64_000):
            body += chunk
            if len(body) >= MAX_BYTES:
                break
        r.close()
        return r.status_code, r.headers.get("content-type", ""), body.decode(r.encoding or "utf-8", "replace")
    return None


def quote_on_page(url: str, quote: str) -> bool | None:
    """True if the page carries the quote's numbers and most of its words (checkers paraphrase), False if the page doesn't
    exist or clearly doesn't say it, None if it can't be read here (blocked, paywalled, rendered by script)."""
    if not quote:
        return False
    fetched = _fetch(url)
    if fetched is None:
        return None
    status, ctype, text = fetched
    if status in (404, 410):
        return False
    if status != 200 or "pdf" in ctype.lower():
        return None  # blocked, or a PDF we can't read here
    page, q = _norm(text), _norm(quote)
    if len(page.split()) < 400:
        return None  # a bot wall or a page rendered by script, not the article
    numbers = [n for n in re.findall(r"\d[\d.]*", q) if len(n) > 1 or "." in n]
    words = [w for w in q.split() if len(w) > 3 and not w[0].isdigit()]
    if not words and not numbers:
        return None
    share = sum(w in page for w in words) / len(words) if words else 1.0
    if all(n in page for n in numbers) and share >= 0.6:
        return True
    if share < 0.3 or (numbers and not any(n in page for n in numbers)):
        return False
    return None


def _date(s: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(str(s or "")[:len(fmt) + 2].strip(), fmt).date()
        except ValueError:
            continue
    return None


def judge(claim: dict, verdict: dict | None, due: str, fetch=quote_on_page) -> str | None:
    """None if the claim stands, otherwise the note for the writer."""
    text = claim.get("text", "")
    if claim.get("type") == "arithmetic":
        ok = arithmetic_ok(claim)
        return None if ok is not False else f"The sum is wrong: '{text}' ({claim.get('expr')} is not {claim.get('stated')})."
    if claim.get("type") not in CHECKED:
        return None
    if not verdict:
        return f"Could not verify: '{text}'. Cut it, or state it only if a source says it."
    kind = verdict.get("verdict")
    correct = f" What's true: {verdict['correct']}." if verdict.get("correct") else ""
    if kind == "contradicted":
        return f"Wrong: '{text}'.{correct}"
    if kind in ("outdated", "misframed"):
        return None  # the page's numbers paint a picture, not a business deck: older or rounded is fine, wrong is not
    if kind != "supported":
        return f"Could not verify: '{text}'. Cut it, or state it only if a source says it."
    sources = [s for s in verdict.get("sources", []) if isinstance(s, dict) and s.get("url")]
    checks = [(s, fetch(s["url"], s.get("quote", ""))) for s in sources]
    confirmed = [s for s, ok in checks if ok]
    if checks and all(ok is False for _, ok in checks):
        return f"Could not confirm: '{text}' (the cited pages don't say it). Use a source that does, or cut it."
    # One reachable source that supports it is enough: the numbers draw a picture, they aren't a business deck.
    return None


def verify(post: dict, draft: dict, fetch=quote_on_page) -> dict:
    due = post.get("due") or ""
    cache = post.setdefault("verification_cache", {})
    done = cache.get("_by_text", {}).get(text_hash(draft))
    if done:  # exactly this text was judged before: the same verdict, no new calls
        return {**done, "at": datetime.now(timezone.utc).isoformat()}
    claims = ledger(draft, due, cache.get("_ledger"))
    cache["_ledger"] = {"text": final_text(draft), "claims": claims}
    checkable = [c for c in claims if c.get("type") in CHECKED]
    fresh = [c for c in checkable if c["text"] not in cache]
    verdicts = {c["id"]: cache[c["text"]] for c in checkable if c["text"] in cache}
    if fresh:
        new = web_verify(fresh, due, (post.get("sources") or []) + list(post["topic"].get("proof") or []))
        for c in fresh:
            if c.get("id") in new:
                verdicts[c["id"]] = cache[c["text"]] = new[c["id"]]
    notes = [n for c in claims if (n := judge(c, verdicts.get(c.get("id")), due, fetch))]
    mechanism, take_dead = None, False
    argument = [c for c in claims if c.get("type") in ("mechanism", "entity_attribute")]
    if argument:  # the same argument gets the same verdict, so a wording edit elsewhere can't flip it
        key = hashlib.sha1(json.dumps(sorted(c.get("text", "") for c in argument)).encode()).hexdigest()
        mechanism = cache.setdefault("_skeptic", {}).get(key) or skeptic(draft, argument, due)
        cache["_skeptic"][key] = mechanism
        if mechanism.get("holds") is False:
            take_dead = mechanism.get("take_survives") is False
            notes.insert(0, f"The take's premise is wrong: {mechanism.get('broken_premise')}. How it actually works: "
                            f"{mechanism.get('actual_mechanism')} Rebuild the post on the correct mechanism.")
    result = {"passed": not notes, "take_dead": take_dead, "notes": notes, "ledger": claims, "verdicts": verdicts,
              "mechanism": mechanism, "text_hash": text_hash(draft), "at": datetime.now(timezone.utc).isoformat()}
    cache.setdefault("_by_text", {})[result["text_hash"]] = result
    return result
