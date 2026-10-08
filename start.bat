@echo off
rem Запуск на Windows: двойной щелчок по start.bat
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Первый запуск: создаю окружение и ставлю зависимости, это займёт несколько минут...
  py -3 -m venv .venv 2>nul || python -m venv .venv
  if errorlevel 1 (
    echo Не найден Python. Установите его с https://www.python.org/downloads/ и отметьте "Add python.exe to PATH".
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

".venv\Scripts\python.exe" -m video_cutter %*
pause
