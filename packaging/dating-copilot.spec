# PyInstaller spec for the Dating Copilot app.
#
#   pyinstaller --noconfirm --clean packaging/dating-copilot.spec
#
# One-folder build. On macOS this also produces "Dating Copilot.app".
# Playwright's Chromium is NOT bundled; the app downloads it on first launch.

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent

datas, binaries, hidden = [], [], []
for pkg in ("playwright", "webview", "keyring", "apscheduler", "anthropic",
            "certifi"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hidden += h

hidden += collect_submodules("keyring.backends")
# Imported lazily or by reload(), so the analysis can't see them.
hidden += ["judge", "main", "notifier", "runlog", "settings", "secrets_store",
           "scheduler", "controller", "app", "paths", "browser_setup",
           "platforms", "platforms.base", "platforms.tinder",
           "platforms.capture", "tzlocal", "yaml"]

datas += [(str(ROOT / "src" / "ui.html"), "."),
          (str(ROOT / "config"), "config"),
          (str(ROOT / "packaging" / "icon" / "icon_1024.png"), "icon")]

a = Analysis(
    [str(ROOT / "src" / "gui.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries, datas=datas, hiddenimports=hidden,
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
          name="dating-copilot", console=False if sys.platform == "darwin" else True)
coll = COLLECT(exe, a.binaries, a.datas, name="dating-copilot")

if sys.platform == "darwin":
    app = BUNDLE(coll, name="Dating Copilot.app",
                 icon=str(ROOT / "packaging" / "icon" / "icon.icns"),
                 bundle_identifier="com.dating-copilot.app",
                 info_plist={"NSHighResolutionCapable": True,
                             "CFBundleShortVersionString": "0.1.0"})
