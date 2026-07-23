@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Local virtual environment not found.
  echo Run install_windows.bat or install_offline.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" app.py
endlocal
