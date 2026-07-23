#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo "Local .venv missing. Create it and install requirements.txt first." >&2
  exit 1
fi
exec .venv/bin/python app.py
