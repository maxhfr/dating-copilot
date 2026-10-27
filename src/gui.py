"""Open the control app in a native window (pywebview), or in the browser.

    python src/gui.py

Loads .env from the project folder before anything reads the environment.
"""

import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env():
    import runlog
    for f in (runlog.home() / ".env", ROOT / ".env"):
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


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


def main():
    import runlog
    import secrets_store
    if getattr(sys, "frozen", False):
        runlog.home().mkdir(parents=True, exist_ok=True)
        os.chdir(runlog.home())        # debug_nocard.* etc. land here
        import browser_setup
        browser_setup.use_standard_browsers_path()   # before any Playwright launch
        # A packaged app has no terminal: keep prints and errors in a file.
        sys.stdout = sys.stderr = open(runlog.home() / "app.log", "a", buffering=1)
    secrets_store.load_into_env()      # shell > keychain > .env
    load_env()
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
