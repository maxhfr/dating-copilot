"""Unattended swipe session.

Scores and swipes automatically. Telegram digest at the end. Stops
immediately on any challenge screen — we never try to solve one.

Run this from cron 3-4x/day rather than continuously.

`run_session` can also be driven from the app: it takes callbacks
(on_profile, on_status) and a stop event, and every profile is logged to
the SQLite run log either way.
"""

import asyncio
import os
import random
import sys
from datetime import datetime

import judge
import runlog
from notifier import session_digest, alert
from platforms import get_platform

# Defaults, read from the environment at import. run_session() accepts
# overrides so the app can pass its own settings per run.
MAX_LIKES = int(os.environ.get("MAX_LIKES", "45"))
MAX_PROFILES = int(os.environ.get("MAX_PROFILES", "250"))

# Send an interim digest every N profiles reviewed. 0 disables it and you
# only get the end-of-session summary. Useful while calibrating the score
# threshold — you see what it's doing without waiting for the full run.
DIGEST_EVERY = int(os.environ.get("DIGEST_EVERY", "30"))

# Keep the browser open for 45s when the deck stops unexpectedly, so you
# can actually see what was on screen. Set HOLD_ON_STOP=0 once scheduled.
HOLD_ON_STOP = os.environ.get("HOLD_ON_STOP", "1") == "1"

QUIET_HOURS = range(1, 8)   # no sessions 01:00-07:59 Paris

# Stop reasons that are normal endings, not worth a Telegram alert.
QUIET_STOPS = ("no card found", "out of likes", "stopped by you")


async def run_session(platform: str = "tinder", on_profile=None, on_status=None,
                      stop_event=None, manual: bool = False,
                      max_likes: int | None = None,
                      max_profiles: int | None = None,
                      quiet_hours=None) -> dict:
    """Run one swipe session and return a summary dict.

    on_profile(dict)  called after each profile is decided
    on_status(str)    called with each progress / status line
    stop_event        a threading.Event; set it to end the session cleanly
    manual            True when a person pressed Start: skips the random
                      "skip this run" roll, but quiet hours still apply
    """
    def say(msg: str):
        print(msg)
        if on_status:
            on_status(msg)

    max_likes = MAX_LIKES if max_likes is None else max_likes
    max_profiles = MAX_PROFILES if max_profiles is None else max_profiles
    quiet = QUIET_HOURS if quiet_hours is None else quiet_hours
    summary = {"reviewed": 0, "likes": 0, "vision_calls": 0, "stopped": None}

    if datetime.now().hour in quiet:
        say("Quiet hours — skipping.")
        summary["stopped"] = "quiet hours"
        return summary

    # Not every scheduled run should actually fire.
    if not manual and random.random() < 0.15:
        say("Randomly skipping this session.")
        summary["stopped"] = "randomly skipped"
        return summary

    # Vary the session size rather than always hitting the cap.
    like_cap = random.randint(int(max_likes * 0.45), max_likes)
    profile_cap = random.randint(int(max_profiles * 0.4), max_profiles)

    seen, likes, reviewed, vision_calls = set(), 0, 0, 0
    unreadable_in_a_row = 0
    liked_log, stopped = [], None
    last_reported = 0
    session_id = runlog.start_session(platform)

    try:
        async with get_platform(platform)(headless=False) as t:
            await t.ensure_logged_in()

            while likes < like_cap and reviewed < profile_cap:
                if stop_event is not None and stop_event.is_set():
                    stopped = "stopped by you"
                    break

                blocked = await t.check_blocked()
                if blocked:
                    stopped = blocked
                    break

                profile = await t.read_current_profile()
                if not profile:
                    # Retry — the deck lags behind a swipe, and popups
                    # (upsells, match promos) block it entirely.
                    await t.dismiss_modals()
                    await asyncio.sleep(random.uniform(3, 6))
                    profile = await t.read_current_profile()
                if not profile:
                    # Find out why before swiping blind: a popup or the like
                    # limit is not an unreadable card.
                    reason = await t.diagnose_no_card()
                    unreadable_in_a_row += 1
                    if unreadable_in_a_row <= 3:
                        if reason.startswith("popup was blocking"):
                            say("  (dismissed a popup, retrying)")
                            continue
                        if reason.startswith("no card found"):
                            # One odd card shouldn't end the session: pass
                            # it, but give up if several in a row fail.
                            say(f"  (passed unreadable card, "
                                f"{unreadable_in_a_row} in a row)")
                            await t.swipe(like=False)
                            continue
                    stopped = reason
                    if HOLD_ON_STOP:
                        say(f"\n  !! {stopped}")
                        say("  !! Browser stays open 45s so you can look.\n")
                        await asyncio.sleep(45)
                    break
                unreadable_in_a_row = 0

                if profile["id"] in seen:
                    await t.swipe(like=False)
                    continue
                seen.add(profile["id"])
                reviewed += 1

                v = judge.evaluate(profile)
                if v["stage"] == 2:
                    vision_calls += 1

                say(f"[{reviewed}] {profile['name']}, {profile['age']}: "
                    f"score={v['score']} like={v['like']} ({v['why']})")
                runlog.log_profile(session_id, platform, profile, v)
                if on_profile:
                    on_profile({
                        "n": reviewed, "name": profile["name"],
                        "age": profile["age"],
                        "distance_km": profile.get("distance_km"),
                        "score": v["score"], "stage": v["stage"],
                        "like": v["like"], "why": v["why"],
                        "hooks": (v.get("hooks", []) + v.get("photo_hooks", []))[:3],
                    })

                await t.swipe(like=v["like"])
                if v["like"]:
                    likes += 1
                    liked_log.append({
                        "name": profile["name"], "age": profile["age"],
                        "score": v["score"],
                        "hooks": (v.get("hooks", []) + v.get("photo_hooks", []))[:3],
                    })

                # Interim digest so you're not waiting for the whole run.
                if DIGEST_EVERY and reviewed % DIGEST_EVERY == 0:
                    session_digest(reviewed=reviewed, likes=likes,
                                   vision_calls=vision_calls,
                                   liked=liked_log[last_reported:],
                                   partial=True)
                    last_reported = len(liked_log)

                # Break the rhythm every so often.
                if random.random() < 0.12:
                    await t.idle()
    except asyncio.CancelledError:
        # The app cancelled the task to stop the session. The browser is
        # closed by the context manager; fall through to the summary.
        stopped = "stopped by you"
    except KeyboardInterrupt:
        stopped = "interrupted by you"
    except Exception as e:
        stopped = f"{type(e).__name__}: {e}"

    if stopped and not stopped.startswith(QUIET_STOPS):
        alert(f"Session stopped: {stopped}")

    session_digest(reviewed=reviewed, likes=likes,
                   vision_calls=vision_calls, liked=liked_log, stopped=stopped)
    runlog.end_session(session_id, reviewed, likes, vision_calls, stopped)
    say(f"Done. {reviewed} reviewed, {likes} likes, "
        f"{vision_calls} vision calls. Stopped: {stopped}")
    summary.update(reviewed=reviewed, likes=likes,
                   vision_calls=vision_calls, stopped=stopped)
    return summary


if __name__ == "__main__":
    asyncio.run(run_session(sys.argv[1] if len(sys.argv) > 1 else "tinder"))
