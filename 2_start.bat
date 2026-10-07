@echo off
cd /d "%~dp0"
title 3D Ops - close this window to quit
if exist ".venv\Scripts\python.exe" goto run
echo Not installed yet, running setup first...
call 1_setup.bat
if not exist ".venv\Scripts\python.exe" exit /b 1
:run
rem install new packages added by updates (skipped if already installed)
".venv\Scripts\python.exe" -c "import pypdf, numpy" 2>nul || ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
".venv\Scripts\python.exe" app.py
pause
