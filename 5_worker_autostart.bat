@echo off
cd /d "%~dp0"
title 3D Ops - accelerator auto start
set "S=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\3dops_accelerator.bat"
if exist "%S%" goto remove
> "%S%" echo @echo off
>> "%S%" echo start "3D Ops accelerator" /min "%~dp04_start_worker.bat"
echo.
echo DONE. The PC accelerator will start automatically (minimized) when Windows starts.
echo Run this file again to turn auto start OFF.
pause
exit /b 0
:remove
del "%S%"
echo.
echo Auto start is now OFF. Run this file again to turn it back ON.
pause
exit /b 0
