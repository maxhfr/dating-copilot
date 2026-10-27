"""SQLite run log: one row per session and per profile reviewed.

Feeds the live view and the calibration view (score histogram, like rate).
Stores names, ages, scores and the model's reasons. It does NOT store photos
or bios. Logging problems never interrupt a swipe session.
"""

import json
import os
import sqlite3
import time
import unicodedata
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
CREATE TABLE IF NOT EXISTS matches (
    id TEXT PRIMARY KEY, platform TEXT, name TEXT, first_seen REAL,
    baseline INTEGER DEFAULT 0, profile_id INTEGER);
CREATE TABLE IF NOT EXISTS tracking (
    platform TEXT PRIMARY KEY, started_at REAL,
    last_snapshot_at REAL, last_seen_count INTEGER);
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


@_safe(None)
def last_session_start():
    """Unix time the most recent session started, or None."""
    with _db() as con:
        row = con.execute("SELECT MAX(started_at) AS t FROM sessions").fetchone()
    return row["t"] if row and row["t"] else None


def _norm(name) -> str:
    """Accent- and case-insensitive form of a first name, for matching."""
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    return "".join(c for c in s.lower() if c.isalnum())


ATTRIBUTION_WINDOW = 30 * 86400   # a match is credited to a like from the last 30 days


def _attribute(con, platform: str, name: str, now: float):
    """Most recent unmatched liked profile with the same first name, or None.
    Approximate on purpose: the match list only gives a first name."""
    rows = con.execute(
        "SELECT id, name FROM profiles WHERE platform=? AND decision='like' "
        "AND ts<=? AND ts>=? AND id NOT IN "
        "(SELECT profile_id FROM matches WHERE profile_id IS NOT NULL) "
        "ORDER BY ts DESC", (platform, now, now - ATTRIBUTION_WINDOW)).fetchall()
    want = _norm(name)
    for row in rows:
        if want and _norm(row["name"]) == want:
            return row["id"]
    return None


@_safe(None)
def record_match_snapshot(platform: str, entries: list[dict]):
    """Record the match ids visible right now.

    The first snapshot for a platform is a baseline: the matches that already
    exist are noted but never counted. Later snapshots count each unseen id
    once. Returns {"baseline": bool, "new": int, "seen": int}.
    """
    now = time.time()
    with _db() as con:
        started = con.execute("SELECT started_at FROM tracking WHERE platform=?",
                              (platform,)).fetchone()
        baseline = started is None
        known = {r["id"] for r in con.execute(
            "SELECT id FROM matches WHERE platform=?", (platform,))}
        new = 0
        for e in entries or []:
            mid = str(e.get("id") or "").strip()
            if not mid or mid in known:
                continue
            known.add(mid)
            name = e.get("name") or ""
            if baseline:
                con.execute("INSERT INTO matches (id, platform, name, first_seen, baseline) "
                            "VALUES (?,?,?,?,1)", (mid, platform, name, now))
            else:
                con.execute("INSERT INTO matches (id, platform, name, first_seen, baseline, "
                            "profile_id) VALUES (?,?,?,?,0,?)",
                            (mid, platform, name, now, _attribute(con, platform, name, now)))
                new += 1
        if baseline:
            con.execute("INSERT INTO tracking (platform, started_at, last_snapshot_at, "
                        "last_seen_count) VALUES (?,?,?,?)",
                        (platform, now, now, len(entries or [])))
        else:
            con.execute("UPDATE tracking SET last_snapshot_at=?, last_seen_count=? "
                        "WHERE platform=?", (now, len(entries or []), platform))
    return {"baseline": baseline, "new": new, "seen": len(entries or [])}


def _empty_conversion() -> dict:
    return {"tracking": False, "since": None, "likes": 0, "matches": 0, "rate": None,
            "last7": {"likes": 0, "matches": 0, "rate": None}, "bands": [],
            "last_snapshot_at": None, "visible_matches": None}


def _rate(matches: int, likes: int):
    return round(matches / likes, 3) if likes else None


@_safe(_empty_conversion())
def conversion_stats(platform: str = "tinder", bucket: int = 10) -> dict:
    """Like -> match conversion since match tracking began.

    rate = new matches / likes sent since tracking began. Matches that arrive
    after a session are added at the next snapshot, so recent numbers lag.
    Per-band figures use the approximate first-name attribution.
    """
    now = time.time()
    with _db() as con:
        t = con.execute("SELECT * FROM tracking WHERE platform=?", (platform,)).fetchone()
        if t is None:
            return _empty_conversion()
        since = t["started_at"]
        likes = con.execute("SELECT COUNT(*) AS n FROM profiles WHERE platform=? AND "
                            "decision='like' AND ts>=?", (platform, since)).fetchone()["n"]
        matches = con.execute("SELECT COUNT(*) AS n FROM matches WHERE platform=? AND "
                              "baseline=0", (platform,)).fetchone()["n"]
        week = max(since, now - 7 * 86400)
        likes7 = con.execute("SELECT COUNT(*) AS n FROM profiles WHERE platform=? AND "
                             "decision='like' AND ts>=?", (platform, week)).fetchone()["n"]
        matches7 = con.execute("SELECT COUNT(*) AS n FROM matches WHERE platform=? AND "
                               "baseline=0 AND first_seen>=?", (platform, week)).fetchone()["n"]
        liked = con.execute("SELECT id, score FROM profiles WHERE platform=? AND "
                            "decision='like' AND ts>=? AND score IS NOT NULL",
                            (platform, since)).fetchall()
        matched_ids = {r["profile_id"] for r in con.execute(
            "SELECT profile_id FROM matches WHERE platform=? AND baseline=0 AND "
            "profile_id IS NOT NULL", (platform,))}
    bands = {}
    for row in liked:
        lo = min(row["score"] // bucket * bucket, 100 - bucket)
        b = bands.setdefault(lo, {"from": lo, "to": lo + bucket, "likes": 0, "matches": 0})
        b["likes"] += 1
        b["matches"] += 1 if row["id"] in matched_ids else 0
    band_list = sorted(bands.values(), key=lambda b: -b["from"])
    for b in band_list:
        b["rate"] = _rate(b["matches"], b["likes"])
    return {"tracking": True, "since": since, "likes": likes, "matches": matches,
            "rate": _rate(matches, likes),
            "last7": {"likes": likes7, "matches": matches7, "rate": _rate(matches7, likes7)},
            "bands": band_list, "last_snapshot_at": t["last_snapshot_at"],
            "visible_matches": t["last_seen_count"]}


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
