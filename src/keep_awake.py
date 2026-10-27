"""Stop the Mac idling to sleep while a session is running.

Uses macOS `caffeinate -i -w <our pid>`: it prevents idle sleep (the screen
may still turn off) and exits by itself when the app quits. A closed laptop
lid still sleeps the Mac. Does nothing on other systems.
"""

import os
import shutil
import subprocess
import sys


class KeepAwake:
    def __init__(self):
        self._proc = None

    @property
    def active(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def set(self, enabled: bool) -> bool:
        """Turn it on or off; returns whether the Mac is being kept awake."""
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
