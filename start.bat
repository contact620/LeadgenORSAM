@echo off
echo Starting ORSAM...
echo.

REM Start FastAPI backend in a new window
start "ORSAM API" cmd /k "python -m uvicorn api.server:app --reload --host 0.0.0.0 --port 8000"

REM Wait 2 seconds then start frontend
timeout /t 2 /nobreak >nul
start "ORSAM Frontend" cmd /k "cd frontend && npm run dev"

echo.
echo Backend:  http://localhost:8000
echo Frontend: http://localhost:5173
echo.
echo Close the two terminal windows to stop.
