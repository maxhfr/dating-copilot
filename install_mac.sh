#!/usr/bin/env bash
# Install or update Dating Copilot on a Mac from the latest GitHub release.
#
#   curl -fsSL https://raw.githubusercontent.com/maxhfr/dating-copilot/main/install_mac.sh | bash
#
# A file downloaded with curl is not flagged as "downloaded from the internet",
# so macOS does not show the "Apple could not verify..." warning. Your data
# (~/.dating-copilot, the keychain) is never touched; only the app itself is
# replaced.
#
# Optional: DATING_COPILOT_VERSION=v0.2.0 installs a specific release.
set -euo pipefail

REPO="maxhfr/dating-copilot"
ASSET="DatingCopilot-mac.zip"
APP_NAME="Dating Copilot.app"

if [ -n "${DATING_COPILOT_URL:-}" ]; then
  URL="$DATING_COPILOT_URL"                      # used by the tests
elif [ -n "${DATING_COPILOT_VERSION:-}" ]; then
  URL="https://github.com/$REPO/releases/download/$DATING_COPILOT_VERSION/$ASSET"
else
  URL="https://github.com/$REPO/releases/latest/download/$ASSET"
fi

if [ "$(uname -s)" != "Darwin" ]; then
  echo "This installer is for macOS only." >&2
  exit 1
fi
if [ "$(uname -m)" != "arm64" ]; then
  echo "Note: this build is made for Apple Silicon Macs (M1 or newer)." >&2
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Downloading Dating Copilot..."
curl -fL --progress-bar "$URL" -o "$TMP/app.zip"

echo "Unpacking..."
ditto -x -k "$TMP/app.zip" "$TMP/out"
if [ ! -d "$TMP/out/$APP_NAME" ]; then
  echo "The download does not contain $APP_NAME." >&2
  exit 1
fi

# Quit a running copy so it can be replaced.
osascript -e 'tell application "Dating Copilot" to quit' >/dev/null 2>&1 || true
sleep 1

if [ -w /Applications ]; then
  DEST_DIR="/Applications"
else
  DEST_DIR="$HOME/Applications"
  mkdir -p "$DEST_DIR"
fi
DEST="$DEST_DIR/$APP_NAME"

echo "Installing to $DEST ..."
rm -rf "$DEST"
ditto "$TMP/out/$APP_NAME" "$DEST"
xattr -dr com.apple.quarantine "$DEST" >/dev/null 2>&1 || true

echo "Done. Opening Dating Copilot."
open "$DEST"
