# dating-copilot

Swipe filtering + chat drafting for Tinder, on macOS, using the Claude API.

## What it does

Runs unattended. Two-stage evaluation per profile:

1. **Stage 1 — text only** (~300 tokens). Hard filters from
   `config/rubric.yaml`: age, distance, language, smoking, drinking,
   height, empty profiles. Most profiles die here, cheaply. Swipes left.
2. **Stage 2 — vision** (~5k tokens). Survivors only. Scores 0-100 using
   the weights in `config/scoring.yaml`. Likes at or above the threshold.

You get a Telegram digest when the session ends. Tune `auto_like` in
`scoring.yaml` based on what it liked.

Chat drafting (`src/chat.py`) writes replies in your voice and escalates
to Telegram the moment a plan starts forming. It never confirms anything.

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
```

**Telegram bot:** message @BotFather → `/newbot` → copy the token.
Then message your new bot once, and visit
`https://api.telegram.org/bot<TOKEN>/getUpdates` to find your chat ID.

**Anthropic key:** console.anthropic.com → API keys. Billing must be
enabled. This is separate from your claude.ai subscription.

## Running

```bash
source .venv/bin/activate && set -a && source .env && set +a
python src/main.py
```

First run opens a real Chromium window. Log into Tinder by hand — the
session persists in `~/.dating-copilot/` after that. The bot never sees
your password.

## Honest notes

**Selectors will break.** Tinder ships UI changes constantly. Everything
is in the `SEL` dict at the top of `platforms/tinder.py` — when the bot
stops finding cards, that's what to fix.

**Tune the threshold on the first few runs.** `auto_like: 62` is a
starting guess, not a calibrated number. Read the first digest, see what
scores it gave people you'd actually have liked, and move it. Too low and
you burn 45 likes on mediocre matches; too high and you don't spend them.

**`last_active_days` is None on Tinder web.** The inactivity filter can't
be applied there — the web client doesn't expose it. It works on Hinge.
Bumble shows a recently-active badge that can be scraped.

**Rate.** `MAX_LIKES` caps likes per session at 45; `MAX_PROFILES` caps
how many it looks at. Free Tinder gives roughly 50-100 likes per 12h.
Several shorter sessions across the day look far more normal than one
long burst — cron it 3-4x daily rather than running it continuously.

**This violates Tinder's ToS.** Accounts do get banned. You've said the
accounts are disposable — just don't attach a phone number or payment
method you care about.

## Chat loop

```bash
python src/chat_loop.py
```

Polls matches every ~25 minutes (jittered). Decides opener / follow-up /
reply per match, drafts it, sanitizes it, sends it. State lives in
`~/.dating-copilot/chat_state.json` so restarts don't double-message.

- No reply to the opener → one follow-up after 3-4 days, different angle
- No reply to that → dormant, never messaged again
- Anything resembling a plan → Telegram, and it waits for your tap

## Staying unbanned

None of this makes you ban-proof. It makes the account look like a person
rather than a script, which is the difference between lasting months and
lasting days.

Built in:
- Non-uniform swipe pacing — most gaps 1-4s, but 8% run 20-75s and 12%
  are sub-second. Uniformity is more suspicious than speed.
- Randomised session size, 15% of scheduled runs skipped entirely
- Quiet hours 01:00-08:00, no swiping and no messages sent
- Occasional idle behaviour mid-session (mouse movement, scrolling)
- Messages typed character by character with variable delay, not pasted
- Persistent browser session — no repeated fresh logins
- Residential IP (your Mac). This is why a VPS would have been worse.
- Like ratio lands around 15-20%, which reads as human

Your part:
- Run it from cron 3-4x/day. Never continuously, never one long burst.
- Use the account by hand for a week or two before turning the bot on.
  A day-old account swiping 150 profiles looks much worse than an
  established one.
- Don't attach a phone number, payment method, or social account you care
  about.
- If a session stops with a challenge screen, leave it alone for a while.
  Immediately retrying is itself a signal.

**Not built, deliberately:** fingerprint spoofing and CAPTCHA solving.
On a challenge screen the bot stops and pings you. Solve it yourself,
in the browser, or don't.

## Cron

```
17 9,13,18,21 * * *  cd ~/dating-copilot && ./run.sh swipe
*/25 * * * *         cd ~/dating-copilot && ./run.sh chat
```

Odd minute values on purpose — jobs firing exactly on the hour is a
pattern too.

## Not yet built

- `platforms/bumble.py` — same shape, bumble.com is also web-based
- `platforms/hinge.py` — needs Android emulator + ADB, mobile-only
