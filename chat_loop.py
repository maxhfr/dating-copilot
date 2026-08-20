"""Chat loop.

Polls matches, decides opener vs follow-up vs reply, drafts via chat.py,
sanitizes via style.py, and sends. Escalates to Telegram the moment a
plan is forming or anything looks off, and waits for your answer.

State lives in a small JSON file so restarts don't re-open conversations
or double-message anyone.
"""

import asyncio
import json
import os
import random
from datetime import datetime, timedelta
from pathlib import Path

from chat import draft_reply
from notifier import escalate, poll_updates, alert
from platforms.tinder import Tinder

STATE = Path.home() / ".dating-copilot" / "chat_state.json"
QUIET_HOURS = range(1, 8)

FOLLOWUP_AFTER_DAYS = 3
MAX_UNANSWERED = 2          # opener + one follow-up, then stop


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"matches": {}, "tg_offset": None}


def save_state(state: dict):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def _now() -> str:
    return datetime.now().isoformat()


def decide_kind(record: dict, history: list[dict]) -> str | None:
    """opener / followup / reply / None (do nothing)."""
    her_msgs = [m for m in history if m["role"] == "her"]
    my_msgs = [m for m in history if m["role"] == "me"]

    if her_msgs and history[-1]["role"] == "her":
        return "reply"

    if not my_msgs:
        return "opener"

    if her_msgs:
        return None                       # she replied, we already answered

    # She has never replied. How many unanswered have we sent?
    if len(my_msgs) >= MAX_UNANSWERED:
        return None                       # dormant, leave it alone

    last = datetime.fromisoformat(record.get("last_sent", _now()))
    if datetime.now() - last >= timedelta(days=FOLLOWUP_AFTER_DAYS):
        return "followup"
    return None


async def handle_match(t: Tinder, match_id: str, state: dict):
    record = state["matches"].setdefault(match_id, {})

    if record.get("status") in ("dormant", "handed_over", "dropped"):
        return

    match, history = await t.read_match(match_id)
    kind = decide_kind(record, history)
    if not kind:
        return

    draft = draft_reply(match, history, kind=kind)

    if draft["action"] == "escalate":
        escalate(match_name=match.get("name", match_id),
                 reason=draft.get("reason", ""),
                 proposed=draft.get("proposed", ""),
                 recent=history)
        record["status"] = "awaiting_you"
        record["pending_since"] = _now()
        save_state(state)
        return

    # Wait as though typing, then send.
    await asyncio.sleep(min(draft.get("delay_seconds", 20), 180))
    await t.send_message(match_id, draft["message"])

    record["last_sent"] = _now()
    record["status"] = "active"
    record["unanswered"] = record.get("unanswered", 0) + 1 if kind != "reply" else 0
    save_state(state)
    print(f"[{kind}] -> {match.get('name', match_id)}: {draft['message']}")


def drain_telegram(state: dict):
    """Apply any button taps you've made since the last pass."""
    offset = state.get("tg_offset")
    for u in poll_updates(offset):
        state["tg_offset"] = u["update_id"] + 1
        cb = u.get("callback_query")
        if not cb:
            continue
        action, name = cb["data"].split(":", 1)
        for mid, rec in state["matches"].items():
            if rec.get("name") == name or mid == name:
                rec["status"] = {"ok": "active",
                                 "me": "handed_over",
                                 "drop": "dropped"}.get(action, rec.get("status"))
    save_state(state)


async def run_loop(interval_minutes: int = 25):
    state = load_state()

    async with Tinder(headless=True) as t:
        await t.ensure_logged_in()

        while True:
            if datetime.now().hour in QUIET_HOURS:
                await asyncio.sleep(60 * 30)
                continue

            drain_telegram(state)

            blocked = await t.check_blocked()
            if blocked:
                alert(f"Chat loop stopped: {blocked}")
                break

            try:
                match_ids = await t.list_matches()
            except Exception as e:
                alert(f"Could not read matches: {e}")
                break

            for mid in match_ids:
                try:
                    await handle_match(t, mid, state)
                except Exception as e:
                    print(f"error on {mid}: {e}")
                await asyncio.sleep(random.uniform(3, 12))

            # Jittered poll interval — don't hit it on a clean schedule.
            wait = interval_minutes * 60 * random.uniform(0.6, 1.5)
            print(f"sleeping {wait/60:.0f}min")
            await asyncio.sleep(wait)


if __name__ == "__main__":
    asyncio.run(run_loop())
