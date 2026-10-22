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

## The account's recurring formats (tag each topic with one)
- price_tells: a price or number that hides a behaviour nobody admits.
- behind_the_brand: something a brand does to customers on purpose that looks like an accident.
- family_ledger: a money or status arrangement inside Indian families that nobody names.
- feed_anthropology: how people actually behave on Instagram and the internet.
- saturday_single: one quick, arguable take or short list for a single slide.
A topic is only worth it if there's an obvious person a reader would send it to.

## Output
Return only JSON: {"topics": [ ... ]} where each topic is
{
  "title": "short working title",
  "claim": "the take in one sentence, in the account's voice",
  "behaviour": "what people or brands actually do, concretely, with real names and places where natural",
  "mechanism": "why, in one or two plain sentences",
  "group": "who the reader is",
  "territory": one of ["business_brands","creators_internet","money_status","pop_culture","life_relationships"],
  "mood": one of ["sharp","funny","rant","warm","prediction"],
  "format_name": one of ["price_tells","behind_the_brand","family_ledger","feed_anthropology","saturday_single"],
  "send_to": "who a reader would send this to, and why, in one line (e.g. 'the friend who always adds chips to hit free delivery')",
  "format_hint": "carousel" or "single",
  "real_details": [],
  "why_now": "one line: why this take is worth saying now",
  "counterintuitive": true or false,
  "needs_facts": false
}
