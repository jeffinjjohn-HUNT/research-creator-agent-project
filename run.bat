@echo off
rem One-click start for the AI Research & Creator Agent (Windows).
rem Double-click this file. It always runs from its own folder, so the folder name does not matter.
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
  echo First-time setup: creating the Python environment...
  python -m venv .venv
  if errorlevel 1 py -m venv .venv
  if not exist ".venv\Scripts\activate.bat" (
    echo.
    echo Could not create the environment. Is Python installed? Get it from python.org and tick "Add Python to PATH".
    pause
    exit /b 1
  )
)

call ".venv\Scripts\activate.bat"

pip show uvicorn >nul 2>&1
if errorlevel 1 (
  echo Installing packages. This can take a few minutes the first time...
  pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo Install failed. Check your internet connection and run this file again.
    pause
    exit /b 1
  )
)

rem Demo mode (fake data) unless you created a .env file for real research.
if not exist ".env" set USE_MOCK=1

echo.
echo Starting... your browser will open at http://localhost:8000
echo Keep this window open while you use the app. Close it (or press Ctrl+C) to stop.
echo.
start "" cmd /c "timeout /t 5 /nobreak >nul & start http://localhost:8000"
uvicorn apps.api.main:app_factory --factory

pause
