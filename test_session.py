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
import types
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
    logged_in = True
    delay = 0
    fail_login = False

    def __init__(self, headless=False):
        self.queue = list(FakePlatform.script)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def ensure_logged_in(self, wait_for_login=None):
        if FakePlatform.fail_login:
            raise RuntimeError("browser failed to launch")
        if wait_for_login is not None and not self.logged_in:
            await wait_for_login(self)

    async def is_logged_in(self):
        return self.logged_in

    async def check_blocked(self, expect="recs"):
        return None

    async def dismiss_modals(self):
        return None

    async def read_current_profile(self):
        await asyncio.sleep(FakePlatform.delay)
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
            (main, "notifier", main.notifier),
            (main, "HOLD_ON_STOP", main.HOLD_ON_STOP),
            (main, "DIGEST_EVERY", main.DIGEST_EVERY),
        ]
        main.get_platform = lambda name: FakePlatform
        main.judge = FakeJudge
        self.digests, self.alerts = [], []
        main.notifier = types.SimpleNamespace(
            session_digest=lambda **kw: self.digests.append(kw),
            alert=lambda text: self.alerts.append(text))
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


class LoginTests(unittest.TestCase):
    def setUp(self):
        self._gp = main.get_platform
        main.get_platform = lambda name: FakePlatform

    def tearDown(self):
        main.get_platform = self._gp
        FakePlatform.logged_in = True

    def test_already_logged_in(self):
        status = []
        r = asyncio.run(main.login_only(on_status=status.append, timeout=5))
        self.assertTrue(r["logged_in"])
        self.assertTrue(any("Logged in" in m for m in status))

    def test_waits_until_login_completes(self):
        FakePlatform.logged_in = False
        threading.Timer(0.5, lambda: setattr(FakePlatform, "logged_in", True)).start()
        r = asyncio.run(main.login_only(timeout=10))
        self.assertTrue(r["logged_in"])

    def test_cancel_via_stop_event(self):
        FakePlatform.logged_in = False
        ev = threading.Event()
        threading.Timer(0.5, ev.set).start()
        r = asyncio.run(main.login_only(stop_event=ev, timeout=30))
        self.assertFalse(r["logged_in"])

    def test_launch_failure_is_reported_and_logged(self):
        FakePlatform.fail_login = True
        try:
            status = []
            r = asyncio.run(main.login_only(on_status=status.append, timeout=5))
        finally:
            FakePlatform.fail_login = False
        self.assertFalse(r["logged_in"])
        self.assertTrue(any("Login failed: RuntimeError" in m for m in status))
        log = (runlog.home() / "app.log").read_text()
        self.assertIn("browser failed to launch", log)
        self.assertIn("Traceback", log)

    def test_controller_messages_are_logged(self):
        c = SessionController()
        c.messages.append("hello from the controller")
        self.assertIn("hello from the controller", (runlog.home() / "app.log").read_text())

    def test_timeout_reports_failure(self):
        FakePlatform.logged_in = False
        status = []
        r = asyncio.run(main.login_only(on_status=status.append, timeout=2))
        self.assertFalse(r["logged_in"])
        self.assertTrue(any("timed out" in m for m in status))


class CliTests(unittest.TestCase):
    def test_cli_passes_platform_and_loads_env(self):
        import cli
        seen = {}

        async def fake_run_session(platform="tinder", **kw):
            seen["platform"] = platform
            return {"reviewed": 0}
        orig = main.run_session
        main.run_session = fake_run_session
        try:
            cli.run(["cli.py"])
            self.assertEqual(seen["platform"], "tinder")
            cli.run(["cli.py", "tinder"])
            self.assertEqual(seen["platform"], "tinder")
        finally:
            main.run_session = orig


class RecordingAwake:
    def __init__(self):
        self.calls = []
        self.active = False

    def set(self, on):
        self.calls.append(on)
        self.active = on
        return on


class AwakeTests(unittest.TestCase):
    def _controller(self):
        c = SessionController()
        c.awake = RecordingAwake()
        return c

    def test_awake_only_while_a_session_runs(self):
        FakePlatform.script = [prof(i, "Lo") for i in range(10000)]
        FakePlatform.delay = 0.05
        orig = (main.get_platform, main.judge, main.HOLD_ON_STOP, main.notifier)
        main.get_platform = lambda name: FakePlatform
        main.notifier = types.SimpleNamespace(
            session_digest=lambda **kw: None, alert=lambda text: None)
        main.HOLD_ON_STOP = False
        import controller as ctl
        real_reload = ctl.importlib.reload
        ctl.importlib.reload = lambda m: m
        main.judge = FakeJudge
        try:
            c = self._controller()
            self.assertEqual(c.awake.calls, [])          # idle: not held
            c.start(max_likes=45, quiet_hours=range(0))
            time.sleep(0.3)
            self.assertTrue(c.awake.active)              # held while swiping
            c.stop()
            for _ in range(50):
                if not c.is_running():
                    break
                time.sleep(0.1)
            self.assertFalse(c.awake.active)             # released after
            self.assertEqual(c.awake.calls, [True, False])
        finally:
            ctl.importlib.reload = real_reload
            FakePlatform.delay = 0
            (main.get_platform, main.judge, main.HOLD_ON_STOP, main.notifier) = orig

    def test_login_does_not_hold_the_mac_awake(self):
        c = self._controller()
        orig = main.login_only

        async def quick_login(**kw):
            return {"logged_in": True}
        main.login_only = quick_login
        try:
            self.assertTrue(c.start_login())
            for _ in range(50):
                if not c.is_running():
                    break
                time.sleep(0.05)
        finally:
            main.login_only = orig
        self.assertFalse(c.awake.active)
        self.assertNotIn(True, c.awake.calls)


class ControllerTests(unittest.TestCase):
    def test_start_stop_roundtrip(self):
        FakePlatform.script = [prof(i, "Lo") for i in range(10000)]
        FakePlatform.delay = 0.05      # slow enough to still be running below
        orig = (main.get_platform, main.judge, main.HOLD_ON_STOP, main.notifier)
        main.get_platform = lambda name: FakePlatform
        main.notifier = types.SimpleNamespace(
            session_digest=lambda **kw: None, alert=lambda text: None)
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
            FakePlatform.delay = 0
            (main.get_platform, main.judge, main.HOLD_ON_STOP,
             main.notifier) = orig


if __name__ == "__main__":
    unittest.main(verbosity=2)
