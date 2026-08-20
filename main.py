"""Unattended swipe session.

Scores and swipes automatically. Telegram digest at the end. Stops
immediately on any challenge screen — we never try to solve one.

Run this from cron 3-4x/day rather than continuously.
"""

import asyncio
import os
import random
from datetime import datetime
from judge import evaluate
from notifier import session_digest, alert
from platforms.tinder import Tinder

MAX_LIKES = int(os.environ.get("MAX_LIKES", "45"))
MAX_PROFILES = int(os.environ.get("MAX_PROFILES", "250"))

QUIET_HOURS = range(1, 8)   # no sessions 01:00-07:59 Paris


async def run_session():
    if datetime.now().hour in QUIET_HOURS:
        print("Quiet hours — skipping.")
        return

    # Not every scheduled run should actually fire.
    if random.random() < 0.15:
        print("Randomly skipping this session.")
        return

    # Vary the session size rather than always hitting the cap.
    like_cap = random.randint(int(MAX_LIKES * 0.45), MAX_LIKES)
    profile_cap = random.randint(int(MAX_PROFILES * 0.4), MAX_PROFILES)

    seen, likes, reviewed, vision_calls = set(), 0, 0, 0
    liked_log, stopped = [], None

    async with Tinder(headless=True) as t:
        await t.ensure_logged_in()

        while likes < like_cap and reviewed < profile_cap:
            blocked = await t.check_blocked()
            if blocked:
                stopped = blocked
                break

            profile = await t.read_current_profile()
            if not profile:
                stopped = "no card found"
                break
            if profile["id"] in seen:
                await t.swipe(like=False)
                continue
            seen.add(profile["id"])
            reviewed += 1

            v = evaluate(profile)
            if v["stage"] == 2:
                vision_calls += 1

            print(f"[{reviewed}] {profile['name']}, {profile['age']}: "
                  f"score={v['score']} like={v['like']} ({v['why']})")

            await t.swipe(like=v["like"])
            if v["like"]:
                likes += 1
                liked_log.append({
                    "name": profile["name"], "age": profile["age"],
                    "score": v["score"],
                    "hooks": (v.get("hooks", []) + v.get("photo_hooks", []))[:3],
                })

            # Break the rhythm every so often.
            if random.random() < 0.12:
                await t.idle()

    if stopped and stopped not in ("no card found", "out of likes"):
        alert(f"Session stopped: {stopped}")

    session_digest(reviewed=reviewed, likes=likes,
                   vision_calls=vision_calls, liked=liked_log, stopped=stopped)
    print(f"Done. {reviewed} reviewed, {likes} likes, "
          f"{vision_calls} vision calls. Stopped: {stopped}")


if __name__ == "__main__":
    asyncio.run(run_session())
