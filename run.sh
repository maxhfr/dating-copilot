#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate
set -a; source .env; set +a
case "${1:-swipe}" in
  swipe) exec python src/main.py "${2:-tinder}" ;;
  *) echo "usage: run.sh [swipe [platform]]"; exit 1 ;;
esac
