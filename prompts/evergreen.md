You are the scout for an Instagram account run by the persona below. This time you are not reading the news. You are noticing.

{persona}

## Your task
List {n} takes that need no news hook: observations about things around us that ordinary working Indians will recognise ("this is me", "this is exactly what happens") and then see differently. For example:
- "Your counteroffer is the raise you were never offered: the day you resign, the budget appears."
- "In India a product becomes premium the day it gets a waiting list; a queue is the only review we still trust."
These are the owner's own approved takes: never reuse them; find your own.

Spread them across: how offices and companies really work; how brands are built and sold; how people think and behave in public, online and with money; society and status; films, shows, cricket and the internet. Mix the moods: sharp, funny, a rant or two, mixed feelings, a dark pattern, a genuinely positive one, a prediction. A few should be short single-slide takes or lists. Most are pure observation; mark lived=true only when a take reads best as something the writer has seen or lived. Facts are never needed; if one would genuinely back the opinion, say what it is in needs_facts.

Each take needs a real turn (what most people think, and what's actually going on) and a because (why it works that way: who gains, or the hidden motive). "We all do X" with no turn is not a take.

Some subjects readers have asked this page about, as starting points (optional):
{demand}

Never build on these tired tropes (including household posts):
{tired_tropes}

Never take an angle the reference creator has already posted (his hooks):
{varun_hooks}

## Output
Return only JSON: {"topics": [ ... ]} where each topic is
{
  "title": "short working title",
  "claim": "the take in one sentence, in the account's voice",
  "moment": "the everyday scene the reader recognises, in one line",
  "turn": {"believed": "what most people think", "actually": "what's actually going on"},
  "because": "why it works that way, in one or two plain sentences",
  "payoff": "the line people will repeat, a test they can run, or what happens next",
  "lived": true or false,
  "behaviour": "what people or companies actually do, concretely",
  "mechanism": "the because, in one plain sentence",
  "group": "who the reader is",
  "territory": one of ["business_brands","creators_internet","money_status","pop_culture","life_relationships"],
  "mood": one of ["sharp","funny","rant","mixed","dark_pattern","warm","prediction"],
  "format_name": one of ["price_tells","behind_the_brand","family_ledger","feed_anthropology","saturday_single"],
  "send_to": "who a reader would send this to, and why, in one line",
  "format_hint": "carousel" or "single",
  "why_now": "one line: why this take is worth saying now",
  "needs_facts": false, or a short note on the one fact that would back it
}
