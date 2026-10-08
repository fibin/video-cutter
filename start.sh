#!/usr/bin/env bash
# Запуск на macOS и Linux: ./start.sh
set -e
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  echo "Первый запуск: создаю окружение и ставлю зависимости (несколько минут)..."
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
  touch .venv/.installed
elif [ requirements.txt -nt .venv/.installed ]; then
  echo "Обновляю зависимости..."
  .venv/bin/python -m pip install -r requirements.txt
  touch .venv/.installed
fi

exec .venv/bin/python -m video_cutter "$@"
