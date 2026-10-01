"""Draft replies to matches, in Max's voice.

Uses Sonnet 5 — this is the part standing in for him, so quality matters
more than cost here. Volume is low compared to swiping.

The model can emit an escalation instead of a message. Anything that looks
like a plan being formed stops the loop and goes to Telegram.
"""

import json
import os
from anthropic import Anthropic
from style import sanitize, has_tells, typing_delay

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

MODEL = "claude-sonnet-5"
DEBUG = os.environ.get("JUDGE_DEBUG") == "1"

with open("config/persona.md") as f:
    PERSONA = f.read()
with open("config/date_rules.md") as f:
    DATE_RULES = f.read()
with open("config/openers.md") as f:
    OPENERS = f.read()

SYSTEM = f"""{PERSONA}

---

{OPENERS}

---

{DATE_RULES}

---

OUTPUT FORMAT — strict. Reply with a single JSON object and NOTHING
else. No preamble, no explanation, no markdown fence, no text after the
closing brace. Your entire reply must start with {{ and end with }}.

{{"action": "send" | "escalate",
  "message": "the message text, if action is send",
  "reason": "why you're escalating, if action is escalate",
  "proposed": "the plan on the table, if any"}}

Escalate — do not send — when ANY of these is true:
- A specific day, time, or venue is being agreed
- She proposes anything beyond a drink in Paris
- She asks something you cannot answer truthfully from the persona file
- The conversation turns personal in a register the persona file rules out
- Anything feels off: aggression, a scam pattern, an obvious bot,
  a request for money, or a request to move to another platform early
- You are writing an opener and there is NO usable hook from her bio or
  photos. Do not fall back on a generic message — escalate instead.

When in doubt, escalate. A delayed reply costs nothing. A wrong one does.
"""


def draft_reply(match: dict, history: list[dict], kind: str = "reply") -> dict:
    """match: {name, age, bio, hooks, photo_hooks}
    history: [{"role": "her"|"me", "text": "..."}]
    kind: "opener" | "followup" | "reply" """

    convo = "\n".join(
        f"{'Her' if m['role'] == 'her' else 'Max'}: {m['text']}" for m in history
    )

    task = {
        "opener": ("You are writing the OPENER. She has not seen a message "
                   "from Max yet. Follow the opener rules exactly. If there "
                   "is no usable hook, escalate instead of sending."),
        "followup": ("She did not reply to the opener. Write ONE short "
                     "follow-up on a DIFFERENT angle. Light, no pressure, "
                     "no reference to being ignored. One line."),
        "reply": "Write Max's next message in the conversation.",
    }[kind]

    prompt = f"""Match profile:
{json.dumps(match, ensure_ascii=False, indent=2)}

Conversation so far ({len(history)} messages):
{convo if convo else "(no messages yet)"}

{task}"""

    resp = client.messages.create(
        model=MODEL,
        max_tokens=800,
        system=[
            {"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}
        ],
        messages=[{"role": "user", "content": prompt}],
    )

    text = "".join(b.text for b in resp.content if b.type == "text")
    if DEBUG:
        print(f"  -- raw draft output: {text[:400]}")
    text = text.replace("```json", "").replace("```", "").strip()

    try:
        out = json.loads(text)
    except json.JSONDecodeError:
        # The model sometimes wraps the object in prose. Take the
        # outermost {...} and retry before giving up.
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                out = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return {"action": "escalate",
                        "reason": "could not parse model output",
                        "proposed": text[:300]}
        else:
            return {"action": "escalate",
                    "reason": "model returned no JSON object",
                    "proposed": text[:300]}

    # Never let a generic opener through, whatever the model thinks
    if out.get("action") == "send" and kind == "opener":
        msg = out.get("message", "").strip().lower()
        banned_starts = ["hey", "salut", "coucou", "hello", "hi ", "bonjour",
                         "ça va", "ca va", "how are you", "how's it going"]
        if any(msg.startswith(b) for b in banned_starts) or len(msg) < 15:
            return {"action": "escalate",
                    "reason": "opener was generic — needs a real hook",
                    "proposed": out.get("message")}
        # Long openers read as written rather than texted. 160 is the
        # ceiling; between 120 and 160 is allowed but not encouraged.
        if len(out.get("message", "")) > 160:
            return {"action": "escalate",
                    "reason": f"opener too long ({len(out['message'])} chars, max 160)",
                    "proposed": out.get("message")}

    # Belt and braces: never send a message containing a hard commitment
    if out.get("action") == "send":
        msg = out.get("message", "").lower()
        commit_markers = [
            "à demain", "see you", "on se dit", "c'est noté", "je réserve",
            "i'll book", "deal", "parfait, à", "rendez-vous à",
        ]
        if any(m in msg for m in commit_markers):
            return {
                "action": "escalate",
                "reason": "draft contained a commitment phrase",
                "proposed": out.get("message"),
            }

    # Strip AI writing tells, then re-check what the sanitizer can't fix
    if out.get("action") == "send":
        lang = "en" if kind != "opener" and _looks_english(history) else "fr"
        cleaned = sanitize(out["message"], lang=lang)
        problems = has_tells(cleaned)
        if problems:
            return {"action": "escalate",
                    "reason": "draft read as AI-written: " + "; ".join(problems),
                    "proposed": cleaned}
        out["message"] = cleaned
        out["delay_seconds"] = typing_delay(cleaned)

    return out


def _looks_english(history: list[dict]) -> bool:
    her = " ".join(m["text"] for m in history if m["role"] == "her").lower()
    if not her:
        return False
    fr_markers = [" je ", " tu ", " et ", " est ", " pas ", " oui", " merci",
                  " ça", " c'est", " bien"]
    return not any(m in f" {her} " for m in fr_markers)
