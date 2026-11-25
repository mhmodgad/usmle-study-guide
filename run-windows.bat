@echo off

REM Double-click to start the app (Windows).

REM It checks GitHub for updates first (public repo - no account, login or SSH key

REM needed; offline just uses the current version), then opens

REM http://127.0.0.1:5000/ in your browser.

REM The whole script is wrapped in one block so cmd reads it fully before the

REM update runs; otherwise an update that rewrites this file mid-run could break it.

(

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

  ".venv\Scripts\python.exe" -m tempu.launch --port 5000

  pause

  exit /b 0

)

