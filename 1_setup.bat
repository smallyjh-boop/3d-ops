@echo off
cd /d "%~dp0"
title 3D Ops - Setup
echo.
echo ===== Step 1/3: Find Python =====
set "PYCMD="

py -3 --version >nul 2>nul
if not errorlevel 1 set "PYCMD=py -3"
if defined PYCMD goto found

python --version >nul 2>nul
if not errorlevel 1 set "PYCMD=python"
if defined PYCMD goto found

for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do if exist "%%~D\python.exe" set PYCMD="%%~D\python.exe"
if defined PYCMD goto found
for /d %%D in ("%ProgramFiles%\Python3*") do if exist "%%~D\python.exe" set PYCMD="%%~D\python.exe"
if defined PYCMD goto found
for /d %%D in ("C:\Python3*") do if exist "%%~D\python.exe" set PYCMD="%%~D\python.exe"
if defined PYCMD goto found

echo.
echo [ERROR] Python not found on this computer.
echo Please install Python 3.12 from python.org - Downloads - Windows.
echo IMPORTANT: on the first installer screen, tick "Add python.exe to PATH".
echo Then double-click 1_setup.bat again.
echo.
pause
exit /b 1

:found
echo Using: %PYCMD%
%PYCMD% --version
%PYCMD% -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 goto tooold
echo Python version OK.
goto venv

:tooold
echo [ERROR] Python is too old. Need 3.10 or newer, 3.12 recommended.
pause
exit /b 1

:venv
echo.
echo ===== Step 2/3: Create environment .venv =====
if exist ".venv\Scripts\python.exe" goto install
%PYCMD% -m venv .venv
if errorlevel 1 goto venvfail
goto install

:venvfail
echo [ERROR] Could not create .venv - please send a screenshot of this window.
pause
exit /b 1

:install
echo.
echo ===== Step 3/3: Install packages =====
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto pipfail
echo.
echo ===== Environment check =====
".venv\Scripts\python.exe" check_env.py
echo.
echo DONE. From now on, double-click 2_start.bat to start.
pause
exit /b 0

:pipfail
echo [ERROR] Package install failed. Check internet and run again.
echo If it still fails, send a screenshot of this window.
pause
exit /b 1
