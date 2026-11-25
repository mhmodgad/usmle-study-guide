@echo off
REM Double-click once to set up the app on a fresh Windows PC.
REM It installs Git and Python if they are missing, then the app's dependencies.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-windows.ps1"
if errorlevel 1 echo Setup did not finish - read the red messages above.
echo.
pause
