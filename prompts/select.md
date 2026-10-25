You are choosing this month's takes for an Instagram account run by the persona below. You choose on the owner's behalf, so judge by the owner's taste, not your own.

{persona}

## The owner's taste (principles are ranked)
{principles}

Takes the owner approved, and why:
{approved}

Takes the owner rejected, and why:
{rejected}

Topics by the reference creator, for range and register only (never pick a take that repeats one of these angles):
{varun_hooks}

Takes already scheduled (never pick one too close to these):
{our_hooks}

## Candidates
{candidates}

## Your job
Score every candidate 1-5 on each of these, honestly:
- relatable (weight 3): would an ordinary working Indian say "this is me" or "this is exactly what happens"?
- fresh_angle (weight 3): does it make them see it differently ("never thought of it like that"), not just nod?
- shareable (weight 2): an obvious person to send it to, or an argument it starts.
- saveable (weight 1): a reason to come back to it, or a test they'll use.
- because (weight 1): is the reason it works that way clear and sharp?

Hard gates (a candidate failing any of these is out, whatever its score):
- relatable 4 or more, and fresh_angle 4 or more;
- a real turn: what people think, and what's actually going on;
- not a news recap, a data explainer or a meme;
- not a typical household post, a tired trope ({tired_tropes}), or too close to a rejected or scheduled take;
- not resting on one stranger's story or an accusation a source doesn't support.
Facts are never required.

Then pick the {n} best by weighted score, best first. Keep the set varied: roughly this mix of territories {mix}; a range of moods (sharp, funny, rant, mixed, dark_pattern, warm, prediction), with no single mood above a third; at most a quarter about offices, jobs, appraisals or layoffs (the page already has many); mostly pure observation, with lived takes (lived=true) at most a third; and a few that suit a single-slide take. If fewer than {n} candidates pass the gates, pick fewer; never pad.

Return only JSON:
{"picks": [{"id": "...", "scores": {"relatable": n, "fresh_angle": n, "shareable": n, "saveable": n, "because": n}, "why": "one line in the owner's terms", "format_fit": "carousel" | "single" | "either"}]}
format_fit: "carousel" for nearly every take; "single" only for a quick list, a one-line prediction or a short rant that would be weaker stretched over slides.
