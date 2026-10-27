#!/usr/bin/env bash
# Build "Dating Copilot.app" (run this on the Mac you will use it on).
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m venv .build-venv
source .build-venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean packaging/dating-copilot.spec

cat <<'MSG'

Built: dist/Dating Copilot.app

It is unsigned (personal use). The first time, right-click the app and choose
Open, then confirm. If macOS still refuses:
    xattr -dr com.apple.quarantine "dist/Dating Copilot.app"
Move it to /Applications if you like. On first launch it downloads Chromium
(~190 MB). Config and your run log live in ~/.dating-copilot/.
MSG
