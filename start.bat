@echo off
rem Start on Windows: double-click start.bat
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo First run: creating the environment and installing dependencies, this takes a few minutes...
  py -3 -m venv .venv 2>nul || python -m venv .venv
  if errorlevel 1 (
    echo Python not found. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

".venv\Scripts\python.exe" -m video_cutter %*
pause
