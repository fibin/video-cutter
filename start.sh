#!/usr/bin/env bash
# Start on macOS and Linux: ./start.sh
set -e
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  echo "First run: creating the environment and installing dependencies (a few minutes)..."
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
  touch .venv/.installed
elif [ requirements.txt -nt .venv/.installed ]; then
  echo "Updating dependencies..."
  .venv/bin/python -m pip install -r requirements.txt
  touch .venv/.installed
fi

exec .venv/bin/python -m video_cutter "$@"
