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
# (the database is checked by the app itself, after the update)

exec "$PY" -m tempu.launch --port 5000
