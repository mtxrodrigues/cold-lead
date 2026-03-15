@echo off
setlocal

echo =======================================================
echo  Cold Lead - Bootstrapper (Windows)
echo =======================================================

:: 1. Check if virtual environment exists, create if not
if not exist "venv\Scripts\activate.bat" (
    echo [1/3] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo Failed to create virtual environment! Make sure Python is installed.
        pause
        exit /b 1
    )
) else (
    echo [1/3] Virtual environment already exists.
)

:: 2. Activate venv & install dependencies
echo [2/3] Activating venv and installing dependencies...
call venv\Scripts\activate.bat
pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies!
    pause
    exit /b 1
)

:: Install Playwright browsers if they don't exist
python -m playwright install --with-deps chromium
if errorlevel 1 (
    echo Failed to install Playwright browsers!
    pause
    exit /b 1
)

:: 3. Start the server
echo [3/3] Starting the Cold Lead server...
echo.
echo =======================================================
echo  Server is running at: http://localhost:8000
echo  Press Ctrl+C to stop the server
echo =======================================================
python -m uvicorn server:app --port 8000 --reload

pause
