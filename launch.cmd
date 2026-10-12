@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Set up the environment first. See README.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m mokka_ecu_lab
if errorlevel 1 pause
