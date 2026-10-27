"""Session loop, run log and controller tests using a fake platform.

    python test_session.py

No network, no browser, no API calls. Needs the project's Python
dependencies (anthropic, PyYAML) installed, because it imports src/main.py.
"""

import asyncio
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, "src")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")
_TMP = tempfile.TemporaryDirectory()
os.environ["DATING_COPILOT_HOME"] = _TMP.name   # keep the run log out of ~

import main  # noqa: E402
import runlog  # noqa: E402
from controller import SessionController  # noqa: E402
from platforms.base import Platform  # noqa: E402


class FakePlatform(Platform):
    """Scripted deck. `profiles` is a list of dicts (or None = unreadable)."""
    script = []
    swipes = []

    def __init__(self, headless=False):
        self.queue = list(FakePlatform.script)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def ensure_logged_in(self):
        pass

    async def check_blocked(self, expect="recs"):
        return None

    async def dismiss_modals(self):
        return None

    async def read_current_profile(self):
        await asyncio.sleep(0)
        return self.queue.pop(0) if self.queue else None

    async def swipe(self, like):
        FakePlatform.swipes.append(like)

    async def idle(self):
        pass

    async def diagnose_no_card(self):
        return "out of likes (Tinder Plus popup)"


def prof(i, name="Ana"):
    return {"id": f"fake:{name}{i}", "name": f"{name}{i}", "age": 28,
            "distance_km": 5, "photos": [], "bio": "", "lifestyle": {}}


class FakeJudge:
    """score = 80 for names starting with 'Hi', else 30."""
    @staticmethod
    def evaluate(p):
        hi = p["name"].startswith("Hi")
        return {"like": hi, "score": 80 if hi else 30, "stage": 2,
                "why": "fake", "hooks": ["travel"], "breakdown": {"hair": ("blonde", 16)}}


class SessionTests(unittest.TestCase):
    def setUp(self):
        FakePlatform.swipes = []
        self._patches = [
            (main, "get_platform", main.get_platform),
            (main, "judge", main.judge),
            (main, "session_digest", main.session_digest),
            (main, "alert", main.alert),
            (main, "HOLD_ON_STOP", main.HOLD_ON_STOP),
            (main, "DIGEST_EVERY", main.DIGEST_EVERY),
        ]
        main.get_platform = lambda name: FakePlatform
        main.judge = FakeJudge
        self.digests, self.alerts = [], []
        main.session_digest = lambda **kw: self.digests.append(kw)
        main.alert = lambda text: self.alerts.append(text)
        main.HOLD_ON_STOP = False
        main.DIGEST_EVERY = 0
        runlog_db = runlog.home() / "runlog.db"
        if runlog_db.exists():
            runlog_db.unlink()

    def tearDown(self):
        for obj, name, val in self._patches:
            setattr(obj, name, val)

    def run_it(self, **kw):
        kw.setdefault("manual", True)
        kw.setdefault("max_likes", 10)
        kw.setdefault("quiet_hours", range(0))   # never quiet in tests
        return asyncio.run(main.run_session(**kw))

    def test_callbacks_and_runlog(self):
        FakePlatform.script = [prof(1, "Hi"), prof(2, "Lo"), prof(3, "Hi")]
        got, status = [], []
        s = self.run_it(on_profile=got.append, on_status=status.append)
        self.assertEqual([g["like"] for g in got], [True, False, True])
        self.assertEqual(s["reviewed"], 3)
        self.assertEqual(s["likes"], 2)
        self.assertTrue(any("Done." in m for m in status))
        rows = runlog.recent(10)
        self.assertEqual(len(rows), 3)
        self.assertEqual({r["decision"] for r in rows}, {"like", "pass"})
        st = runlog.stats()
        self.assertEqual(st["total"], 3)
        self.assertAlmostEqual(st["like_rate"], 0.667, places=2)
        self.assertEqual(sum(b["count"] for b in st["histogram"]), 3)

    def test_stop_event_ends_session_cleanly(self):
        FakePlatform.script = [prof(i, "Lo") for i in range(50)]
        ev = threading.Event()
        seen = []

        def on_profile(p):
            seen.append(p)
            if len(seen) == 2:
                ev.set()

        s = self.run_it(on_profile=on_profile, stop_event=ev, max_likes=45)
        self.assertEqual(s["stopped"], "stopped by you")
        self.assertEqual(len(seen), 2)
        self.assertEqual(self.alerts, [])     # a stop request is not an alert

    def test_out_of_likes_stops_without_alert(self):
        FakePlatform.script = []              # deck unreadable from the start
        s = self.run_it()
        self.assertTrue(s["stopped"].startswith("out of likes"))
        self.assertEqual(self.alerts, [])

    def test_quiet_hours_respected_even_when_manual(self):
        from datetime import datetime
        s = self.run_it(quiet_hours=range(24))
        self.assertEqual(s["stopped"], "quiet hours")
        self.assertEqual(FakePlatform.swipes, [])

    def test_like_cap_respected(self):
        FakePlatform.script = [prof(i, "Hi") for i in range(30)]
        s = self.run_it(max_likes=4)
        self.assertGreaterEqual(s["likes"], 1)
        self.assertLessEqual(s["likes"], 4)


class ControllerTests(unittest.TestCase):
    def test_start_stop_roundtrip(self):
        FakePlatform.script = [prof(i, "Lo") for i in range(10000)]
        orig = (main.get_platform, main.judge, main.HOLD_ON_STOP,
                main.session_digest, main.alert)
        main.get_platform = lambda name: FakePlatform
        main.session_digest = lambda **kw: None
        main.alert = lambda text: None
        main.HOLD_ON_STOP = False
        import controller as ctl
        real_reload = ctl.importlib.reload
        ctl.importlib.reload = lambda m: m          # keep the FakeJudge
        main.judge = FakeJudge
        try:
            c = SessionController()
            self.assertTrue(c.start(max_likes=45, quiet_hours=range(0)))
            self.assertFalse(c.start())              # already running
            time.sleep(0.3)
            self.assertTrue(c.is_running())
            self.assertTrue(c.stop())
            for _ in range(50):
                if not c.is_running():
                    break
                time.sleep(0.1)
            self.assertFalse(c.is_running())
            self.assertEqual(c.state, "idle")
            self.assertEqual(c.last_summary["stopped"], "stopped by you")
        finally:
            ctl.importlib.reload = real_reload
            (main.get_platform, main.judge, main.HOLD_ON_STOP,
             main.session_digest, main.alert) = orig


if __name__ == "__main__":
    unittest.main(verbosity=2)
