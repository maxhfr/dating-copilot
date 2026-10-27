"""Make sure Playwright's Chromium is present (it is not bundled in the app).

The packaged app downloads it on first launch (~190 MB, once).
"""

import os
import subprocess
import sys
from pathlib import Path


def browsers_dir() -> Path:
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env and env != "0":
        return Path(env)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    if sys.platform.startswith("win"):
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def chromium_installed() -> bool:
    d = browsers_dir()
    return d.exists() and any(d.glob("chromium-*"))


def install_command() -> list[str]:
    """Command that installs Chromium, for a checkout or a frozen app."""
    if not getattr(sys, "frozen", False):
        return [sys.executable, "-m", "playwright", "install", "chromium"]
    from playwright._impl._driver import compute_driver_executable
    drv = compute_driver_executable()
    parts = list(drv) if isinstance(drv, (tuple, list)) else [drv]
    return [str(p) for p in parts] + ["install", "chromium"]


def install_chromium(on_status=print) -> bool:
    if chromium_installed():
        return True
    on_status("Downloading the browser (first launch only, ~190 MB)...")
    try:
        env = dict(os.environ)
        if getattr(sys, "frozen", False):
            from playwright._impl._driver import get_driver_env
            env = {**env, **get_driver_env()}
        r = subprocess.run(install_command(), env=env, capture_output=True,
                           text=True, timeout=1800)
    except Exception as e:
        on_status(f"Browser download failed: {type(e).__name__}: {e}")
        return False
    if r.returncode != 0:
        on_status("Browser download failed: " + (r.stderr or r.stdout)[-300:])
        return False
    on_status("Browser ready.")
    return True
