"""Telegram loop-in.

Two jobs:
  1. Review queue — profiles that passed the rubric, for your visual yes/no
  2. Escalations — a plan is forming, or something needs your call

Both use inline buttons so you answer with one tap.
"""

import os
import requests

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
API = f"https://api.telegram.org/bot{TOKEN}"


def _buttons(rows):
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row]
                               for row in rows]}


def alert(text: str):
    """Something needs your attention right now."""
    requests.post(f"{API}/sendMessage",
                  json={"chat_id": CHAT_ID, "text": f"\u26a0\ufe0f {text}"}, timeout=20)


def session_digest(reviewed: int, likes: int, vision_calls: int,
                   liked: list[dict], stopped: str | None = None):
    """End-of-session summary. No approval needed — just so you can see
    what it did and retune the threshold if it's swiping badly."""
    lines = [f"*Session done*",
             f"{reviewed} profiles · {likes} likes · {vision_calls} vision calls",
             ""]
    for m in sorted(liked, key=lambda x: -x["score"])[:15]:
        hooks = ", ".join(m.get("hooks", [])[:2])
        lines.append(f"`{m['score']:>3}` {m['name']}, {m['age']} — _{hooks}_")
    if len(liked) > 15:
        lines.append(f"...and {len(liked) - 15} more")
    if stopped:
        lines.append(f"\nStopped early: _{stopped}_")

    requests.post(f"{API}/sendMessage", json={
        "chat_id": CHAT_ID,
        "text": "\n".join(lines),
        "parse_mode": "Markdown",
    }, timeout=20)


def escalate(match_name: str, reason: str, proposed: str, recent: list[dict]):
    """A plan is forming. Stop and ask."""
    tail = "\n".join(
        f"{'Her' if m['role'] == 'her' else 'You'}: {m['text']}" for m in recent[-3:]
    )
    text = (
        f"⏸ *{match_name}*\n\n"
        f"{reason}\n\n"
        f"On the table: _{proposed or '—'}_\n\n"
        f"```\n{tail}\n```"
    )
    requests.post(f"{API}/sendMessage", json={
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": _buttons([
            [("✅ Go ahead", f"ok:{match_name}"), ("✋ I'll handle it", f"me:{match_name}")],
            [("🚫 Drop it", f"drop:{match_name}")],
        ]),
    }, timeout=20)


def poll_updates(offset: int | None = None):
    """Long-poll for your button taps."""
    r = requests.get(f"{API}/getUpdates",
                     params={"offset": offset, "timeout": 30}, timeout=40)
    return r.json().get("result", [])
