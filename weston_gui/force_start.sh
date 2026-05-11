#!/bin/bash

# 1. Kill everything first to be sure
echo "Cleaning up old sessions and services..."
sudo systemctl stop pi-music.service 2>/dev/null
sudo killall -9 weston 2>/dev/null
sudo killall -9 mpv 2>/dev/null
sudo killall -9 labwc 2>/dev/null
sudo killall -9 wayfire 2>/dev/null
# Force kill anything on port 5000 (Flask)
sudo fuser -k 5000/tcp 2>/dev/null
sleep 2

# 2. Setup a clean Runtime Directory
export XDG_RUNTIME_DIR=/tmp/weston-runtime
echo "Setting up $XDG_RUNTIME_DIR..."
# If it exists and is owned by root, we need sudo to remove it
if [ -d "$XDG_RUNTIME_DIR" ]; then
    sudo rm -rf $XDG_RUNTIME_DIR
fi
mkdir -p $XDG_RUNTIME_DIR
chmod 700 $XDG_RUNTIME_DIR

# 3. Activate virtual environment if it exists
echo "Checking environment..."
cd "$(dirname "$0")"
if [ -d "../venv" ]; then
    source ../venv/bin/activate
    PYTHON_EXEC="python3"
elif [ -d "venv" ]; then
    source venv/bin/activate
    PYTHON_EXEC="python3"
else
    PYTHON_EXEC="python3"
fi

# 4. Start Weston Fresh
echo "[1/3] Starting Weston (Kiosk Mode)..."
CONFIG_PATH="$(pwd)/weston.ini"

# Start weston
weston --backend=drm-backend.so --shell=kiosk-shell.so --config="$CONFIG_PATH" --socket=wayland-0 --drm-device=card0 > $XDG_RUNTIME_DIR/weston.log 2>&1 &
sleep 5

# 5. Check if the socket was actually created
if [ -S "$XDG_RUNTIME_DIR/wayland-0" ]; then
    echo "✅ Wayland socket found at $XDG_RUNTIME_DIR/wayland-0"
else
    echo "❌ ERROR: Weston failed to start correctly."
    echo "--- Weston Log Content ---"
    cat $XDG_RUNTIME_DIR/weston.log
    echo "--------------------------"
    exit 1
fi

# 6. Start the Background API Server
echo "[2/3] Starting Background API Server..."
(cd ../dashboards && $PYTHON_EXEC dashboard_1.py > ../weston_gui/api.log 2>&1) &

# Wait for API to be ready (max 15 seconds)
echo "Waiting for API to respond..."
for i in {1..15}; do
    if curl -s http://localhost:5000/api/ping > /dev/null; then
        echo "✅ API is up!"
        break
    fi
    if [ $i -eq 15 ]; then
        echo "❌ ERROR: API failed to start. Check weston_gui/api.log"
        exit 1
    fi
    sleep 1
done

# 7. Run Kivy with Wayland settings
export WAYLAND_DISPLAY=wayland-0
export SDL_VIDEODRIVER=wayland
export KIVY_WINDOW=sdl2
export KIVY_GL_BACKEND=sdl2

echo "[3/3] Starting Touch UI..."
python3 touch_controls.py
