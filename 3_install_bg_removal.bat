@echo off
cd /d "%~dp0"
title Install background removal - optional
if not exist ".venv\Scripts\python.exe" goto nosetup
echo Installing rembg, about 200MB, please wait a few minutes...
".venv\Scripts\python.exe" -m pip install "rembg[cpu]"
if errorlevel 1 goto fail
echo.
echo DONE. The first background removal will download a model file, about 170MB.
pause
exit /b 0
:nosetup
echo Please run 1_setup.bat first.
pause
exit /b 1
:fail
echo [ERROR] Install failed - please send a screenshot of this window.
pause
exit /b 1
