#!/usr/bin/env bash
# Sign, notarize and staple the macOS app (used by the GitHub Actions build).
#
#   packaging/sign_and_notarize_mac.sh "dist/Dating Copilot.app"
#
# The "Developer ID Application" certificate must already be in the keychain.
# Notarization runs when APPLE_ID, APPLE_APP_PASSWORD and APPLE_TEAM_ID are set.
# Failures are printed as GitHub "::error::" lines so they show up as
# annotations on the run.
set -euo pipefail

APP="${1:?usage: sign_and_notarize_mac.sh path/to/App.app}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ENTITLEMENTS="$HERE/mac_entitlements.plist"

IDENTITY="${SIGN_IDENTITY:-$(security find-identity -v -p codesigning | awk -F'"' '/Developer ID Application/ {print $2; exit}')}"
if [ -z "$IDENTITY" ]; then
  echo "::error title=Signing::No Developer ID Application certificate found in the keychain"
  exit 1
fi
echo "Signing as: $IDENTITY"

sign() {
  codesign --force --options runtime --timestamp \
    --entitlements "$ENTITLEMENTS" --sign "$IDENTITY" "$1"
}

# Every Mach-O file inside the app, deepest paths first, then the bundle itself.
find "$APP" -type f | awk '{ print length($0) "\t" $0 }' | sort -rn | cut -f2- |
while IFS= read -r f; do
  if file -b "$f" | grep -q "Mach-O"; then
    sign "$f"
  fi
done
sign "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"

if [ -z "${APPLE_ID:-}" ] || [ -z "${APPLE_APP_PASSWORD:-}" ] || [ -z "${APPLE_TEAM_ID:-}" ]; then
  echo "::warning title=Notarization::APPLE_ID / APPLE_APP_PASSWORD / APPLE_TEAM_ID not set: signed but NOT notarized"
  exit 0
fi

WORK="$(mktemp -d)"
ditto -c -k --keepParent "$APP" "$WORK/notarize.zip"
echo "Submitting to Apple for notarization (this can take a few minutes)..."
RESULT="$(xcrun notarytool submit "$WORK/notarize.zip" \
  --apple-id "$APPLE_ID" --password "$APPLE_APP_PASSWORD" --team-id "$APPLE_TEAM_ID" \
  --wait --output-format json || true)"
echo "$RESULT"
STATUS="$(printf '%s' "$RESULT" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("status",""))' 2>/dev/null || true)"
SUBMISSION="$(printf '%s' "$RESULT" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("id",""))' 2>/dev/null || true)"

if [ "$STATUS" != "Accepted" ]; then
  LOG=""
  if [ -n "$SUBMISSION" ]; then
    LOG="$(xcrun notarytool log "$SUBMISSION" --apple-id "$APPLE_ID" \
      --password "$APPLE_APP_PASSWORD" --team-id "$APPLE_TEAM_ID" 2>&1 | tr '\n' ' ' | head -c 1500 || true)"
  fi
  echo "::error title=Notarization failed::status=${STATUS:-unknown} ${LOG}"
  exit 1
fi

xcrun stapler staple "$APP"
xcrun stapler validate "$APP"
spctl --assess --type execute --verbose=4 "$APP"
echo "Signed, notarized and stapled."
