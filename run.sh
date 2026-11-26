#!/usr/bin/env bash
# Double-clickable equivalent: run the app (Linux/macOS).
# Self-updates from the public repo first (best effort, needs no account),
# then starts the server and opens the browser.
set -euo pipefail
cd "$(dirname "$0")"

PY=".venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "No virtual environment found. Run ./setup.sh first."
  exit 1
fi
if [ ! -f data/base.db ] && [ ! -f data/tempu.db ]; then
  echo "No database found. Run ./setup.sh first (or copy your data/ folder into place)."
  exit 1
fi

exec "$PY" -m tempu.launch --port 5000
