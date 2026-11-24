@echo off
title AI Plot Layout Management - Web Deployment
echo ===================================================
echo     Publishing AI Plot Layout Management to Web
echo ===================================================

cd /d "%~dp0"

:: 1. Build frontend if dist is missing
if not exist "frontend\dist\index.html" (
    echo [INFO] Building frontend production bundle...
    cd /d "%~dp0frontend"
    call npm run build
    cd /d "%~dp0"
)

:: 2. Launch backend server in a separate background window
echo [INFO] Starting Backend on port 8000...
cd /d "%~dp0backend"
start "AI Plot Layout Backend" /min cmd /k "python run.py"

cd /d "%~dp0"
echo Waiting for backend to start...
timeout /t 3 /nobreak >nul

:: 3. Launch Cloudflare Tunnel
echo ===================================================
echo [INFO] Generating live public HTTPS link...
echo The public web address will appear below:
echo ===================================================
.\cloudflared.exe tunnel --url http://localhost:8000
