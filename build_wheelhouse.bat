@echo off
setlocal
cd /d "%~dp0"
if not exist "app_data\logs" mkdir "app_data\logs"
set "LOG=app_data\logs\wheelhouse_build.log"
where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
".venv\Scripts\python.exe" -m pip install --upgrade pip >> "%LOG%" 2>&1
if not exist wheelhouse mkdir wheelhouse
".venv\Scripts\python.exe" -m pip download -r requirements.txt -d wheelhouse >> "%LOG%" 2>&1
if errorlevel 1 (
  echo Wheelhouse build failed. See %LOG%
  pause
  exit /b 1
)
echo Wheelhouse ready in .\wheelhouse
pause
