"""Load KEY=value lines from .env files into the environment (never overriding
a variable that is already set). Looks in ~/.dating-copilot/.env first, then
the project folder."""

import os
from pathlib import Path

import runlog

ROOT = Path(__file__).resolve().parent.parent


def load_env():
    for f in (runlog.home() / ".env", ROOT / ".env"):
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
