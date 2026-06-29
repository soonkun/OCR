@echo off
REM ============================================================
REM  Gomunseo OCR - one-click launcher (Windows)
REM  ASCII-only on purpose: Korean text in a .bat gets mojibaked
REM  on CP949 consoles and breaks parsing. Keep this file ASCII.
REM ============================================================
cd /d "%~dp0"
title Gomunseo OCR

echo(
echo   Gomunseo OCR is starting...
echo(

REM 1) Stop any previous server still holding port 8000
for /f "tokens=5" %%p in ('netstat -ano ^| findstr "127.0.0.1:8000" ^| findstr LISTENING') do taskkill /F /PID %%p >nul 2>&1
ping -n 2 127.0.0.1 >nul

REM 2) First run only: create the virtual environment if missing
if not exist ".venv\Scripts\python.exe" (
  echo   First run: installing packages, this may take a few minutes...
  call setup.bat
)
if not exist ".venv\Scripts\python.exe" (
  echo   [ERROR] Setup failed. Please check the messages above.
  pause
  exit /b 1
)

REM 3) Start the server in its own window (close that window to stop)
REM  --no-access-log: hide the per-request access log spam (the page polls
REM  /api/documents every second to update the progress bar). Errors still show.
start "Gomunseo OCR Server" .venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --no-access-log

REM 4) Wait until the server answers, then open the browser
echo   Waiting for the server to be ready...
powershell -NoProfile -Command "for($i=0;$i -lt 60;$i++){ try{ if((Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8000/api/health' -TimeoutSec 2).StatusCode -eq 200){ exit 0 } }catch{}; Start-Sleep -Milliseconds 500 }; exit 1"
start "" "http://localhost:8000/app/"

echo(
echo   Ready. Browser opens at http://localhost:8000/app/
echo   (To stop: close the "Gomunseo OCR Server" window.)
ping -n 4 127.0.0.1 >nul
