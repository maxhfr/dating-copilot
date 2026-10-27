"""Runs a swipe session in a background thread so a UI can start and stop it.

The session gets its own asyncio event loop. Stopping sets the stop event
(checked between profiles) and cancels the task so a long pause ends at once;
the browser is closed by the platform's context manager either way.
"""

import asyncio
import importlib
import threading
from collections import deque

import judge
import notifier
import main as session_main


class SessionController:
    def __init__(self):
        self._thread = None
        self._loop = None
        self._task = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.state = "idle"            # idle | running | stopping | error
        self.last_summary = None
        self.messages = deque(maxlen=200)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> dict:
        return {"state": self.state, "running": self.is_running(),
                "messages": list(self.messages)[-30:],
                "last_summary": self.last_summary}

    def start(self, **run_kwargs) -> bool:
        """Start a session; False if one is already running."""
        with self._lock:
            if self.is_running():
                return False
            # Pick up config edits (rubric / threshold) made since import.
            importlib.reload(judge)
            importlib.reload(notifier)   # Telegram settings are read at import
            self._stop.clear()
            self.messages.clear()
            self.state = "running"
            self._thread = threading.Thread(
                target=self._run, kwargs=run_kwargs, daemon=True)
            self._thread.start()
            return True

    def stop(self) -> bool:
        with self._lock:
            if not self.is_running():
                return False
            self.state = "stopping"
            self._stop.set()
            if self._loop and self._task:
                self._loop.call_soon_threadsafe(self._task.cancel)
            return True

    def start_login(self) -> bool:
        """Open the browser so the user can log in; False if busy."""
        with self._lock:
            if self.is_running():
                return False
            self._stop.clear()
            self.messages.clear()
            self.state = "running"
            self._thread = threading.Thread(
                target=self._run, kwargs={"login": True}, daemon=True)
            self._thread.start()
            return True

    def _run(self, login: bool = False, **run_kwargs):
        loop = asyncio.new_event_loop()
        self._loop = loop
        try:
            if login:
                coro = session_main.login_only(
                    on_status=self.messages.append, stop_event=self._stop)
            else:
                run_kwargs.setdefault("manual", True)
                coro = session_main.run_session(
                    on_status=self.messages.append, stop_event=self._stop,
                    wait_for_login=session_main.poll_login(
                        self._stop, self.messages.append),
                    **run_kwargs)
            self._task = loop.create_task(coro)
            result = loop.run_until_complete(self._task)
            if not login:
                self.last_summary = result
            self.state = "idle"
        except asyncio.CancelledError:
            self.state = "idle"
        except Exception as e:
            self.messages.append(f"error: {type(e).__name__}: {e}")
            self.state = "error"
        finally:
            loop.close()
            self._loop = self._task = None
