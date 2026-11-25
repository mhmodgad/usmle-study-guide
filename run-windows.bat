@echo off
REM Double-click to start the app. It opens http://127.0.0.1:5000/ in your browser.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please run setup-windows.bat first.
  pause
  exit /b 1
)
if not exist "data\tempu.db" (
  echo No database found. Run setup-windows.bat first ^(or copy data\tempu.db into the data folder^).
  pause
  exit /b 1
)
echo Starting the USMLE Study Guide at http://127.0.0.1:5000/  ^(press Ctrl+C to stop^)
start "" http://127.0.0.1:5000/
".venv\Scripts\python.exe" -m tempu.app --port 5000
pause
