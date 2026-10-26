#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate
set -a; source .env; set +a
cd src
case "${1:-swipe}" in
  swipe) exec python main.py ;;
  *) echo "usage: run.sh [swipe]"; exit 1 ;;
esac
