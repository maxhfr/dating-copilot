"""Telegram loop-in.

Two jobs:
  1. Session digests — what the swipe run did
  2. Escalations — a plan is forming, or something needs your call

Every send checks the response. Silent Telegram failures are worse than
useless: you think it's working when it isn't.
"""

import os
import requests

# Telegram is optional: without both values every send is a silent no-op.
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
API = f"https://api.telegram.org/bot{TOKEN}"


def _md(text: str) -> str:
    """Escape Telegram Markdown specials. A single stray _ in a name
    makes Telegram reject the entire message."""
    for ch in ("_", "*", "`", "["):
        text = text.replace(ch, "\\" + ch)
    return text


def _post(method: str, payload: dict):
    """Send, and say so loudly if Telegram refuses."""
    if not TOKEN or not CHAT_ID:
        return {"ok": False}
    try:
        r = requests.post(f"{API}/{method}", json=payload, timeout=20)
        data = r.json()
        if not data.get("ok"):
            print(f"[telegram] {method} FAILED: {data.get('description')}")
        return data
    except Exception as e:
        print(f"[telegram] {method} ERROR: {e}")
        return {"ok": False}


def _buttons(rows):
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row]
                               for row in rows]}


def alert(text: str):
    """Something needs your attention right now."""
    _post("sendMessage", {"chat_id": CHAT_ID, "text": f"⚠️ {text}"})


def session_digest(reviewed: int, likes: int, vision_calls: int,
                   liked: list[dict], stopped: str | None = None,
                   partial: bool = False):
    """Progress or end-of-session summary. No approval needed — it's so you
    can see what it's doing and retune the threshold if it's swiping badly.

    partial=True means the session is still running and `liked` holds only
    the likes since the last digest.
    """
    header = f"Still going - {reviewed} so far" if partial else "Session done"
    lines = [header,
             f"{reviewed} profiles · {likes} likes · {vision_calls} vision calls",
             ""]
    if partial and not liked:
        lines.append("(no new likes since last update)")

    for m in sorted(liked, key=lambda x: -(x["score"] or 0))[:15]:
        hooks = ", ".join(m.get("hooks", [])[:2])
        lines.append(f"{m['score']:>3}  {_md(str(m['name']))}, {m['age']}"
                     + (f" - {_md(hooks)}" if hooks else ""))
    if len(liked) > 15:
        lines.append(f"...and {len(liked) - 15} more")
    if stopped:
        lines.append(f"\nStopped early: {stopped}")

    _post("sendMessage", {"chat_id": CHAT_ID, "text": "\n".join(lines)})


def escalate(match_name: str, reason: str, proposed: str, recent: list[dict]):
    """A plan is forming. Stop and ask."""
    tail = "\n".join(
        f"{'Her' if m['role'] == 'her' else 'You'}: {m['text']}" for m in recent[-3:]
    )
    text = (
        f"⏸ {match_name}\n\n"
        f"{reason}\n\n"
        f"On the table: {proposed or '-'}\n\n"
        f"{tail}"
    )
    _post("sendMessage", {
        "chat_id": CHAT_ID,
        "text": text,
        "reply_markup": _buttons([
            [("✅ Go ahead", f"ok:{match_name}"), ("✋ I'll handle it", f"me:{match_name}")],
            [("🚫 Drop it", f"drop:{match_name}")],
        ]),
    })


def poll_updates(offset: int | None = None):
    """Long-poll for your button taps."""
    try:
        r = requests.get(f"{API}/getUpdates",
                         params={"offset": offset, "timeout": 30}, timeout=40)
        return r.json().get("result", [])
    except Exception as e:
        print(f"[telegram] getUpdates ERROR: {e}")
        return []
