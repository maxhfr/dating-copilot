"""Open the control app in a native window (pywebview), or in the browser.

    python src/gui.py

Loads the keychain and .env before anything reads the environment.
`--check` imports every module and exits 0/1 (used by CI to smoke-test a build).
"""

import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def set_dock_icon():
    """Show the app icon in the Dock when running from source on macOS.
    (A packaged .app already carries it.) Best effort; never raises."""
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApplication, NSImage
        import paths
        img = NSImage.alloc().initWithContentsOfFile_(str(paths.icon_png()))
        if img is not None:
            NSApplication.sharedApplication().setApplicationIconImage_(img)
    except Exception:
        pass


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


CHECK_MODULES = ("judge", "main", "notifier", "runlog", "settings", "secrets_store",
                 "scheduler", "controller", "app", "paths", "browser_setup",
                 "keep_awake", "envfile", "cli", "platforms.base",
                 "platforms.tinder", "platforms.capture")


def check() -> int:
    """Import everything the app needs and verify the bundled files exist.
    Returns 0 when the build looks healthy, 1 otherwise."""
    import importlib
    import traceback
    import runlog
    try:
        os.environ.setdefault("ANTHROPIC_API_KEY", "check")
        for name in CHECK_MODULES:
            importlib.import_module(name)
        import app
        import paths
        assert (paths.config_dir() / "rubric.yaml").exists(), "rubric.yaml missing"
        assert (paths.config_dir() / "scoring.yaml").exists(), "scoring.yaml missing"
        assert paths.icon_png().exists(), "icon missing"
        assert app.PAGE.exists(), "ui.html missing"
        app.create_app()
        runlog.log_line("check ok")
        return 0
    except Exception:
        runlog.log_line("check FAILED:\n" + traceback.format_exc())
        traceback.print_exc()
        return 1


def main():
    if "--check" in sys.argv:
        return check()
    import runlog
    import secrets_store
    if getattr(sys, "frozen", False):
        runlog.home().mkdir(parents=True, exist_ok=True)
        os.chdir(runlog.home())        # debug_nocard.* etc. land here
        import browser_setup
        browser_setup.use_standard_browsers_path()   # before any Playwright launch
        # A packaged app has no terminal: keep prints and errors in a file.
        sys.stdout = sys.stderr = open(runlog.home() / "app.log", "a", buffering=1,
                                       encoding="utf-8", errors="replace")
    secrets_store.load_into_env()      # shell > keychain > .env
    import envfile
    envfile.load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set (put it in .env). Starting anyway; "
              "sessions will fail until it is.")
        os.environ["ANTHROPIC_API_KEY"] = "missing"   # judge reads it at import
    from app import create_app
    from controller import SessionController
    from scheduler import Schedule

    port = free_port()
    ctl = SessionController()
    schedule = Schedule(ctl)
    schedule.start()
    app = create_app(ctl, schedule)
    threading.Thread(target=lambda: app.run(host="127.0.0.1", port=port,
                                            debug=False, use_reloader=False),
                     daemon=True).start()
    url = f"http://127.0.0.1:{port}/"

    import browser_setup
    if not browser_setup.chromium_installed():
        threading.Thread(target=browser_setup.install_chromium,
                         kwargs={"on_status": ctl.messages.append},
                         daemon=True).start()

    try:
        try:
            import webview
            webview.create_window("Dating Copilot", url, width=1080, height=760,
                                  min_size=(760, 520))
            set_dock_icon()
            webview.start()
        except Exception as e:      # not installed, or no GUI toolkit
            print(f"No native window ({type(e).__name__}); opening {url} in "
                  "your browser. Press Ctrl+C here to quit.")
            webbrowser.open(url)
            try:
                threading.Event().wait()
            except KeyboardInterrupt:
                pass
    finally:
        schedule.shutdown()


if __name__ == "__main__":
    sys.exit(main())
