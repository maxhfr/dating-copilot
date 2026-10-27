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
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    import secrets_store
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
    try:
        import webview
        webview.create_window("Dating Copilot", url, width=980, height=720)
        webview.start()
    except ImportError:
        print(f"pywebview not installed; opening {url} in your browser. "
              "Press Ctrl+C here to quit.")
        webbrowser.open(url)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
    finally:
        schedule.shutdown()


if __name__ == "__main__":
    sys.exit(main())
