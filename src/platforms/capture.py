"""Opt-in capture of raw profile page text, for building parser fixtures.

Set CAPTURE=1 to enable. Files go to ~/.dating-copilot/captures/, outside
the repo, so they can't be committed. They contain other people's profile
text: keep them local, and blur names before using one as a fixture.
"""

import os
import time
from pathlib import Path

CAPTURE_DIR = Path.home() / ".dating-copilot" / "captures"


def save_capture(body: str):
    """Write the raw page text to a timestamped file. Never raises: a
    capture problem must not interrupt a swipe session."""
    if os.environ.get("CAPTURE") != "1":
        return
    try:
        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        # Timestamp only in the name, so profile names stay out of filenames.
        path = CAPTURE_DIR / f"profile-{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1000000:06d}.txt"
        path.write_text(body, encoding="utf-8")
        path.chmod(0o600)
    except Exception:
        pass
