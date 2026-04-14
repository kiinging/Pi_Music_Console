#!/usr/bin/env bash

# Get the script directory
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_DIR"

echo "=== Pi Music Console Startup ==="

# 1. Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "Warning: venv not found. Using system python."
fi

# 2. Start Flask Dashboard in the background
echo "[1/2] Starting Web Dashboard (Port 5000)..."
python3 dashboards/dashboard_1.py > dashboard.log 2>&1 &

# 3. Start Touchscreen GUI
echo "[2/2] Starting Touchscreen GUI..."
export DISPLAY=:0
# Ensure XAUTHORITY is set for the current user
if [ -z "$XAUTHORITY" ]; then
    export XAUTHORITY="$HOME/.Xauthority"
fi

# Run the main GUI (this will block until closed)
python3 music_player.py