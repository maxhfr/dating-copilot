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

Unit tests (offline, no API calls, no browser):

```bash
python test_parsers.py     # page-text parsers, platform registry
python test_session.py     # swipe loop, run log, stop/start (fake platform)
python test_app.py         # settings, keys and the local web app
python test_schedule.py    # schedule limits, scheduler, login agent
python test_packaging.py   # paths and browser-setup helpers
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

## Control app

```bash
pip install -r requirements.txt   # adds Flask and pywebview
./run.sh app
```

Opens a window with four tabs: **Run** (Start/Stop, live feed of every
profile with score and reason), **Calibration** (score histogram and like
rate, for choosing `auto_like`), **Settings** (age, distance, height,
threshold, session limits, quiet hours) and **Setup** (what is configured).

- Every profile reviewed is logged to `~/.dating-copilot/runlog.db`
  (name, age, score, reason; no photos or bios), including CLI runs.
- Settings edit `config/rubric.yaml` and `config/scoring.yaml` in place, so
  comments survive. Scoring weights are not editable in the app, and the
  session limits are capped (100 likes, 500 profiles) on purpose.
- A manual Start skips the random "skip this run" roll but still respects
  quiet hours.
- The server listens on 127.0.0.1 only; every action needs a per-launch token.
- **Setup tab:** "Log in to Tinder" opens the browser; log in by hand and it
  closes itself and remembers you. API keys are saved to the macOS Keychain
  (write-only: they are never shown again). Precedence is shell environment,
  then keychain, then `.env`.
- **Schedule tab:** up to 4 sessions a day, at least 3 hours apart, none in
  quiet hours, with jitter. Scheduled runs keep the random skip. The app must
  be open and the Mac awake at those times. The app keeps the Mac awake only
  while a session is running (macOS `caffeinate`; the screen may still turn
  off, and a closed lid still sleeps it); otherwise the Mac sleeps normally.
  A time missed while asleep runs once, late, when the Mac wakes (within 2
  hours, and never within 2 hours of another session). To have macOS open the
  app at login: `python packaging/launch_agent.py install` (and `uninstall`).
- **Why not a server or a Raspberry Pi?** The account is fragile and the
  browser must stay headed on a home connection. A server or headless board
  means a different device and network and is the riskiest way to run this.
  A spare Mac that stays on at home is the safe always-on option.
- Without `pywebview` the app opens in your browser instead.

## Packaging a Mac app

The app icon lives in `packaging/icon/` (`icon.svg` is the source; `icon_1024.png`
and `icon.icns` are generated from it and committed).

```bash
./packaging/build_mac.sh
```

Builds `dist/Dating Copilot.app` with PyInstaller (run it on the Mac you will
use it on). It is unsigned, which is fine for personal use: right-click the
app, choose **Open**, and confirm. If macOS still refuses:
`xattr -dr com.apple.quarantine "dist/Dating Copilot.app"`.

- Chromium is not bundled; the app downloads it on first launch (~190 MB).
- Inside the app, the editable config is copied to `~/.dating-copilot/config/`
  on first launch, and `.env` can live in `~/.dating-copilot/.env`.
- The spec is `packaging/dating-copilot.spec`. The build was verified on Linux
  (it serves the UI and seeds its config); the macOS `.app` bundle itself has
  not been built yet.

## Windows

The same app runs on Windows (the browser window comes from Edge WebView2).

- **Easiest: let GitHub build it.** On GitHub open the repository's **Actions**
  tab, choose **build**, press **Run workflow**, and when it finishes download
  `DatingCopilot-windows.zip` (and `DatingCopilot-mac.zip`) from the run's
  Artifacts. Unzip it and double-click `dating-copilot.exe`.
- **Or build it yourself** on the Windows PC:
  `powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1`.
- The app is unsigned, so Windows says "Windows protected your PC": click
  **More info** then **Run anyway**.
- From source: `run.bat app` (window) or `run.bat swipe` (command line).
- Keep the PC awake during sessions (done automatically), and open the app at
  login with `python packaging\launch_agent.py install` (`uninstall` removes it).
- The Tinder login is per machine, so log in again on each. Don't run the app
  on two machines at the same time: the account is fragile and the daily
  session limits are counted per machine.
- Not verified on a real Windows PC yet: the CI build and import check pass,
  but tell me what you see when you try it.

## Tuning

`auto_like: 65` is a starting guess, not a calibrated number. Read the
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
