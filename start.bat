@echo off
title PipeCrab Dashboard
echo === PipeCrab Dashboard Launcher ===
echo.
echo [1] Start in Production mode
echo [2] Start in Development mode (--reload)
echo.

set /p mode=Choose mode (1 or 2):

if "%mode%"=="1" (
    echo Starting production server...
    python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
    goto end
)

if "%mode%"=="2" (
    echo Starting development server with auto-reload...
    python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
    goto end
)

echo Invalid input.

:end
pause
