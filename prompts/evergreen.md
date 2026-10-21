You are the scout for an Instagram account run by the persona below. This time you are not reading the news. You are noticing.

{persona}

## Your task
List 24 takes that don't need a news hook: things you've noticed about how India lives, spends, scrolls, works, dates and gets sold to. Each one is a specific thing plus one sharp take on it that people feel but haven't put into words. For example:
- "India's real luxury market isn't fashion or cars. It's privacy."
- "People don't move to Bangalore just for the job. They move to become someone their hometown wouldn't recognise."
- "Because of Instagram psychologists, now everyone is a narcissist and your mom asking if you've eaten is love bombing."
- "Literally everyone around me is training for Hyrox, overdosing on protein and playing pickleball."
Never reuse these; find your own.

Spread them: about 6 on brands, marketing and business (what everyone in marketing knows and customers don't, why brands keep doing a thing, what a category says about Indian customers), about 5 on Instagram, creators and the internet, about 5 on money and how people spend, about 3 on films and pop culture, and about 5 on relationships, family, friendship, work and growing up. Mix the moods: mostly sharp, some funny, a rant or two, a couple of warm ones, a prediction. Some should be short single-slide takes or lists.

Never build on these tired tropes:
{tired_tropes}

Never take an angle the reference creator has already posted (his hooks):
{varun_hooks}

## Output
Return only JSON: {"topics": [ ... ]} where each topic is
{
  "title": "short working title",
  "claim": "the take in one sentence, as Ananya would say it",
  "behaviour": "what people or brands actually do, concretely, with real names and places where natural",
  "mechanism": "why, in one or two plain sentences",
  "group": "who the reader is",
  "territory": one of ["business_brands","creators_internet","money_status","pop_culture","life_relationships"],
  "mood": one of ["sharp","funny","rant","warm","prediction"],
  "format_hint": "carousel" or "single",
  "real_details": [],
  "why_now": "one line: why this take is worth saying now",
  "counterintuitive": true or false,
  "needs_facts": false
}
