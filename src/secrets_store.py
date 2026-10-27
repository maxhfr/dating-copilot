"""API keys in the OS keychain (macOS Keychain via `keyring`).

Precedence when the app starts: a variable already set in the shell wins,
then the keychain, then .env. Values are never returned by the web API and
never printed.
"""

import os
import re

SERVICE = "dating-copilot"
NAMES = ("ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")

_PATTERNS = {
    "ANTHROPIC_API_KEY": (r"sk-ant-[A-Za-z0-9_\-]{20,}", "should look like sk-ant-..."),
    "TELEGRAM_BOT_TOKEN": (r"\d{6,}:[A-Za-z0-9_\-]{20,}", "should look like 123456:ABC..."),
    "TELEGRAM_CHAT_ID": (r"-?\d{5,}", "should be a number"),
}


def _keyring():
    try:
        import keyring
        from keyring.backends import fail
        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
        return keyring
    except Exception:
        return None


def available() -> bool:
    return _keyring() is not None


def get(name: str) -> str | None:
    kr = _keyring()
    if kr is None or name not in NAMES:
        return None
    try:
        return kr.get_password(SERVICE, name)
    except Exception:
        return None


def validate(name: str, value: str) -> str | None:
    """Return an error message, or None if the value looks right."""
    if name not in NAMES:
        return "unknown secret"
    pattern, hint = _PATTERNS[name]
    if not re.fullmatch(pattern, value):
        return f"{name} {hint} (no spaces or quotes)"
    return None


def set(name: str, value: str) -> str | None:
    """Store a secret. Returns an error message, or None on success."""
    value = value.strip()
    err = validate(name, value)
    if err:
        return err
    kr = _keyring()
    if kr is None:
        return "no keychain available on this system; put it in .env instead"
    try:
        kr.set_password(SERVICE, name, value)
    except Exception as e:
        return f"keychain refused: {type(e).__name__}"
    os.environ[name] = value
    return None


def delete(name: str) -> str | None:
    kr = _keyring()
    if kr is None or name not in NAMES:
        return "no keychain available"
    try:
        kr.delete_password(SERVICE, name)
    except Exception:
        pass                      # already absent
    os.environ.pop(name, None)
    return None


def load_into_env():
    """Fill any name not already set in the environment from the keychain."""
    for name in NAMES:
        if not os.environ.get(name):
            v = get(name)
            if v:
                os.environ[name] = v
