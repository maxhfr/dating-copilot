"""Verify the setup before the first real run.

    python check_setup.py

Checks file layout, .env, dependencies, config validity, and that both
APIs actually answer. Does not touch Tinder.
"""

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent
ok, warn, fail = [], [], []

REQUIRED = [
    "requirements.txt",
    "config/rubric.yaml", "config/scoring.yaml",
    "config/persona.md", "config/date_rules.md", "config/openers.md",
    "src/__init__.py", "src/chat.py", "src/chat_loop.py", "src/judge.py",
    "src/gate.py", "src/main.py", "src/notifier.py", "src/style.py",
    "src/platforms/__init__.py", "src/platforms/tinder.py",
]


def check_files():
    for rel in REQUIRED:
        p = ROOT / rel
        if not p.exists():
            fail.append(f"missing: {rel}")
        elif p.stat().st_size == 0 and not rel.endswith("__init__.py"):
            fail.append(f"empty: {rel}")
        else:
            ok.append(rel)

    allowed_root = {"check_setup.py", "test_gate.py", "match_probe.py",
                    "thread_probe.py", "dom_probe.py"}
    stray = [f.name for f in ROOT.glob("*.py") if f.name not in allowed_root]
    if stray:
        fail.append(f"python files loose in root (should be in src/): {stray}")

    if not (ROOT / ".env").exists():
        fail.append("missing: .env")
    if (ROOT / ".gitignore").exists():
        if ".env" not in (ROOT / ".gitignore").read_text():
            fail.append(".gitignore does not exclude .env")
    else:
        warn.append("no .gitignore")


def check_env():
    env = {}
    envfile = ROOT / ".env"
    if envfile.exists():
        for line in envfile.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()

    for key in ["ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]:
        val = env.get(key, "")
        if not val:
            fail.append(f".env missing {key}")
        elif "xxx" in val.lower() or val.startswith("<"):
            fail.append(f".env {key} is still a placeholder")
        elif val.startswith('"') or val.startswith("'"):
            fail.append(f".env {key} has quotes around it — remove them")
        else:
            ok.append(f".env {key} set")

    if env.get("ANTHROPIC_API_KEY", "").strip() and \
            not env["ANTHROPIC_API_KEY"].startswith("sk-ant-"):
        warn.append("ANTHROPIC_API_KEY doesn't start with sk-ant-")

    os.environ.update(env)
    return env


def check_deps():
    for mod, pkg in [("anthropic", "anthropic"), ("playwright", "playwright"),
                     ("requests", "requests"), ("yaml", "PyYAML")]:
        if importlib.util.find_spec(mod) is None:
            fail.append(f"not installed: {pkg}  (pip install -r requirements.txt)")
        else:
            ok.append(f"installed: {pkg}")


def check_configs():
    try:
        import yaml
    except ImportError:
        return
    try:
        r = yaml.safe_load((ROOT / "config/rubric.yaml").read_text())
        assert r["age"]["min"] < r["age"]["max"]
        ok.append(f"rubric: age {r['age']['min']}-{r['age']['max']}, "
                  f"{r['distance_km_max']}km, "
                  f"height<{r['height']['max_cm_if_stated']}")
    except Exception as e:
        fail.append(f"rubric.yaml invalid: {e}")

    try:
        w = yaml.safe_load((ROOT / "config/scoring.yaml").read_text())
        photo = sum(w[k]["max"] for k in
                    ["body_type", "hair", "eyes", "photo_style",
                     "photo_variety", "filters"])
        text = sum(w[k]["max"] for k in
                   ["bio_effort", "shared_interests", "intent_fit"])
        if photo + text != 100:
            fail.append(f"scoring weights total {photo + text}, expected 100")
        else:
            ok.append(f"scoring: {photo} photo / {text} text, "
                      f"threshold {w['thresholds']['auto_like']}")
    except Exception as e:
        fail.append(f"scoring.yaml invalid: {e}")


def check_imports():
    sys.path.insert(0, str(ROOT / "src"))
    os.chdir(ROOT)
    for mod in ["style", "judge", "gate", "chat", "notifier"]:
        try:
            importlib.import_module(mod)
            ok.append(f"imports: {mod}")
        except Exception as e:
            fail.append(f"import {mod} failed: {type(e).__name__}: {e}")


def check_telegram():
    try:
        import requests
    except ImportError:
        return
    tok, cid = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not cid:
        return
    try:
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          data={"chat_id": cid,
                                "text": "setup check ok"}, timeout=15)
        if r.json().get("ok"):
            ok.append("telegram: message sent (check your phone)")
        else:
            fail.append(f"telegram: {r.json().get('description')}")
    except Exception as e:
        fail.append(f"telegram: {e}")


def check_anthropic():
    if importlib.util.find_spec("anthropic") is None:
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return
    try:
        from anthropic import Anthropic
        r = Anthropic().messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=10,
            messages=[{"role": "user", "content": "reply with: ok"}])
        ok.append(f"anthropic: responded ({r.usage.input_tokens} in / "
                  f"{r.usage.output_tokens} out)")
    except Exception as e:
        msg = str(e)
        if "credit balance" in msg or "billing" in msg.lower():
            fail.append("anthropic: no credit — add billing at console.anthropic.com")
        elif "authentication" in msg.lower() or "401" in msg:
            fail.append("anthropic: key rejected")
        else:
            fail.append(f"anthropic: {type(e).__name__}: {msg[:120]}")


def check_playwright():
    if importlib.util.find_spec("playwright") is None:
        return
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True)
            b.close()
        ok.append("playwright: chromium launches")
    except Exception as e:
        if "executable doesn't exist" in str(e).lower():
            fail.append("playwright: run  playwright install chromium")
        else:
            fail.append(f"playwright: {str(e)[:120]}")


if __name__ == "__main__":
    check_files()
    check_env()
    check_deps()
    check_configs()
    check_imports()
    check_playwright()
    check_telegram()
    check_anthropic()

    print()
    for m in ok:
        print(f"  \033[32mOK\033[0m    {m}")
    for m in warn:
        print(f"  \033[33mWARN\033[0m  {m}")
    for m in fail:
        print(f"  \033[31mFAIL\033[0m  {m}")

    print(f"\n  {len(ok)} ok, {len(warn)} warnings, {len(fail)} failures\n")
    if fail:
        print("  Fix the failures above, then run this again.\n")
    else:
        print("  Ready. Next: python src/main.py\n")
    sys.exit(1 if fail else 0)
