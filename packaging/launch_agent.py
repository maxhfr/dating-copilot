"""Open the app automatically at login with a macOS launchd agent.

    python packaging/launch_agent.py install     # writes and loads the agent
    python packaging/launch_agent.py uninstall
    python packaging/launch_agent.py print       # show the plist, change nothing

The scheduler only runs while the app is open, so this is what makes
scheduled sessions happen after a reboot. It starts the app at login and
does not restart it if you quit.
"""

import plistlib
import subprocess
import sys
from pathlib import Path

LABEL = "com.dating-copilot.app"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
ROOT = Path(__file__).resolve().parent.parent


def build_plist(project_root: Path = ROOT) -> dict:
    log = Path.home() / ".dating-copilot" / "app.log"
    return {
        "Label": LABEL,
        "ProgramArguments": [str(project_root / "run.sh"), "app"],
        "WorkingDirectory": str(project_root),
        "RunAtLoad": True,
        "KeepAlive": False,
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
    }


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "print"
    if cmd == "print":
        sys.stdout.write(plistlib.dumps(build_plist()).decode())
    elif cmd == "install":
        PLIST.parent.mkdir(parents=True, exist_ok=True)
        (Path.home() / ".dating-copilot").mkdir(parents=True, exist_ok=True)
        PLIST.write_bytes(plistlib.dumps(build_plist()))
        subprocess.run(["launchctl", "unload", str(PLIST)], capture_output=True)
        subprocess.run(["launchctl", "load", str(PLIST)], check=True)
        print(f"Installed {PLIST}. The app will open at login.")
    elif cmd == "uninstall":
        subprocess.run(["launchctl", "unload", str(PLIST)], capture_output=True)
        PLIST.unlink(missing_ok=True)
        print("Removed the login agent.")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
