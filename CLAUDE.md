# dating-copilot — project brief for Claude Code

Read this first. It is the full context for the project: who it's for, what
exists, what's been learned the hard way, and what to build next.

## 1. Goal

A **personal desktop app** (Max's own use only, never distributed) that he
opens, presses Start, and it swipes for him on dating apps automatically.

- Platform order: **Tinder first** (works today), then **Hinge**, then **Bumble**.
  Develop and stabilise everything on Tinder before touching the others.
- Runs on Mac now (also had a Windows PC before). Target: a Mac `.app`
  first; Windows `.exe` later if wanted.
- Scope is **auto-liking only**. The messaging side (chat.py, gate.py,
  chat_loop.py, style.py) was deprioritised because drafted messages weren't
  good enough. It now lives in `_archive/messaging/`. Do not extend it unless
  asked.
- Not a product. No accounts, no server, no telemetry, no multi-user.
  Max supplies his own Anthropic API key.

## 2. User

Max, Paris, French/English/Romanian. Comfortable with Python, data tooling and
dashboards; not a frontend specialist. Wants things that work over things that
are clever. UI copy in English is fine, but Tinder itself runs in **French**
(selectors and parsers depend on French labels, see section 6).

## 3. What exists (working)

Python 3, Playwright (Chromium, persistent profile), Anthropic API, Telegram
Bot API.

```
config/rubric.yaml    hard filters (age, distance, height, obese, min_photos)
config/scoring.yaml   70 photo / 30 text weights, thresholds.auto_like = 65
src/main.py           the swipe session (entry point)
src/judge.py          3-stage evaluation (see below)
src/notifier.py       Telegram digests / alerts
src/platforms/tinder.py   all Tinder DOM logic (SEL dict at top)
check_setup.py        preflight checks (files, .env, deps, APIs, chromium)
run.sh                ./run.sh swipe
```

### Evaluation pipeline (src/judge.py)

0. **Code filters, free:** age 26-34, distance <= 20 km, height <= 173 cm
   if stated, reject obese, min 2 photos. Smoking and drinking filters are
   deliberately **off**.
1. **Stage 1, text only, Haiku 4.5 (~300 tokens):** language (French or
   English OK, assume French if unstated), profile quality, text scores. May
   only reject on `language` and `profile_quality`. Do not let the model
   reject on anything else (it over-rejected on intent, pets, and did age
   arithmetic wrong; those moved to code).
2. **Stage 2, vision, Haiku 4.5 (~5k tokens):** scores against scoring.yaml.
   Like if score >= `auto_like`.

Scoring weights (sum to 100): photo 70 = body_type 30, hair 16, eyes 12,
photo_style 5, photo_variety 4, filters 3; text 30 = bio_effort 12,
shared_interests 12, intent_fit 6. Obese = -999 (hard reject).
Max's physical preferences: slim/average/athletic body types score highest,
blonde hair and blue eyes score highest. **Ethnicity is intentionally not
evaluated anywhere.** Keep it that way.

The API uses prompt caching and JSON-only outputs with an outermost-`{...}`
fallback parser. Screenshots are JPEG; media type is sniffed from magic
bytes (a PNG declared as JPEG caused a 400 once).

### Session behaviour (src/main.py)

- `headless=False` always. Headless got the account flagged.
- Randomised like cap (45-100% of `MAX_LIKES`) and profile cap per session,
  15% of runs skipped at random, quiet hours 01:00-08:00.
- Interim Telegram digest every `DIGEST_EVERY` profiles, final digest always
  sent (try/except around the session).
- Stops immediately on any challenge / CAPTCHA / "activité suspecte" screen
  and alerts. **Never solve or evade challenges. Never add fingerprint
  spoofing.** That is a hard rule of this project.

## 4. Environment

`.env` (never commit; `.gitignore` excludes it):
`ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `MAX_LIKES=45`,
`MAX_PROFILES=250`, `DIGEST_EVERY=30`, optional `HOLD_ON_STOP`, `JUDGE_DEBUG`.
Browser session persists in `~/.dating-copilot/tinder-session`.

Security note: the old Telegram bot token was pasted in a chat during setup.
It should be revoked in BotFather and replaced. In the app, move secrets to
the OS keychain (`keyring`) rather than a plaintext `.env`.

## 5. Next steps (the actual task)

**Status (Oct 27 2026):** Phase 0 passed on live Tinder. Phases 1-3 are done
and pushed on branch `phase1-platform-interface`: Platform interface and
registry, local control app (Run / Calibration / Settings / Schedule /
Setup, SQLite run log, keychain), scheduler with limits. Phase 4 has a
PyInstaller spec and build script, validated on Linux; the macOS `.app` build
and the native window still need a first run on Max's Mac. Messaging code is
archived in `_archive/messaging/`. Phase 5 (Hinge, Bumble) has not started.

Build in this order. Stop and check with Max after each phase.

**Phase 0, baseline.** Run `python check_setup.py`, then one real
`./run.sh swipe` session on Max's Mac and confirm it still works against
live Tinder. Fix any selector drift first. Don't start the UI until this passes.

**Phase 1, platform abstraction.** Define a small `Platform` interface in
`src/platforms/base.py`, extracted from what `Tinder` already exposes:
`ensure_logged_in()`, `check_blocked()`, `dismiss_modals()`,
`read_current_profile() -> dict | None`, `swipe(like: bool)`, `idle()`,
`diagnose_no_card()`. Make `main.py` take a platform name. Tinder stays the only
implementation. Do **not** write Hinge/Bumble code yet; they work very
differently (Hinge likes a specific photo/prompt and has a daily like cap,
Bumble is women-message-first and has a swipe limit) and need their own
investigation with real captures.

**Phase 2, local control app.** A single-window app for Mac:
- Recommended: Flask or FastAPI backend + a simple page, shown in a native
  window with `pywebview`. Alternative: a menu-bar app (`rumps`). Keep the
  UI minimal.
- Screens: **Run** (Start/Stop, status, live feed of profiles with photo
  thumbnail, score, reason, liked/passed), **Settings** (age range,
  distance, height, `auto_like` threshold, MAX_LIKES, quiet hours; writes to
  the yaml files), **Schedule** (times of day, see below), **Setup** (API key,
  Telegram optional, Tinder login button that opens the Chromium window).
- The swipe session must run in a worker thread/process that the UI can
  stop cleanly. `main.py` currently runs as a script; refactor
  `run_session()` to accept callbacks (`on_profile`, `on_status`) and a
  stop event, with the CLI still working.
- Persist a run log (SQLite is fine): timestamp, name, age, score, stage,
  decision, reasons, hooks. This also enables a calibration view (score
  histogram, like rate), which Max needs to tune `auto_like`.
- Telegram becomes optional; the in-app feed is the primary view.

**Phase 3, scheduling.** In-app scheduler (APScheduler) with jittered times,
keeping the existing skip/quiet-hours logic. Document that the app must be
open; optionally install a `launchd` agent that launches it.

**Phase 4, packaging.** PyInstaller or Briefcase for a Mac `.app`. Playwright's
Chromium should download on first launch (not bundled). Unsigned is fine,
since it's personal use; document right-click > Open.

**Phase 5, Hinge, then Bumble.** One at a time, only after Tinder is stable
and the interface from phase 1 holds up. For each: capture real page text
and DOM first (use `match_probe.py` style probes), write parsers against real
captures, add tests, then wire in.

## 6. Hard-won Tinder lessons (read before touching tinder.py)

- Tinder web **removed `data-testid`**. Selectors are text/aria based in
  the `SEL` dict at the top of `src/platforms/tinder.py`; this is the first
  place to look when the bot stops finding cards. `debug_nocard.png/.txt`
  are written when the deck looks empty.
- Swiping is **keyboard driven**: Right = like, Left = pass, Up = open
  profile, Down = close profile, Space = next photo. Synthetic button
  clicks looked more bot-like.
- **Do not scroll** the profile view: scrolling closes it and the bio is lost.
  Parse the profile's flat rendered text instead.
- Profile text renders flat, with name and age concatenated (e.g.
  `Morgan27`). Parsers live at module level in tinder.py (`_parse_name_age`,
  `_parse_fields`, ...). Keep them module-level and unit-tested against real
  captures (a `_first_int` helper once got inserted inside the class and
  silently broke things).
- Tinder UI is **French**: "Ouvrir le profil", "NON", "LIKE", "Matchs",
  "Messages", "Vous:", "Alcool", "Sport", "Animal de compagnie", etc.
- A consent popup ("Non merci" for AI data sharing) and various upsells
  block the deck; `dismiss_modals()` handles them. Retry once after
  dismissing before concluding there is no card.
- `check_blocked()` is context-aware (`expect="recs"|"chat"|"any"`); the
  URL `/app/messages` is normal in chat context.
- `last_active_days` is not available on Tinder web, so the inactivity filter
  can't be applied.
- Pacing is non-uniform on purpose (mostly 1-4 s, 8% long 20-75 s tails, 12%
  sub-second). Uniform timing is the easiest tell. Don't "optimise" it away.
- The account was flagged once ("activité suspecte"); Max recovered via
  selfie verification. Treat the account as fragile: low volume, few sessions
  per day, headed browser, no retry loops after a challenge.
- `main.py` and `chat_loop.py` can't run at the same time (shared browser
  profile lock).

## 7. Conventions

- Keep modules small and plain. No framework beyond what's needed for the UI.
- Any new parser gets a unit test built from a real capture, not a guess.
- Never log or print API keys / tokens. Never commit `.env` or the session dir.
- Cost matters: stage 0/1 exist to avoid the ~5k-token vision call. Keep that
  funnel. Typical cost is cents per session.
- When a live-site change is needed, make it small, run it against the real
  site with Max, and report what you saw. Don't guess at selectors offline.
- Ask Max before: adding dependencies beyond the UI stack, changing
  scoring weights, or touching anything that increases swipe volume or
  speed.
