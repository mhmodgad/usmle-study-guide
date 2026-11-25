#!/usr/bin/env bash
# One-shot setup: venv, deps, CSS bundle, and database build.
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}
echo "==> Creating virtualenv (.venv)"
$PY -m venv .venv
. .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo "==> Building CSS bundle from the captured replica stylesheet"
python -m tempu.build_css

echo "==> Building the content database from ../content"
python -m tempu.loader

echo
echo "Done. Start the app with:"
echo "    . .venv/bin/activate && python -m tempu.app --port 5000"
echo "then open http://127.0.0.1:5000/"
