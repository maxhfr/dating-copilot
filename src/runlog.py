"""SQLite run log: one row per session and per profile reviewed.

Feeds the live view and the calibration view (score histogram, like rate).
Stores names, ages, scores and the model's reasons. It does NOT store photos
or bios. Logging problems never interrupt a swipe session.
"""

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY, started_at REAL, ended_at REAL, platform TEXT,
    reviewed INTEGER DEFAULT 0, likes INTEGER DEFAULT 0,
    vision_calls INTEGER DEFAULT 0, stopped TEXT);
CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY, session_id INTEGER, ts REAL, platform TEXT,
    name TEXT, age INTEGER, distance_km INTEGER, score INTEGER, stage INTEGER,
    decision TEXT, why TEXT, hooks TEXT, breakdown TEXT);
"""


def home() -> Path:
    return Path(os.environ.get("DATING_COPILOT_HOME",
                               Path.home() / ".dating-copilot"))


def log_line(text: str):
    """Append a timestamped line to ~/.dating-copilot/app.log (best effort,
    rotated at 1 MB). Never put secrets in `text`."""
    try:
        home().mkdir(parents=True, exist_ok=True)
        f = home() / "app.log"
        if f.exists() and f.stat().st_size > 1_000_000:
            f.replace(home() / "app.log.1")
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text.rstrip() + "\n")
    except Exception:
        pass


def _connect() -> sqlite3.Connection:
    home().mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(home() / "runlog.db")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


@contextmanager
def _db():
    """Connection that commits on success and is always closed."""
    con = _connect()
    try:
        with con:
            yield con
    finally:
        con.close()


def _safe(default):
    def deco(fn):
        def wrapper(*a, **kw):
            try:
                return fn(*a, **kw)
            except Exception as e:  # logging must never break a session
                print(f"[runlog] {fn.__name__} failed: {type(e).__name__}: {e}")
                return default
        wrapper.__name__ = fn.__name__
        return wrapper
    return deco


@_safe(None)
def start_session(platform: str):
    with _db() as con:
        cur = con.execute("INSERT INTO sessions (started_at, platform) VALUES (?, ?)",
                          (time.time(), platform))
        return cur.lastrowid


@_safe(None)
def end_session(session_id, reviewed, likes, vision_calls, stopped):
    if session_id is None:
        return
    with _db() as con:
        con.execute("UPDATE sessions SET ended_at=?, reviewed=?, likes=?, "
                    "vision_calls=?, stopped=? WHERE id=?",
                    (time.time(), reviewed, likes, vision_calls, stopped, session_id))


@_safe(None)
def log_profile(session_id, platform, profile: dict, verdict: dict):
    with _db() as con:
        con.execute(
            "INSERT INTO profiles (session_id, ts, platform, name, age, distance_km, "
            "score, stage, decision, why, hooks, breakdown) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (session_id, time.time(), platform, profile.get("name"), profile.get("age"),
             profile.get("distance_km"), verdict.get("score"), verdict.get("stage"),
             "like" if verdict.get("like") else "pass", verdict.get("why", ""),
             json.dumps((verdict.get("hooks", []) + verdict.get("photo_hooks", []))[:3],
                        ensure_ascii=False),
             json.dumps({k: list(v) for k, v in verdict.get("breakdown", {}).items()},
                        ensure_ascii=False)))


@_safe([])
def recent(limit: int = 50) -> list[dict]:
    with _db() as con:
        rows = con.execute("SELECT * FROM profiles ORDER BY id DESC LIMIT ?",
                           (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["hooks"] = json.loads(d["hooks"] or "[]")
        d.pop("breakdown", None)
        out.append(d)
    return out


@_safe({"total": 0, "likes": 0, "like_rate": None, "histogram": []})
def stats(bucket: int = 10) -> dict:
    """Score histogram over profiles that reached scoring, plus like rate."""
    with _db() as con:
        rows = con.execute("SELECT score, decision FROM profiles").fetchall()
    scored = [r["score"] for r in rows if r["score"] is not None]
    hist = []
    for lo in range(0, 100, bucket):
        hi = lo + bucket
        hist.append({"from": lo, "to": hi,
                     "count": sum(1 for s in scored
                                  if lo <= s < hi or (hi == 100 and s == 100))})
    likes = sum(1 for r in rows if r["decision"] == "like")
    return {"total": len(rows), "likes": likes,
            "like_rate": round(likes / len(rows), 3) if rows else None,
            "histogram": hist}
