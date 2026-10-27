"""Where things live, for a source checkout and for a packaged app.

In a checkout everything is relative to the project folder. In a frozen app
(PyInstaller) the bundle is read-only, so the editable yaml config is copied
to ~/.dating-copilot/config on first launch and used from there.
"""

import shutil
import sys
from pathlib import Path

import runlog


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    if frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def config_dir() -> Path:
    if not frozen():
        return bundle_root() / "config"
    dest = runlog.home() / "config"
    dest.mkdir(parents=True, exist_ok=True)
    for src in (bundle_root() / "config").glob("*.yaml"):
        if not (dest / src.name).exists():
            shutil.copy(src, dest / src.name)
    return dest


def icon_png() -> Path:
    """The 1024px app icon (bundled under icon/ when frozen)."""
    sub = Path("icon") if frozen() else Path("packaging") / "icon"
    return bundle_root() / sub / "icon_1024.png"
