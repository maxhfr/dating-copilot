# dating-copilot

Auto-liking for Tinder, using the Claude API. Scores every profile against
your rubric, swipes for you, and sends a Telegram digest.

Auto-liking only. The old messaging code is parked in
`_archive/messaging/` — see **Archived: messaging** at the bottom.

## What the swipe side does

Runs unattended. Three stages per profile:

0. **Numeric filters, in code, free.** Age, distance, height. Rejected
   here costs zero tokens and zero API calls.
1. **Stage 1 — text only** (~300 tokens). Language and profile quality,
   plus the text scoring categories. Most survivors of stage 0 die here.
2. **Stage 2 — vision** (~5k tokens). Scores 0-100 using the weights in
   `config/scoring.yaml`. Likes at or above the threshold.

You get a Telegram digest every `DIGEST_EVERY` profiles and at the end.
Tune `auto_like` in `scoring.yaml` based on what it liked.

## Setup (macOS)

```bash
cd dating-copilot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Create `.env` from `.env.example`:

```
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
MAX_LIKES=45
MAX_PROFILES=250
DIGEST_EVERY=30
```

**Telegram bot:** message @BotFather → `/newbot` → copy the token.
Then message your new bot once, and visit
`https://api.telegram.org/bot<TOKEN>/getUpdates` to find your chat ID.
(Or just message @userinfobot — for a private chat your user ID *is* the
chat ID.)

**Anthropic key:** console.anthropic.com → API keys. Billing must be
enabled, and set a monthly spend limit while you're in there. This is
separate from your claude.ai subscription.

Then verify everything before the first run:

```bash
python check_setup.py
```

Parser unit tests (offline, no API calls, no browser):

```bash
python test_parsers.py
```

## Running

```bash
./run.sh swipe            # Tinder (the default)
./run.sh swipe tinder     # platform can be named explicitly
```

or

```bash
source .venv/bin/activate && set -a && source .env && set +a
python src/main.py
```

To save raw profile text for building parser test fixtures, run with
`CAPTURE=1 ./run.sh swipe`. Files go to `~/.dating-copilot/captures/`
(outside the repo). They contain real names and bios, so anonymise before
sharing or committing.

First run opens a real Chromium window. Log into Tinder by hand — the
session persists in `~/.dating-copilot/` after that. The bot never sees
your password.

## Tuning

`auto_like: 58` is a starting guess, not a calibrated number. Read the
first digest, see what scores it gave people you'd actually have liked,
and move it. Too low and you burn 45 likes on mediocre matches; too high
and you don't spend them.

Don't touch the category weights until you've seen 50+ scores. The 70/30
photo/text split means a strong physical match clears the bar even with a
thin bio — if that's not what you want, raise the threshold rather than
reweighting.

## Staying unbanned

None of this makes you ban-proof. It makes the account look like a person
rather than a script, which is the difference between lasting months and
lasting days.

Built in:
- Non-uniform swipe pacing — most gaps 1-4s, but 8% run 20-75s and 12%
  are sub-second. Uniformity is more suspicious than speed.
- Randomised session size, 15% of scheduled runs skipped entirely
- Quiet hours 01:00-08:00
- Occasional idle behaviour mid-session (mouse movement, scrolling)
- Keyboard input rather than synthetic button clicks
- Persistent browser session — no repeated fresh logins
- Residential IP (your own machine). This is why a VPS would be worse.
- Like ratio lands around 15-20%, which reads as human
- Popup dismissal, including declining Tinder's AI data-sharing consent

Your part:
- Run it from cron 2-4x/day. Never continuously, never one long burst.
- Use the account by hand for a week or two before turning the bot on.
  A day-old account swiping 150 profiles looks much worse than an
  established one.
- `headless=False`. Headless is more detectable, and it's already the
  default here.
- If a session stops with a challenge screen, leave it alone for a few
  hours. Immediately retrying is itself a signal.

**Not built, deliberately:** fingerprint spoofing and CAPTCHA solving.
On a challenge screen the bot stops and pings you. Solve it yourself,
in the browser, or don't.

## Cron (macOS)

```
17 9,13,18,21 * * *  cd ~/dating-copilot && ./run.sh swipe >> ~/dating-copilot/swipe.log 2>&1
```

Odd minute values on purpose — jobs firing exactly on the hour is a
pattern too. Set `HOLD_ON_STOP=0` in `.env` once scheduled, so a stop
doesn't leave the browser hanging for 45s.

## Honest notes

**Selectors will break.** Tinder ships UI changes constantly and removed
`data-testid` entirely. Everything is in the `SEL` dict at the top of
`src/platforms/tinder.py` — when the bot stops finding cards, that's what
to fix. `debug_nocard.png` / `.txt` get written when the deck looks empty.

**`last_active_days` is unavailable on Tinder web.** The inactivity filter
in the rubric can't be applied there.

**This violates Tinder's ToS.** Accounts do get banned, and because the
account is phone-verified, a ban is sticky.

## Archived: messaging

The messaging side (chat loop, opener drafting, quality gate, persona and
date rules) is no longer part of the app. It lives in `_archive/messaging/`
with its original `src/` and `config/` layout, so it can be moved back if
it's ever revived. It is not run, imported or checked by anything here.
