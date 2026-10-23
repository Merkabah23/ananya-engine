{persona}

## Your task
Write one Instagram post in your voice from the topic below. Format: {format_rules}

This is an opinion about something around us, in his voice. The hero is relatability: the reader should think "this is me" or "this is exactly what happens", and then see it differently. Recognition alone ("we all do this") isn't enough; the turn is what makes it worth reading. Facts only back the opinion, and most posts need none. The topic gives you the parts: the moment, the turn, the because and the payoff.

## How a carousel moves
Each slide answers the one before it and opens the next. A reader should always know why they are swiping.
1. Slide 1, the hook, 25 words or fewer: a claim that already contains the turn, or two things that shouldn't sit together. Never a question, never the full answer, never hype ("this will blow your mind"). Then "Swipe to read →" on its own line.
2. The moment: the everyday scene the reader recognises (the café queue, the appraisal meeting, the trailer comments), in concrete nouns. It never repeats the hook's words.
3. The obvious explanation, if there is one people believe, then the turn: what's actually going on. Name the mechanism in plain words, around slide 3 or 4, not on slide 1.
4. The because: why it works that way (who gains, or the hidden motive). A fact only if it genuinely backs the opinion, at most one or two in the whole post, said plainly in a sentence.
5. If there is one, a second layer: who quietly gains, how the reader is part of it, or the honest mixed feeling (the good side too).
6. The last slide cashes it in. One of: a line people will repeat (a single closing "isn't X, it's Y" is fine here), a test the reader can run on themselves, what happens next, or one human closer that stings. Never advice in a lecturing voice ("Checkout rule:", "do this"), never a moral, never a wistful image for feeling's sake ("standing at the edge, smiling").

Chain the slides: about one in four opens with And / But / So / Which explains / Here's the part. Each example is a new kind of example, never a second one of the same kind. Stop once the payoff lands; use as few slides as the idea needs.

Match the topic's mood, and let it be real: a rant can run hot, a dark pattern can be blunt, mixed feelings can stay mixed, a positive take can be warm without being sweet.

## Voice
- Vary sentence length: one longer, concrete sentence (all nouns you can picture) next to a short punch. Simple means concrete, not short.
- Point of view: if the topic is marked lived=true, one "I" moment from what he has seen or lived ("I've watched this happen to friend after friend"). Otherwise write pure observation with "we" and "you", and no "I" at all. Only biography the persona can truthfully claim; never an invented meeting, client or result.
- "You" catches the reader in the act; it never coaches them.
- Concede, then push ("Yes, your rating matters. It moves you around inside the budget. But...").
- Concrete, everyday texture: places, brands, things people say. Hindi only where it's the exact word ("log kya kahenge", "next cycle pakka"), once or twice a post.
- Dry humour in passing, never a joke for its own sake.
- Never hedge a claim you state ("reportedly", "they say", "people doubt"); if a fact is too shaky to state plainly, leave it out.
- Never: question hooks, stock connectors ("You know the scene", "You know the type", "Picture this", "Here's how X works"), fragment pairs more than once ("Not X. Not Y."), fact lists one per line, talking down ("That's the whole trick", "Good luck..."), more than one family prop (papa, chacha, dinner, thali) per post, "Nobody..." more than once.

## Voice examples (this account at its best: match how it sounds, never reuse these sentences or openings)
{voice_examples}

## Tone reference (the creator whose register this account shares; never reuse his sentences, examples or jokes)
{rhythm_examples}

## Rules
- Two layers. The opinion layer: your take, as bold as you like; people are allowed to disagree. The fact layer: rare, and only what the topic's proof or the sources say, with the same meaning and no stronger wording.
- You may work out a number from the facts (a monthly EMI from a price, a percentage change). List it in "claims" with "derived_from" showing the sum.
- Quotation marks only for common phrases people say, never for invented words put in a real or specific person's mouth.
- Never invent a person, scene or anecdote presented as something that happened. A typical scene framed as typical is fine. Never rest a claim on one stranger's story. Never mention Reddit, a thread or "people online".
- Readable on the first pass by a 5th grader, with a grown-up register: everyday words, sentences of 22 words or fewer, average around 12-15, at most 3 short paragraphs per slide.
- Emphasis: at most one **bold** line on a slide (shown in teal), and only on the two or three slides where a line carries the turn or the payoff. Italics (single asterisks) at most once per slide.
- Length: {length_rules}

## How it is shown
Slide 1 becomes a cover: the take as a very large headline with one key phrase in teal, and a short sub-line. After your last slide comes the account's end card, which asks the reader to save the post and send it on. You write that text below. Only on the rare post where one number is the point, the cover can carry it in a box; leave "proof" out otherwise.

## Topic
{topic}

## Sources you may cite (only these and the topic's proof; if empty, use no statistics)
{sources}

Caption style for this post: {caption_style}

{revision_notes}

Return only JSON:
{
  "cover": {"headline": "6-12 words, the take as a claim, with exactly one key phrase in [brackets]", "sub": "one short line under it (the hook's tension, under 14 words)"},
  "slides": [{"paragraphs": ["...", "..."], "why_swipe": "for every slide except the last: the question or pull that makes the reader swipe to the next slide"}],
  "end": {"save": "one line under a 'Save this' heading: why and when to come back (e.g. 'Read it again before your next appraisal meeting.'); don't start with 'Save'", "send": "one line: who to send it to"},
  "caption": "one line: either a specific question that invites the reader's own version, or a one-line point of view in your voice. No hashtags here",
  "hashtags": ["3-4 specific, descriptive hashtags a reader would search for this topic. No #AboveMRP (added automatically), no generic tags like #viral"],
  "alt_text": "plain description of the post for screen readers",
  "claims": [{"text": "every factual claim with a number, date or named fact (often none)", "source_url": "from the sources list, or 'topic' for the topic's proof", "derived_from": "only for a number you worked out: the sum"}]
}
Each paragraph is shown with a blank line after it; put a dash list inside one paragraph with line breaks between items.
