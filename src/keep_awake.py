"""Stop the computer idling to sleep while a session is running.

macOS: `caffeinate -i -w <our pid>` prevents idle sleep (the screen may still
turn off) and exits by itself when the app quits.
Windows: SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED). That flag
belongs to the calling thread, so set() must be called from the same thread
for on and off (the session controller does this).
A closed laptop lid still sleeps the machine. Does nothing on other systems.
"""

import os
import shutil
import subprocess
import sys


ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def _win_set(on: bool) -> bool:
    import ctypes
    flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0)
    return bool(ctypes.windll.kernel32.SetThreadExecutionState(flags))


class KeepAwake:
    def __init__(self):
        self._proc = None
        self._win_on = False

    @property
    def active(self) -> bool:
        if sys.platform == "win32":
            return self._win_on
        return self._proc is not None and self._proc.poll() is None

    def set(self, enabled: bool) -> bool:
        """Turn it on or off; returns whether the machine is being kept awake."""
        if sys.platform == "win32":
            if enabled and not self._win_on:
                try:
                    self._win_on = _win_set(True)
                except Exception:
                    self._win_on = False
            elif not enabled and self._win_on:
                try:
                    _win_set(False)
                finally:
                    self._win_on = False
            return self._win_on
        if enabled and not self.active:
            exe = shutil.which("caffeinate") if sys.platform == "darwin" else None
            if exe:
                self._proc = subprocess.Popen(
                    [exe, "-i", "-w", str(os.getpid())],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif not enabled and self._proc is not None:
            if self._proc.poll() is None:
                self._proc.terminate()
            self._proc = None
        return self.active
