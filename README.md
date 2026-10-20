# Ananya engine

Fully automated Instagram carousels for the Ananya Mishra persona:
Reddit → topics → filter → persona writer → carousel → Buffer → Instagram.

It runs on **GitHub Actions + your Claude subscription + Buffer**. There's no API key, no server and no n8n. The Claude Code CLI runs inside each GitHub job, signed in with a subscription token. State is JSON committed back to this repo.

## How it works

| Agent / step | When | What it does | Code |
| --- | --- | --- | --- |
| 1. Scout (persona) | 20th of each month | Reads the month's top threads from about 15 Indian subreddits through Reddit's public RSS feeds (no account needed), plus top comments for the 40 most promising. If Reddit blocks GitHub's servers, it falls back to Claude's web search over reddit.com. Outputs candidate topics with evidence | `engine/scout.py`, `engine/reddit.py`, `prompts/scout.md` |
| 2. Filter | Same run | Scores each candidate on mirror, group, arguable, emotion and send-to. Rejects niche advice and anything close to the reference creator's posts or ours. Fills next month's 17 slots by territory mix and keeps 5 spares | `engine/filter.py`, `prompts/filter.md` |
| 3. Writer (Ananya) | Daily, 3 posts a run | Writes each post from the real Reddit details. Searches the web for a sourced number only when the topic needs one | `engine/writer.py`, `prompts/persona.md`, `prompts/writer.md` |
| Critic | Inside 3 | Code checks: slide count, length, banned AI phrases, em dashes, copied 6-word runs from the reference, unsourced ₹ or % figures. Then an editor model. Then a blind test: can a judge pick the draft out from three real human posts? Up to 2 rewrites, otherwise a spare takes the slot | `engine/writer.py`, `prompts/critic.md`, `prompts/blindtest.md` |
| 4. Carousel | Inside the daily run | Renders 1080×1350 JPEG slides in the Facebook-post style (one weight, italics only where needed) and uploads them to a public GitHub repo for hosting | `engine/render.py`, `engine/storage.py` |
| Publish | Daily | Schedules anything due in the next 8 days in Buffer. Buffer posts it to Instagram | `engine/buffer.py` |

Slots: Mon, Wed and Fri at 19:30 IST (carousels), Sat at 11:00 IST (single slide). Change them in `engine/config.py`.

## One-time setup (about 20 minutes)

1. **Two GitHub repos:**
   - Push this folder to a **private** repo, `ananya-engine`. It holds the reference creator's text, so keep it private.
   - Create an empty **public** repo, `ananya-media`, with a README so `main` exists. Slides are hosted from it.
2. **Claude token:** on your laptop, run `claude setup-token`. It prints a one-year token for your subscription.
3. **Media token:** in GitHub, go to Settings → Developer settings → Fine-grained tokens. Create one with access to **only** `ananya-media` and the permission Contents: Read and write.
4. **Buffer:** connect the Instagram account (it must be a professional account). Then go to Settings → API → create a key.
5. **In `ananya-engine`, go to Settings → Secrets and variables → Actions:**
   - Secrets: `CLAUDE_CODE_OAUTH_TOKEN`, `BUFFER_API_KEY`, `MEDIA_REPO_TOKEN`
   - Variables: `MEDIA_REPO` = `<your-username>/ananya-media`
   - Do **not** add `ANTHROPIC_API_KEY`. It would override the subscription and bill the API instead.
   - The Buffer channel is found automatically from the Instagram handle `ananyakrishnan47` (`IG_HANDLE` in `engine/config.py`). Set `BUFFER_CHANNEL_ID` only if that lookup fails.
6. **Check everything:** go to Actions → engine → Run workflow → `doctor`. It tests the avatar, the Claude token, the Buffer channel, the media repo and the Reddit feed, and prints one OK or FAIL line for each.
7. **Avatar:** already set, in `assets/avatar.png`, cropped from the profile image.
8. **Calibrate:** run `calibrate`. The judge should rank the reference creator's best posts above his weakest at a pairwise accuracy of 0.65 or higher. Below that, tune `prompts/filter.md`.
9. **Start:** run `monthly`. It scouts and plans next month. From then on, the daily schedule writes and posts. To start this month instead, run `scout` from a terminal, then `filter --plan-month <this month>`.

## Day to day

- **Nothing to do.** Posts reach Buffer's queue about a week ahead, so you can delete any post there before it goes out.
- **Pause everything:** set the repository variable `ENGINE_PAUSED` to `true`. Nothing new gets scheduled. Posts already in Buffer still publish unless you pause the queue in Buffer.
- **Check progress:** each run's summary lists every post's status and the month's model calls. History is in `state/log.jsonl` and `state/calls.jsonl`.
- **A post says `failed`:** read `error` in `state/posts/<id>.json`. If a Buffer call had no confirmed result, check the Buffer queue first, then set the post's status back to `uploaded`.

## Subscription usage

- A month is about 150–200 model calls: the scout and filter once, then about 6–9 calls per post including rewrites and checks.
- To stay inside usage windows, the monthly run only scouts and plans. Each daily run writes `PRODUCE_PER_RUN` posts (default 3).
- If a run hits a usage limit, it stops cleanly and the next daily run continues.
- On a Pro plan, if Opus limits bite, set the repo variable `MODEL_WRITER` to `sonnet`.
- These runs share your subscription's limits with your own Claude use.

## Run locally

```bash
pip install -r requirements.txt          # plus the Claude CLI, signed in
python -m engine scout --month 2026-10
python -m engine filter --month 2026-10 --plan-month 2026-11
DRY_RUN=true python -m engine produce    # renders into out/, uploads and schedules nothing
python -m engine status
python -m pytest -q
```

## Honest limits

- **A weak or wrong post can still go out.** Everything is automatic, and Buffer's queue is your veto window. The critic and blind test reduce the risk; they don't remove it.
- **Reddit can block or rate-limit the anonymous RSS reader.** If it does, the scout falls back to web search, which gives thinner, summarised threads.
- **The AI label is your call.** Slide text is AI-written. `IG_AI_FLAG` controls Instagram's AI label, which is off by default because Meta's rules target photorealistic media.
- **Keep the engine repo private.** `data/varun_corpus.json` holds another creator's text and is used only for calibration and originality checks.
