@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not exist "app_data\logs" mkdir "app_data\logs"
set "LOG=app_data\logs\install_%DATE:~-4%%DATE:~3,2%%DATE:~0,2%_%TIME:~0,2%%TIME:~3,2%%TIME:~6,2%.log"
set "LOG=%LOG: =0%"
for /F "delims=" %%e in ('echo prompt $E^| cmd') do set "ESC=%%e"
set "C_INFO=%ESC%[96m"
set "C_OK=%ESC%[92m"
set "C_WARN=%ESC%[93m"
set "C_ERR=%ESC%[91m"
set "C_RESET=%ESC%[0m"

echo %C_INFO%Blockchain Archaeologist v0.1.0 - local installer%C_RESET%
echo Log: %LOG%
echo [%DATE% %TIME%] Installer started > "%LOG%"

where py >nul 2>nul
if errorlevel 1 (
  where python >nul 2>nul
  if errorlevel 1 (
    echo %C_ERR%[ERROR] Python 3.10+ was not found.%C_RESET%
    echo [ERROR] Python not found. >> "%LOG%"
    pause
    exit /b 1
  )
  set "PY=python"
) else (
  set "PY=py -3"
)

if not exist ".venv\Scripts\python.exe" (
  echo %C_INFO%[1/3] Creating project-local virtual environment...%C_RESET%
  %PY% -m venv .venv >> "%LOG%" 2>&1
  if errorlevel 1 goto :fail
) else (
  echo %C_OK%[1/3] Existing project-local virtual environment detected.%C_RESET%
)

echo %C_INFO%[2/3] Updating packaging tools...%C_RESET%
".venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

echo %C_INFO%[3/3] Installing application dependencies...%C_RESET%
".venv\Scripts\python.exe" -m pip install -r requirements.txt >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

echo %C_OK%Installation completed successfully.%C_RESET%
echo [%DATE% %TIME%] Installation completed. >> "%LOG%"
echo The application will start in 10 seconds. Press Ctrl+C to abort.
timeout /t 10
if errorlevel 1 exit /b 0
call run.bat
exit /b 0

:fail
echo %C_ERR%[ERROR] Installation failed. Review: %LOG%%C_RESET%
echo [%DATE% %TIME%] Installation failed. >> "%LOG%"
pause
exit /b 1
