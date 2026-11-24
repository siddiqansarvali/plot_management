@echo off
title AI Plot Layout Management - Production Mode
echo ===================================================
echo   AI Plot Layout Management - Production Launcher
echo ===================================================

cd /d "%~dp0"

:: 1. Check if frontend production build exists
if not exist "frontend\dist\index.html" (
    echo [INFO] Frontend production build not found. Building now...
    cd /d "%~dp0frontend"
    call npm run build
    if errorlevel 1 (
        echo [ERROR] Frontend build failed. Please check dependencies with 'npm install'.
        pause
        exit /b 1
    )
    cd /d "%~dp0"
) else (
    echo [OK] Frontend production bundle verified at frontend\dist.
)

:: 2. Launch unified production backend (serves API + SPA + Exports on port 8000)
echo [INFO] Starting Unified Production Server on port 8000...
cd /d "%~dp0backend"
start "AI Plot Layout Production (Port 8000)" cmd /k "python run.py"

echo Waiting for server to initialize...
timeout /t 4 /nobreak >nul

start http://localhost:8000/

echo ===================================================
echo [SUCCESS] Application launched in Production Mode!
echo   Unified App URL: http://localhost:8000/
echo   API Docs:        http://localhost:8000/docs
echo   Health Check:    http://localhost:8000/health
echo ===================================================
