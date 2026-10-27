"""Open the app automatically at login.

    python packaging/launch_agent.py install     # writes (and on macOS loads) the agent
    python packaging/launch_agent.py uninstall
    python packaging/launch_agent.py print       # show what would be written, change nothing

macOS: a launchd agent. Windows: a small .cmd in your Startup folder (pass
--exe "C:\\path\\dating-copilot.exe" to start the packaged app instead of run.bat).

The scheduler only runs while the app is open, so this is what makes
scheduled sessions happen after a reboot. It starts the app at login and
does not restart it if you quit.
"""

import os
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


def startup_cmd_path() -> Path:
    appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    return (Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            / "Startup" / "Dating Copilot.cmd")


def build_startup_cmd(project_root: Path = ROOT, exe: str | None = None) -> str:
    """Contents of the Windows Startup-folder script."""
    if exe:
        target = f'start "" "{exe}"'
    else:
        target = f'start "" /min "{project_root}\\run.bat" app'
    return f'@echo off\r\ncd /d "{project_root}"\r\n{target}\r\n'


def _windows(cmd: str, argv) -> int:
    exe = argv[argv.index("--exe") + 1] if "--exe" in argv else None
    if cmd == "print":
        sys.stdout.write(build_startup_cmd(exe=exe))
    elif cmd == "install":
        p = startup_cmd_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(build_startup_cmd(exe=exe), encoding="utf-8")
        print(f"Installed {p}. The app will open at login.")
    elif cmd == "uninstall":
        startup_cmd_path().unlink(missing_ok=True)
        print("Removed the login script.")
    else:
        print(__doc__)
        return 1
    return 0


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "print"
    if sys.platform == "win32":
        return _windows(cmd, argv)
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
