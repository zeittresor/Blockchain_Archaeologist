@echo off
setlocal
cd /d "%~dp0"
if not exist wheelhouse (
  echo [ERROR] wheelhouse directory not found. Build it on an online machine first.
  pause
  exit /b 1
)
where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
".venv\Scripts\python.exe" -m pip install --no-index --find-links=wheelhouse -r requirements.txt
if errorlevel 1 (
  echo [ERROR] Offline installation failed.
  pause
  exit /b 1
)
echo Offline installation completed.
timeout /t 10
if errorlevel 1 exit /b 0
call run.bat
