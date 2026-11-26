#!/usr/bin/env bash
# One-shot setup (Linux/macOS): venv, deps, optional CSS/DB build, git check.
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Python 3 not found. Install it first (e.g. sudo apt install python3 python3-venv) and re-run."
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "==> Creating virtual environment (.venv)"
  "$PY" -m venv .venv
fi
PYBIN=.venv/bin/python

echo "==> Installing dependencies (Flask)"
"$PYBIN" -m pip install -q --upgrade pip
"$PYBIN" -m pip install -q -r requirements.txt

if [ -d local/css ] && [ ! -f static/css/app.css ]; then
  echo "==> Building stylesheet"
  "$PYBIN" -m tempu.build_css
fi

if [ -f data/base.db ] || [ -f data/tempu.db ]; then
  # an old data/tempu.db is upgraded to base.db + user.db automatically on first start
  echo "==> Database already present - skipping build"
elif [ -d local/content ]; then
  echo "==> Building the library (data/base.db) from local/content"
  "$PYBIN" -m tempu.loader
else
  echo "==> [!] No database and no local/content found."
  echo "    Put your content under local/content/ (see local/README.md),"
  echo "    or copy a prebuilt data/ folder (base.db + user.db) into place, then re-run."
fi

if command -v rclone >/dev/null 2>&1; then
  echo "==> rclone found - cloud backup can be set up in Settings > Backup"
else
  echo "==> rclone not installed - cloud backup (optional) needs it."
  echo "    Install:  curl https://rclone.org/install.sh | sudo bash"
  echo "    Then:     rclone config create tempu-drive drive scope=drive.file"
  echo "    and turn backup on in Settings > Backup. The app works fine without it."
fi

if command -v git >/dev/null 2>&1; then
  echo "==> git found - the app will auto-update from the public repo on launch"
else
  echo "==> [!] git not installed - auto-update on launch is disabled (the app still works)."
  echo "    Install it (e.g. sudo apt install git) to enable updates."
fi

echo
echo "=================================================="
echo "  Setup complete. Start the app with:  ./run.sh"
echo "=================================================="
