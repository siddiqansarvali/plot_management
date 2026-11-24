@echo off
title AI Plot Layout Management
echo ===================================================
echo Starting AI Plot Layout Backend and Frontend...
echo ===================================================

cd /d "%~dp0backend"
start "AI Plot Layout Backend" cmd /k "py run.py"

cd /d "%~dp0frontend"
start "AI Plot Layout Frontend" cmd /k "npm run dev"

echo Waiting for servers to boot up...
timeout /t 3 /nobreak >nul

start http://localhost:5173/

echo ===================================================
echo All services launched!
echo Frontend: http://localhost:5173/
echo Backend:  http://localhost:8000/docs
echo Keep the command windows open while using the app.
echo ===================================================
