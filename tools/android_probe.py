"""Look at what is on a USB-connected Android phone's screen, read only.

    python tools/android_probe.py [label]

Takes a screenshot and a UI dump of whatever app is open, and writes them to
~/.dating-copilot/captures/android/. It never taps, swipes, types or installs
anything: only `adb devices`, `screencap`, `uiautomator dump` and `getprop`.
Needs `adb` (Android platform-tools) and USB debugging turned on.

Use it to see what a dating app shows (cards, popups, limits) before any
automation is written against it.
"""

import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

OUT_DIR = Path.home() / ".dating-copilot" / "captures" / "android"


def parse_ui_dump(xml_text: str) -> list[dict]:
    """The nodes of a `uiautomator dump` that show something to the user:
    text, content description, resource id, bounds, clickable."""
    end = xml_text.find("</hierarchy>")
    if end != -1:
        xml_text = xml_text[:end + len("</hierarchy>")]   # drop adb's trailer
    start = xml_text.find("<?xml")
    if start == -1:
        start = xml_text.find("<hierarchy")
    if start == -1:
        return []
    root = ET.fromstring(xml_text[start:])
    nodes = []
    for n in root.iter("node"):
        text = (n.get("text") or "").strip()
        desc = (n.get("content-desc") or "").strip()
        if not (text or desc):
            continue
        nodes.append({
            "text": text, "desc": desc,
            "id": n.get("resource-id") or "",
            "bounds": n.get("bounds") or "",
            "clickable": n.get("clickable") == "true",
        })
    return nodes


def _adb(*args: str, binary: bool = False, timeout: int = 30):
    r = subprocess.run(["adb", *args], capture_output=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode(errors="replace").strip()
                           or f"adb {' '.join(args)} failed")
    return r.stdout if binary else r.stdout.decode(errors="replace")


def connected_devices() -> list[str]:
    out = _adb("devices")
    return [line.split("\t")[0] for line in out.splitlines()[1:]
            if line.strip().endswith("\tdevice")]


def main(label: str = "screen") -> int:
    try:
        devices = connected_devices()
    except FileNotFoundError:
        print("adb not found. Install Android platform-tools and retry.")
        return 1
    if not devices:
        print("No authorised phone found. Plug it in, enable USB debugging, "
              "accept the prompt on the phone, then retry.")
        return 1
    if len(devices) > 1:
        print(f"{len(devices)} devices connected; unplug all but one.")
        return 1

    model = _adb("shell", "getprop", "ro.product.model").strip()
    android = _adb("shell", "getprop", "ro.build.version.release").strip()
    print(f"Phone: {model} (Android {android})")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", label) or "screen"
    stem = OUT_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{safe}"

    stem.with_suffix(".png").write_bytes(
        _adb("exec-out", "screencap", "-p", binary=True))
    dump = _adb("exec-out", "uiautomator", "dump", "/dev/tty")
    stem.with_suffix(".xml").write_text(dump, encoding="utf-8")

    nodes = parse_ui_dump(dump)
    lines = [f"{n['text'] or n['desc']}"
             + (f"   [{n['id']}]" if n["id"] else "")
             + ("   (clickable)" if n["clickable"] else "")
             for n in nodes]
    stem.with_suffix(".txt").write_text("\n".join(lines), encoding="utf-8")

    print(f"Saved {stem.name}.png / .xml / .txt in {OUT_DIR}")
    print(f"{len(nodes)} visible texts on screen:")
    for line in lines[:40]:
        print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "screen"))
