@echo off
echo Starting Antigravity Development Environment...

:: Set current directory to the script's directory
cd /d %~dp0

:: 1. Start Backend
echo Starting Backend Server...
start "Antigravity Backend" cmd /k "cd backend & venv\Scripts\activate & python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000"

:: 2. Start Frontend
echo Starting Frontend Server...
start "Antigravity Frontend" cmd /k "cd frontend & npm run dev"

:: 3. Wait a bit for servers to spin up then open browser
timeout /t 5 >nul
start http://localhost:5173

echo Environment started!
