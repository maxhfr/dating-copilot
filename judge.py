"""Two-stage profile evaluation.

Stage 1 (text only, ~300 tokens): hard filters from rubric.yaml. Most
profiles die here and cost almost nothing — no images attached.

Stage 2 (vision, ~5k tokens): scores survivors 0-100 using scoring.yaml.
Only runs on profiles that already cleared stage 1.

Both use Haiku 4.5. Rubric and weights are cached so they aren't re-billed
on every call.
"""

import json
import os
import yaml
from anthropic import Anthropic

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
MODEL = "claude-haiku-4-5-20251001"

with open("config/rubric.yaml") as f:
    RUBRIC = yaml.safe_load(f)
with open("config/scoring.yaml") as f:
    WEIGHTS = yaml.safe_load(f)

AUTO_LIKE = WEIGHTS["thresholds"]["auto_like"]

NO_ETHNICITY = (
    "Do NOT infer, evaluate, comment on, or reference ethnicity, race, "
    "skin colour, or national origin at any point. These are not criteria "
    "and must not appear in your reasoning or output. When identifying "
    "hair or eye colour, report only what is directly visible as a "
    "grooming/appearance detail — never as an indicator of background."
)

STAGE1_SYSTEM = f"""You apply hard filters to dating profile text. No images.

FILTERS:
{yaml.dump(RUBRIC, allow_unicode=True)}

Rules:
- Age / distance / height: numeric, from stated values only. Never guess.
  Height applies only when explicitly written on the profile.
- Language: assume French unless there's positive evidence she speaks
  neither French nor English.
- Smoking: reject ONLY on explicit anti-smoking statements.
- Drinking: reject ONLY if she states she doesn't drink.
- Profile quality: reject if under 2 photos, or no bio AND no prompts.
- Silence is always a pass. Absence of information is never a rejection.

{NO_ETHNICITY}

Also score the TEXT categories from scoring.yaml:

- bio_effort: how much real personality is in the written profile
- shared_interests: overlap with HIS interests — cooking (especially
  Vietnamese/Korean/Thai), music (wide range, drum & bass, French rap),
  climbing and the gym, animals and cats, film, wine, football, wanting
  a house outside Paris eventually. "strong" needs two or more genuine
  overlaps, not one vague match.
- intent_fit: he wants something serious. Most profiles say nothing —
  that's "open_unstated" and must NOT be punished.

{NO_ETHNICITY}

Return ONLY JSON, no fence:
{{"verdict":"pass"|"reject","failed":["..."],
  "bio_effort":"substantial"|"moderate"|"minimal"|"empty",
  "shared_interests":"strong"|"some"|"slight"|"none",
  "intent_fit":"clearly_serious"|"open_unstated"|"ambiguous"|"clearly_casual",
  "hooks":["specific concrete details worth opening about"]}}
"""

STAGE2_SYSTEM = f"""You score dating profile photos against fixed weights.

WEIGHTS:
{yaml.dump(WEIGHTS, allow_unicode=True)}

For each category, pick the single best-matching label from its scores
map. Be conservative — when a category is genuinely unclear, choose the
neutral/middle label rather than guessing. Bad lighting is not brown eyes.

If body_type is "obese", return it honestly; the caller handles the
rejection.

{NO_ETHNICITY}

Also extract PHOTO HOOKS: concrete, specific, non-obvious things visible
in the photos that could be opened about. A climbing wall, a dog, a
recognisable place, an instrument, a kitchen, a weird t-shirt, a book
spine. NOT "she's pretty", NOT "she's at the beach", NOT anything about
her body or appearance. If nothing specific is visible, return an empty
list — a bad hook is worse than none.

Return ONLY JSON, no fence:
{{"body_type":"...","hair":"...","eyes":"...","photo_style":"...",
  "photo_variety":"...","filters":"...",
  "photo_hooks":["..."],
  "note":"one short line"}}
"""


def _call(system, content, max_tokens=500):
    resp = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": content}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)


def stage1_filter(profile: dict) -> dict:
    """Text only. Cheap. Runs on everything."""
    payload = {k: v for k, v in profile.items() if k != "photos"}
    try:
        return _call(STAGE1_SYSTEM,
                     [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
                     max_tokens=400)
    except (json.JSONDecodeError, KeyError):
        return {"verdict": "reject", "failed": ["parse_error"]}


def stage2_score(profile: dict, text_labels: dict) -> dict:
    """Vision. Only on stage-1 survivors."""
    content = []
    for photo_b64 in profile.get("photos", [])[:5]:
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": "image/jpeg", "data": photo_b64}})
    content.append({"type": "text", "text": "Score these photos."})

    try:
        labels = _call(STAGE2_SYSTEM, content, max_tokens=400)
    except (json.JSONDecodeError, KeyError):
        return {"score": 0, "labels": {}, "reject": True, "why": "parse_error"}

    if labels.get("body_type") == "obese":
        return {"score": 0, "labels": labels, "reject": True, "why": "body_type"}

    score = 0
    breakdown = {}
    for cat in ["body_type", "hair", "eyes", "photo_style", "photo_variety", "filters"]:
        label = labels.get(cat)
        pts = WEIGHTS[cat]["scores"].get(label, 0)
        breakdown[cat] = (label, pts)
        score += pts

    for cat in ["bio_effort", "shared_interests", "intent_fit"]:
        label = text_labels.get(cat)
        pts = WEIGHTS[cat]["scores"].get(label, 0)
        breakdown[cat] = (label, pts)
        score += pts

    return {"score": score, "labels": labels, "breakdown": breakdown,
            "reject": False, "note": labels.get("note", ""),
            "photo_hooks": labels.get("photo_hooks", [])}


def evaluate(profile: dict) -> dict:
    """Full pipeline. Returns {'like': bool, 'score': int, 'why': str}."""
    s1 = stage1_filter(profile)
    if s1["verdict"] == "reject":
        return {"like": False, "score": None, "stage": 1,
                "why": ",".join(s1.get("failed", [])), "hooks": []}

    s2 = stage2_score(profile, s1)
    if s2["reject"]:
        return {"like": False, "score": 0, "stage": 2,
                "why": s2.get("why", ""), "hooks": s1.get("hooks", [])}

    return {"like": s2["score"] >= AUTO_LIKE,
            "score": s2["score"],
            "stage": 2,
            "breakdown": s2.get("breakdown", {}),
            "why": s2.get("note", ""),
            "hooks": s1.get("hooks", []),
            "photo_hooks": s2.get("photo_hooks", [])}
