"""In-app scheduler: starts swipe sessions at set times of day.

The app must be open for this to run (see packaging/launch_agent.py to have
macOS open it at login). Scheduled runs behave like cron runs: they keep the
random "skip this run" roll and quiet hours, and times are jittered. The
limits (sessions per day, minimum gap) live in settings.validate_schedule.
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import settings

TZ = "Europe/Paris"


class Schedule:
    def __init__(self, controller):
        self.controller = controller
        self.sched = BackgroundScheduler(timezone=TZ)
        self.last_fire = None

    def start(self):
        self.sched.start()
        self.apply(settings.read_schedule())

    def shutdown(self):
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
                misfire_grace_time=600, coalesce=True, max_instances=1)

    def _fire(self):
        """Start a scheduled (non-manual) session unless one is running."""
        if self.controller.is_running():
            self.last_fire = "skipped: a session was already running"
            return
        started = self.controller.start(**settings.run_kwargs(), manual=False)
        self.last_fire = "started" if started else "skipped: could not start"

    def status(self) -> dict:
        cfg = settings.read_schedule()
        nxt = sorted(j.next_run_time.isoformat() for j in self.sched.get_jobs()
                     if j.next_run_time)
        return {**cfg, "next_runs": nxt, "last_fire": self.last_fire,
                "limits": {"max_sessions_per_day": settings.MAX_SESSIONS_PER_DAY,
                           "min_gap_hours": settings.MIN_GAP_MINUTES // 60,
                           "max_jitter_minutes": settings.MAX_JITTER_MINUTES}}
