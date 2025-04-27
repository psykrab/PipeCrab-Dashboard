@echo off
title PipeCrab Dashboard Launcher
echo === PipeCrab Dashboard ===
echo.
echo [1] Production
echo [2] Development (--reload)
echo.

set /p mode=Choose mode (1 or 2):

if "%mode%"=="1" (
    echo Stopping any running instances...
    net stop fastapi-dashboard-dev >nul 2>&1
    net stop fastapi-dashboard >nul 2>&1
    echo Starting production server...
    python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
    goto end
)

if "%mode%"=="2" (
    echo Stopping any running instances...
    net stop fastapi-dashboard-dev >nul 2>&1
    net stop fastapi-dashboard >nul 2>&1
    echo Starting development server with --reload...
    python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    goto end
)

echo Invalid input.

:end
pause
