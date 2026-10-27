"""In-app scheduler: starts swipe sessions at set times of day.

The app must be open and the Mac awake for this to run (see
packaging/launch_agent.py to open the app at login). Scheduled runs behave
like cron runs: they keep the random "skip this run" roll and quiet hours,
and times are jittered. The limits (sessions per day, minimum gap) live in
settings.validate_schedule.

Catch-up: a time that passes while the Mac sleeps is run once, late, when it
wakes (within CATCH_UP_SECONDS). A hard floor between sessions stops catch-ups
from stacking. The Mac is kept awake only while a session runs (see
controller.py), so it sleeps normally otherwise.
"""

import threading
import time

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import runlog
import settings

TZ = "Europe/Paris"
CATCH_UP_SECONDS = 2 * 3600        # how late a missed time may still run
MIN_SESSION_GAP_SECONDS = 2 * 3600  # never start a scheduled run this soon after another
HEARTBEAT_SECONDS = 60


class Schedule:
    def __init__(self, controller):
        self.controller = controller
        self.sched = BackgroundScheduler(timezone=TZ)
        self.last_fire = None
        self._beat_stop = threading.Event()

    def start(self):
        self.sched.start()
        self.apply(settings.read_schedule())
        threading.Thread(target=self._heartbeat, daemon=True).start()

    def _heartbeat(self):
        """After a sleep the scheduler's timer is still counting awake time
        only; nudge it so it re-reads the clock and runs anything it missed."""
        while not self._beat_stop.wait(HEARTBEAT_SECONDS):
            try:
                if self.sched.running:
                    self.sched.wakeup()
            except Exception:
                pass

    def shutdown(self):
        self._beat_stop.set()
        if self.sched.running:
            self.sched.shutdown(wait=False)

    def apply(self, cfg: dict):
        """Replace all jobs with the ones in `cfg` (already validated)."""
        self.sched.remove_all_jobs()
        if not cfg.get("enabled"):
            return
        for t in cfg["times"]:
            hour, minute = (int(x) for x in t.split(":"))
            self.sched.add_job(
                self._fire, CronTrigger(hour=hour, minute=minute,
                                        jitter=cfg["jitter_minutes"] * 60,
                                        timezone=TZ),
                id=f"session-{t}", replace_existing=True,
                misfire_grace_time=CATCH_UP_SECONDS, coalesce=True, max_instances=1)

    def _fire(self):
        """Start a scheduled (non-manual) session unless one is running."""
        if self.controller.is_running():
            self.last_fire = "skipped: a session was already running"
            return
        last = runlog.last_session_start()
        if last is not None and time.time() - last < MIN_SESSION_GAP_SECONDS:
            mins = int((time.time() - last) / 60)
            self.last_fire = f"skipped: last session started {mins} min ago"
            return
        started = self.controller.start(**settings.run_kwargs(), manual=False)
        self.last_fire = "started" if started else "skipped: could not start"

    def status(self) -> dict:
        cfg = settings.read_schedule()
        nxt = sorted(j.next_run_time.isoformat() for j in self.sched.get_jobs()
                     if j.next_run_time)
        return {**cfg, "next_runs": nxt, "last_fire": self.last_fire,
                "keeping_awake": bool(getattr(getattr(self.controller, "awake", None),
                                              "active", False)),
                "limits": {"max_sessions_per_day": settings.MAX_SESSIONS_PER_DAY,
                           "min_gap_hours": settings.MIN_GAP_MINUTES // 60,
                           "max_jitter_minutes": settings.MAX_JITTER_MINUTES}}
