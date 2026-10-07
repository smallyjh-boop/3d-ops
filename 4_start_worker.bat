@echo off
cd /d "%~dp0"
title 3D Ops - PC accelerator - keep this window open
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
if exist ".venv\Scripts\python.exe" goto check
echo Not installed yet, running setup first...
call 1_setup.bat
if not exist ".venv\Scripts\python.exe" exit /b 1
:check
".venv\Scripts\python.exe" -c "import numpy, requests, PIL" 2>nul || ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
:loop
".venv\Scripts\python.exe" worker.py
if errorlevel 3 if not errorlevel 4 goto updated
if errorlevel 2 if not errorlevel 3 goto nosetup
echo.
echo Accelerator stopped. Restarting in 10 seconds - close this window to quit.
timeout /t 10 /nobreak >nul
goto loop
:updated
echo Updated from NAS, restarting...
timeout /t 2 /nobreak >nul
goto loop
:nosetup
pause
exit /b 2
