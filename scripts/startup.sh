#!/bin/bash
# =============================================================================
# REJANG CONSOLE - PRO STARTUP SCRIPT
# =============================================================================

# Get the directory where the script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# 1. Cleanup old processes
echo "[1/3] Cleaning up..."
sudo killall weston 2>/dev/null
sudo killall chromium-browser 2>/dev/null
sudo killall chromium 2>/dev/null
sudo killall python3 2>/dev/null
sleep 2

# 2. Setup Wayland Environment
export XDG_RUNTIME_DIR=/tmp/weston-runtime
mkdir -p $XDG_RUNTIME_DIR
chmod 700 $XDG_RUNTIME_DIR
export WAYLAND_DISPLAY=wayland-0

# 3. Start Weston Fresh
echo "[2/3] Starting Weston Compositor..."
cd "$SCRIPT_DIR"
# Force socket name to wayland-0
weston --backend=drm-backend.so --shell=kiosk-shell.so --socket=wayland-0 --config="$SCRIPT_DIR/weston.ini" > /tmp/weston.log 2>&1 &

# Wait for Wayland socket to appear (max 10 seconds)
echo "Waiting for Wayland socket..."
for i in {1..20}; do
    if [ -S "$XDG_RUNTIME_DIR/wayland-0" ]; then
        echo "✅ Wayland socket is ready!"
        break
    fi
    if [ $i -eq 20 ]; then
        echo "❌ ERROR: Weston failed to start. Check /tmp/weston.log"
        exit 1
    fi
    sleep 0.5
done

# 4. Start the Background API Server
# ... (rest of the script)
echo "[3/3] Starting Backend API Server..."
# Activate Virtual Environment if it exists
if [ -d "$REPO_DIR/venv" ]; then
    source "$REPO_DIR/venv/bin/activate"
    echo "✓ Virtual environment activated."
fi

cd "$REPO_DIR/app"
python3 main.py > "$SCRIPT_DIR/api.log" 2>&1 &

# Wait for API to be ready
echo "Waiting for API..."
for i in {1..15}; do
    if curl -s http://localhost:5000/api/ping > /dev/null; then
        echo "✅ API is up!"
        break
    fi
    sleep 1
done

# 5. Determine Browser Command
BROWSER_CMD="chromium-browser"
if ! command -v $BROWSER_CMD &> /dev/null; then
    BROWSER_CMD="chromium"
fi

# 6. Start Chromium in Kiosk Mode
if command -v $BROWSER_CMD &> /dev/null; then
    echo "🚀 Launching Local Touch UI using $BROWSER_CMD..."
    # We use a simplified command that works better on modern Debian/Ubuntu
    $BROWSER_CMD \
        --enable-features=UseOzonePlatform \
        --ozone-platform=wayland \
        --kiosk \
        --app=http://localhost:5000/csi \
        --no-first-run \
        --autoplay-policy=no-user-gesture-required-policy \
        --disable-features=TranslateUI &
else
    echo "❌ ERROR: Chromium not found. Please run: sudo apt install -y chromium-browser"
fi

echo "✨ System Ready."
wait