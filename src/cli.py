"""Run one swipe session from the command line (works on macOS and Windows).

    python src/cli.py [platform]

Loads the keychain and .env first, because main.py reads the API keys when it
is imported. On Windows it forces UTF-8 output so names with accents or emoji
don't crash the console.
"""

import asyncio
import sys


def run(argv: list[str]):
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    import envfile
    import secrets_store
    secrets_store.load_into_env()      # shell > keychain > .env
    envfile.load_env()
    import main
    platform = argv[1] if len(argv) > 1 else "tinder"
    return asyncio.run(main.run_session(platform))


if __name__ == "__main__":
    run(sys.argv)
