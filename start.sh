#!/bin/bash
set -e

echo "======================================================="
echo " Cold Lead - Bootstrapper (Linux/macOS)"
echo "======================================================="

# 1. Check if virtual environment exists, create if not
if [ ! -d "venv" ] || [ ! -f "venv/bin/activate" ]; then
    echo "[1/3] Creating virtual environment..."
    python3 -m venv venv
fi

# 2. Activate venv & install dependencies
echo "[2/3] Activating venv and installing dependencies..."
source venv/bin/activate
pip install -r requirements.txt

# Install Playwright browsers if they don't exist
python -m playwright install --with-deps chromium

# 3. Start the server
echo "[3/3] Starting the Cold Lead server..."
echo ""
echo "======================================================="
echo " Server is running at: http://localhost:8000"
echo " Press Ctrl+C to stop the server"
echo "======================================================="

python -m uvicorn server:app --port 8000 --reload
