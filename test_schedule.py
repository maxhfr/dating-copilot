"""Schedule validation, the scheduler and the launch agent plist.

    python test_schedule.py

Needs APScheduler, PyYAML, Flask and anthropic installed.
"""

import os
import plistlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, "src")
sys.path.insert(0, "packaging")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")
_HOME = tempfile.TemporaryDirectory()
os.environ["DATING_COPILOT_HOME"] = _HOME.name

import settings  # noqa: E402
import runlog  # noqa: E402
from scheduler import Schedule  # noqa: E402
from app import create_app  # noqa: E402
import launch_agent  # noqa: E402


class FakeController:
    def __init__(self):
        self.running = False
        self.calls = []

    def is_running(self):
        return self.running

    def start(self, **kw):
        self.calls.append(kw)
        return True

    def status(self):
        return {"state": "idle", "running": False, "messages": [], "last_summary": None}


class Base(unittest.TestCase):
    def setUp(self):
        f = runlog.home() / "settings.json"
        if f.exists():
            f.unlink()
        self.tmp = tempfile.TemporaryDirectory()
        self.rub, self.sc = Path(self.tmp.name, "r.yaml"), Path(self.tmp.name, "s.yaml")
        shutil.copy(settings.RUBRIC, self.rub)
        shutil.copy(settings.SCORING, self.sc)
        self._old = (settings.RUBRIC, settings.SCORING)
        settings.RUBRIC, settings.SCORING = self.rub, self.sc

    def tearDown(self):
        settings.RUBRIC, settings.SCORING = self._old
        self.tmp.cleanup()


class ValidationTests(Base):
    def test_good_schedule_is_sorted_and_normalised(self):
        c = settings.validate_schedule({"enabled": True, "times": ["18:05", "9:17", "13:42"]})
        self.assertEqual(c["times"], ["09:17", "13:42", "18:05"])
        self.assertEqual(c["jitter_minutes"], 20)

    def test_rejects_bad_input(self):
        for bad in ({"times": ["25:00"]}, {"times": ["9am"]},
                    {"times": "09:00"},
                    {"times": ["09:00", "10:00"]},                 # too close
                    {"times": ["09:00", "12:00", "15:00", "18:00", "21:00"]},  # 5
                    {"times": ["03:00"]},                          # quiet hours
                    {"times": ["09:00"], "jitter_minutes": 90},
                    {"times": ["07:30"]}):                         # quiet until 08:00
            with self.assertRaises(ValueError, msg=str(bad)):
                settings.validate_schedule(bad)

    def test_wraps_around_midnight_gap(self):
        # 22:00 and 09:00 are 11h apart one way, 13h the other: fine.
        settings.validate_schedule({"times": ["09:00", "22:00"]})
        # 23:30 and 08:30 are only 9h apart overnight but 15h by day: fine.
        settings.validate_schedule({"times": ["08:30", "23:30"]})

    def test_write_and_read_roundtrip_and_survives_settings_save(self):
        settings.write_schedule({"enabled": True, "times": ["09:17", "18:40"]})
        settings.write({"auto_like": 60})       # rewrites settings.json
        s = settings.read_schedule()
        self.assertEqual((s["enabled"], s["times"]), (True, ["09:17", "18:40"]))
        self.assertEqual(settings.read()["auto_like"], 60)


class SchedulerTests(Base):
    def setUp(self):
        super().setUp()
        self.ctl = FakeController()
        self.s = Schedule(self.ctl)
        self.s.sched.start(paused=True)     # no real firing during tests

    def tearDown(self):
        self.s.shutdown()
        super().tearDown()

    def test_jobs_registered_with_jitter(self):
        cfg = settings.validate_schedule({"enabled": True, "times": ["09:17", "18:40"],
                                          "jitter_minutes": 10})
        self.s.apply(cfg)
        jobs = sorted(self.s.sched.get_jobs(), key=lambda j: j.id)
        self.assertEqual([j.id for j in jobs], ["session-09:17", "session-18:40"])
        self.assertEqual(jobs[0].trigger.jitter, 600)

    def test_disabled_means_no_jobs(self):
        self.s.apply({"enabled": True, "times": ["09:17"], "jitter_minutes": 5})
        self.s.apply({"enabled": False, "times": ["09:17"], "jitter_minutes": 5})
        self.assertEqual(self.s.sched.get_jobs(), [])

    def test_fire_starts_non_manual_session_with_limits(self):
        self.s._fire()
        self.assertEqual(len(self.ctl.calls), 1)
        kw = self.ctl.calls[0]
        self.assertIs(kw["manual"], False)       # keeps the random skip
        self.assertIn("quiet_hours", kw)
        self.assertEqual(self.s.last_fire, "started")

    def test_fire_skips_when_busy(self):
        self.ctl.running = True
        self.s._fire()
        self.assertEqual(self.ctl.calls, [])
        self.assertTrue(self.s.last_fire.startswith("skipped"))

    def test_status_lists_next_runs_and_limits(self):
        self.s.apply({"enabled": True, "times": ["09:17"], "jitter_minutes": 0})
        st = self.s.status()
        self.assertEqual(len(st["next_runs"]), 1)
        self.assertEqual(st["limits"]["max_sessions_per_day"], 4)


class CatchUpTests(Base):
    def setUp(self):
        super().setUp()
        self.ctl = FakeController()
        self.s = Schedule(self.ctl)
        self.s.sched.start(paused=True)
        self._orig = runlog.last_session_start

    def tearDown(self):
        runlog.last_session_start = self._orig
        self.s.shutdown()
        super().tearDown()

    def test_job_may_run_late_after_sleep(self):
        self.s.apply({"enabled": True, "times": ["09:17"], "jitter_minutes": 0})
        job = self.s.sched.get_jobs()[0]
        self.assertEqual(job.misfire_grace_time, 2 * 3600)
        self.assertTrue(job.coalesce)

    def test_floor_between_sessions_blocks_stacked_catch_ups(self):
        import time as _t
        runlog.last_session_start = lambda: _t.time() - 30 * 60       # 30 min ago
        self.s._fire()
        self.assertEqual(self.ctl.calls, [])
        self.assertIn("min ago", self.s.last_fire)

    def test_runs_when_last_session_was_long_ago(self):
        import time as _t
        runlog.last_session_start = lambda: _t.time() - 5 * 3600
        self.s._fire()
        self.assertEqual(len(self.ctl.calls), 1)

    def test_runs_when_no_session_ever(self):
        runlog.last_session_start = lambda: None
        self.s._fire()
        self.assertEqual(len(self.ctl.calls), 1)

    def test_heartbeat_wakes_the_scheduler(self):
        import scheduler as sch
        calls = []
        self.s.sched.wakeup = lambda: calls.append(1)
        old = sch.HEARTBEAT_SECONDS
        sch.HEARTBEAT_SECONDS = 0.05
        try:
            self.s.sched.start  # already started (paused)
            import threading as _th
            _th.Thread(target=self.s._heartbeat, daemon=True).start()
            import time as _t
            _t.sleep(0.4)
        finally:
            sch.HEARTBEAT_SECONDS = old
            self.s._beat_stop.set()
        self.assertGreaterEqual(len(calls), 2)


class KeepAwakeTests(unittest.TestCase):
    def test_noop_off_mac(self):
        import keep_awake
        from unittest import mock
        with mock.patch.object(keep_awake.sys, "platform", "linux"):
            k = keep_awake.KeepAwake()
            self.assertFalse(k.set(True))

    def test_spawns_caffeinate_on_mac_and_stops(self):
        import keep_awake
        from unittest import mock
        proc = mock.Mock()
        proc.poll.return_value = None
        with mock.patch.object(keep_awake.sys, "platform", "darwin"), \
                mock.patch.object(keep_awake.shutil, "which", return_value="/usr/bin/caffeinate"), \
                mock.patch.object(keep_awake.subprocess, "Popen", return_value=proc) as popen:
            k = keep_awake.KeepAwake()
            self.assertTrue(k.set(True))
            cmd = popen.call_args[0][0]
            self.assertEqual(cmd[:2], ["/usr/bin/caffeinate", "-i"])
            self.assertEqual(cmd[-2], "-w")
            k.set(False)
            proc.terminate.assert_called_once()
            self.assertFalse(k.active)

    def test_apply_toggles_keep_awake(self):
        ctl = FakeController()
        s = Schedule(ctl)
        s.sched.start(paused=True)
        seen = []
        s.awake.set = lambda v: seen.append(v) or False
        s.apply({"enabled": True, "times": ["09:17"], "jitter_minutes": 0})
        s.apply({"enabled": False, "times": [], "jitter_minutes": 0})
        s.shutdown()
        self.assertEqual(seen[:2], [True, False])


class RouteTests(Base):
    def setUp(self):
        super().setUp()
        self.ctl = FakeController()
        self.s = Schedule(self.ctl)
        self.s.sched.start(paused=True)
        self.app = create_app(self.ctl, self.s)
        self.c = self.app.test_client()
        self.base = "http://127.0.0.1:5000"
        page = self.c.get("/", base_url=self.base).get_data(as_text=True)
        self.tok = page.split('const TOKEN = "')[1].split('"')[0]

    def tearDown(self):
        self.s.shutdown()
        super().tearDown()

    def post(self, body, token=True):
        return self.c.post("/api/schedule", json=body, base_url=self.base,
                           headers={"X-App-Token": self.tok} if token else {})

    def test_requires_token(self):
        self.assertEqual(self.post({"enabled": True}, token=False).status_code, 403)

    def test_invalid_schedule_is_400_and_not_applied(self):
        r = self.post({"enabled": True, "times": ["09:00", "10:00"]})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.s.sched.get_jobs(), [])

    def test_valid_schedule_applies_jobs(self):
        r = self.post({"enabled": True, "times": ["09:17", "18:40"], "jitter_minutes": 15})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.get_json()["next_runs"]), 2)
        got = self.c.get("/api/schedule", base_url=self.base).get_json()
        self.assertEqual(got["times"], ["09:17", "18:40"])


class LaunchAgentTests(unittest.TestCase):
    def test_plist_is_valid_and_points_at_run_sh(self):
        root = Path("/tmp/dating-copilot")
        data = plistlib.loads(plistlib.dumps(launch_agent.build_plist(root)))
        self.assertEqual(data["ProgramArguments"], [str(root / "run.sh"), "app"])
        self.assertTrue(data["RunAtLoad"])
        self.assertFalse(data["KeepAlive"])        # quitting the app stays quit


if __name__ == "__main__":
    unittest.main(verbosity=2)
