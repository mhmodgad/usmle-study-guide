@echo off
REM Double-click to set up the app on a fresh Windows machine.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-windows.ps1"
echo.
pause
