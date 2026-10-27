"""Offer to move the packaged Mac app into /Applications on first launch.

When the app is started from somewhere else (Downloads, a mounted disk image),
show a dialog: Move to Applications / Not Now / Don't Ask Again. "Move" copies
the app to /Applications, clears the download quarantine flag on the copy,
opens it from there and quits this instance. Pure Python (osascript, ditto,
xattr, open), no extra dependency. Does nothing outside a packaged macOS app.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import runlog

OPT_OUT_FILE = "no_move_prompt"
MOVE, LATER, NEVER = "Move to Applications", "Not Now", "Don't Ask Again"


def app_bundle_path() -> Path | None:
    """The running .app bundle, or None when not a packaged macOS app."""
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return None
    for parent in Path(sys.executable).parents:
        if parent.suffix == ".app":
            return parent
    return None


def in_applications(app: Path) -> bool:
    for folder in (Path("/Applications"), Path.home() / "Applications"):
        try:
            app.relative_to(folder)
            return True
        except ValueError:
            pass
    return False


def should_offer(app: Path | None) -> bool:
    if app is None:
        return False
    if os.environ.get("DATING_COPILOT_NO_MOVE_PROMPT") == "1":
        return False
    if (runlog.home() / OPT_OUT_FILE).exists():
        return False
    return not in_applications(app)


def _osascript(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["osascript", *args], capture_output=True, text=True)


def _dialog(text: str, buttons: list[str], default: str, icon: str = "note") -> str | None:
    """Show a dialog; return the pressed button, or None if it was dismissed."""
    btns = "{" + ", ".join(f'"{b}"' for b in buttons) + "}"
    script = (f'display dialog "{text}" with title "Dating Copilot" buttons {btns} '
              f'default button "{default}" with icon {icon}')
    r = _osascript("-e", script)
    if r.returncode != 0:
        return None
    marker = "button returned:"
    if marker not in r.stdout:
        return None
    return r.stdout.split(marker, 1)[1].split(",")[0].strip()


def ask_user() -> str | None:
    return _dialog("Dating Copilot works best from your Applications folder. "
                   "Move it there now?", [NEVER, LATER, MOVE], MOVE)


def _exists(path: Path) -> bool:
    return path.exists()


def _trash(app: Path):
    """Move the original to the Trash through Finder (best effort)."""
    try:
        _osascript("-e", "on run argv",
                   "-e", "tell application \"Finder\" to delete (POSIX file (item 1 of argv) as alias)",
                   "-e", "end run", str(app))
    except Exception:
        pass


def move_and_relaunch(app: Path) -> bool:
    """Copy to /Applications and open the copy. True when relaunched."""
    dest = Path("/Applications") / app.name
    try:
        if _exists(dest):
            answer = _dialog("Dating Copilot is already in Applications. Replace it "
                             "with this version?", ["Cancel", "Replace"], "Replace", "caution")
            if answer != "Replace":
                return False
            shutil.rmtree(dest)
        subprocess.run(["ditto", str(app), str(dest)], check=True, capture_output=True)
        # The user already chose to open this download; don't ask macOS again.
        subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(dest)],
                       capture_output=True)
        subprocess.Popen(["open", "-n", str(dest)])
    except Exception as e:
        _dialog(f"Could not move the app ({type(e).__name__}). It will keep running "
                "from where it is.", ["OK"], "OK", "stop")
        return False
    # Gatekeeper may run a download from a hidden read-only copy, and a disk
    # image is not ours to empty: only trash a normal original.
    if "/AppTranslocation/" not in str(app) and not str(app).startswith("/Volumes/"):
        _trash(app)
    return True


def maybe_offer_move() -> bool:
    """Ask once per launch when needed. True means a new copy was started and
    this process should quit."""
    app = app_bundle_path()
    if not should_offer(app):
        return False
    choice = ask_user()
    if choice == NEVER:
        try:
            runlog.home().mkdir(parents=True, exist_ok=True)
            (runlog.home() / OPT_OUT_FILE).write_text("1")
        except Exception:
            pass
        return False
    if choice == MOVE:
        return move_and_relaunch(app)
    return False
