"""Quality gate for outgoing messages.

The drafting model produces a dud every so often — broken grammar, two
ideas welded together, something that reads translated. A human would
catch it instantly. This is that human.

A separate cheap call reviews the draft COLD: no persona, no rules about
what Max is like, just "would a French speaker actually text this?"
Reviewing without the context that produced the draft is the point — it
can't rationalise its own reasoning.

Costs about $0.001 per message. Worth it to keep the loop unattended.
"""

import json
import os
from anthropic import Anthropic

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
MODEL = "claude-haiku-4-5-20251001"
DEBUG = os.environ.get("JUDGE_DEBUG") == "1"

REVIEW_SYSTEM = """You are proofreading a single message before it is sent
on a dating app. You did not write it and know nothing about the sender.

Judge ONLY these, in order:

1. GRAMMAR — does it parse? Is it correct, natural French (or English if
   written in English)? Broken syntax, missing verbs, words that don't
   belong, dangling clauses, prepositions that don't fit: FAIL. This is
   the most common failure and the most important one to catch. Read the
   sentence literally, word by word, and ask whether each part actually
   connects to the next. Do not smooth over errors mentally.

   Example of a FAIL: "à négocier un cours et avec la coach" — the "et"
   and "avec" cannot both attach there. Meaning is guessable; grammar is
   broken; FAIL.
2. SENSE — can you tell what it means on one read? If you have to reread
   it to work out the intent: FAIL.
3. ONE QUESTION — openers only. FAIL only if the message asks her TWO
   SEPARATE THINGS that need two separate answers.

   This is about questions, not nouns. Mentioning several things from her
   profile to set up a single question is GOOD writing, not a violation.
   An either/or ("plutôt X ou Y ?") is ONE question, not two.

   PASSES — one question, however much setup:
     "Cuisine et sushi tous les deux dans tes passions, du coup t'es
      plutôt du genre à rouler tes propres makis ou c'est juste pour les
      manger direct ?"          <- one question: makes them or eats them
     "Paddle et canoë dans la même liste, faut choisir un camp."
                                <- one idea, two nouns as setup

   FAILS — genuinely two questions:
     "T'es plutôt sushi ou pizza ? Et sinon tu fais quoi comme sport ?"
                                <- two unrelated things to answer

   Does NOT apply to replies mid-conversation.
4. NATURAL — would a real person type this to someone they matched with?
   Anything stilted, over-constructed, or translated-sounding: FAIL.
5. LENGTH — over 160 characters: FAIL. Under that, do not comment on
   length at all; a 150-character message that reads well is fine.

Do NOT judge whether it is funny, charming or a good strategy. Not your
job. Only whether it is well-formed and sendable.

Be strict on grammar and lenient on style. Texting register is CORRECT,
not an error: dropped "ne" ("je pense pas"), no final full stop,
lowercase openings, contractions, familiar spoken forms like "J'ai bon ?",
"du coup", "genre", "t'es". Never flag these.

A single sentence with a subordinate clause is one idea, not two.
Naming two of her interests to build one question is one idea.
Only flag when she would genuinely have to answer two separate things.

SCOPE OF LENIENCY — read carefully, this matters:

The "when unsure, pass" instruction applies ONLY to rule 3 (ONE QUESTION)
and rule 4 (NATURAL). Style is subjective and over-rejecting wastes
matches.

It does NOT apply to rule 1 (GRAMMAR) or rule 2 (SENSE). Those stay
strict. A message with broken syntax, a missing verb, a dangling clause,
or words in an order French does not use is a FAIL every time, no matter
how good the idea behind it is. Grammar is the single most important
thing you check — a malformed message is embarrassing in a way a
slightly-awkward one is not.

If you find yourself thinking "the meaning is clear enough despite the
grammar", that is a FAIL.

Return ONLY JSON, nothing else:
{"ok": true|false, "problem": "short reason if not ok"}"""


def review(message: str, kind: str = "opener") -> tuple[bool, str]:
    """Returns (ok, reason). kind is "opener", "followup" or "reply" —
    the one-question rule only applies to openers."""
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=200,
            system=[{"type": "text", "text": REVIEW_SYSTEM,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content":
                       f"This is a {kind}.\n\nMessage:\n{message}"}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        text = text.replace("```json", "").replace("```", "").strip()
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start:end + 1]
        out = json.loads(text)
        ok = bool(out.get("ok"))
        if DEBUG and not ok:
            print(f"  -- gate rejected: {out.get('problem')}")
        return ok, out.get("problem", "")
    except Exception as e:
        # Never block a send because the reviewer itself failed.
        if DEBUG:
            print(f"  -- gate error (allowing through): {e}")
        return True, ""


def draft_with_retry(draft_fn, *args, attempts: int = 3, **kwargs) -> dict:
    """Draft, review, redraft. Escalates rather than sending a dud.

    draft_fn is chat.draft_reply. Anything it escalates is retried too —
    chat.py's own rejections (generic opener, too long, AI tells) are
    worth another attempt before bothering Max.
    """
    tried = []
    out = {}
    for i in range(attempts):
        out = draft_fn(*args, **kwargs)

        if out.get("action") != "send":
            # chat.py already rejected it. Retry unless we're out of goes.
            if out.get("proposed"):
                tried.append((out.get("reason", ""), out["proposed"]))
                if i < attempts - 1:
                    print(f"  (redrafting, attempt {i + 1} rejected: "
                          f"{out.get('reason')})")
                    continue
            return out

        ok, problem = review(out["message"], kind=kwargs.get("kind", "opener"))
        if ok:
            if i and DEBUG:
                print(f"  -- accepted on attempt {i + 1}")
            return out

        tried.append((problem, out["message"]))
        print(f"  (redrafting, attempt {i + 1} rejected: {problem})")

    reason, best = tried[-1] if tried else ("no drafts produced", "")
    return {"action": "escalate",
            "reason": f"{attempts} drafts failed review. Last: {reason}",
            "proposed": best}
