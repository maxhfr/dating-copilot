"""App settings: the filters and threshold live in the existing yaml files
(edited in place so their comments survive); run limits and quiet hours live
in ~/.dating-copilot/settings.json.

Scoring WEIGHTS are deliberately not editable here, only the like threshold.
"""

import json
import re
import yaml
from pathlib import Path

import runlog

ROOT = Path(__file__).resolve().parent.parent
RUBRIC = ROOT / "config" / "rubric.yaml"
SCORING = ROOT / "config" / "scoring.yaml"

# Safety ceilings: the app will not raise swipe volume past these.
LIMITS = {"max_likes": (1, 100), "max_profiles": (10, 500)}

DEFAULTS = {"max_likes": 45, "max_profiles": 250,
            "quiet_start": 1, "quiet_end": 8}


def _set_scalar(text: str, path: tuple, value) -> str:
    """Replace one scalar in yaml text without touching comments."""
    lines = text.splitlines(keepends=True)
    idx, indent = 0, -1
    for depth, key in enumerate(path):
        pat = re.compile(rf"^(\s*){re.escape(key)}:(.*)$")
        found = None
        for i in range(idx, len(lines)):
            m = pat.match(lines[i].rstrip("\n"))
            if m and len(m.group(1)) > indent:
                found = i
                indent = len(m.group(1))
                break
            if depth and lines[i].strip() and not lines[i].startswith(" "):
                break          # left the parent block
        if found is None:
            raise KeyError("/".join(path))
        idx = found + (0 if depth == len(path) - 1 else 1)
    line = lines[idx]
    m = re.match(r"^(\s*[^:]+:\s*)([^#\s]+)(.*)$", line.rstrip("\n"))
    if not m:
        raise ValueError(f"cannot edit line: {line!r}")
    lines[idx] = f"{m.group(1)}{value}{m.group(3)}\n"
    return "".join(lines)


def read() -> dict:
    rubric = yaml.safe_load(RUBRIC.read_text())
    scoring = yaml.safe_load(SCORING.read_text())
    app = dict(DEFAULTS)
    f = runlog.home() / "settings.json"
    if f.exists():
        try:
            app.update(json.loads(f.read_text()))
        except Exception:
            pass
    return {
        "age_min": rubric["age"]["min"], "age_max": rubric["age"]["max"],
        "distance_km_max": rubric["distance_km_max"],
        "height_max_cm": rubric["height"]["max_cm_if_stated"],
        "auto_like": scoring["thresholds"]["auto_like"],
        **app,
    }


def _int(d, key, lo, hi):
    try:
        v = int(d[key])
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"{key} must be a whole number")
    if not lo <= v <= hi:
        raise ValueError(f"{key} must be between {lo} and {hi}")
    return v


def write(new: dict) -> dict:
    """Validate then save. Raises ValueError with a readable message."""
    cur = read()
    merged = {**cur, **{k: v for k, v in new.items() if k in cur}}
    v = {
        "age_min": _int(merged, "age_min", 18, 99),
        "age_max": _int(merged, "age_max", 18, 99),
        "distance_km_max": _int(merged, "distance_km_max", 1, 500),
        "height_max_cm": _int(merged, "height_max_cm", 120, 230),
        "auto_like": _int(merged, "auto_like", 0, 100),
        "max_likes": _int(merged, "max_likes", *LIMITS["max_likes"]),
        "max_profiles": _int(merged, "max_profiles", *LIMITS["max_profiles"]),
        "quiet_start": _int(merged, "quiet_start", 0, 23),
        "quiet_end": _int(merged, "quiet_end", 0, 24),
    }
    if v["age_min"] >= v["age_max"]:
        raise ValueError("age_min must be lower than age_max")

    rub = RUBRIC.read_text()
    rub = _set_scalar(rub, ("age", "min"), v["age_min"])
    rub = _set_scalar(rub, ("age", "max"), v["age_max"])
    rub = _set_scalar(rub, ("distance_km_max",), v["distance_km_max"])
    rub = _set_scalar(rub, ("height", "max_cm_if_stated"), v["height_max_cm"])
    sc = _set_scalar(SCORING.read_text(), ("thresholds", "auto_like"), v["auto_like"])
    yaml.safe_load(rub), yaml.safe_load(sc)       # still valid yaml?
    RUBRIC.write_text(rub)
    SCORING.write_text(sc)

    home = runlog.home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "settings.json").write_text(json.dumps(
        {k: v[k] for k in DEFAULTS}, indent=2))
    return read()


def run_kwargs() -> dict:
    s = read()
    start, end = s["quiet_start"], s["quiet_end"]
    hours = (range(start, end) if start <= end
             else list(range(start, 24)) + list(range(0, end)))
    return {"max_likes": s["max_likes"], "max_profiles": s["max_profiles"],
            "quiet_hours": hours}
