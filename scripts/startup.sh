#!/bin/bash
# =============================================================================
# REJANG CONSOLE - PRO STARTUP SCRIPT
# =============================================================================

# Get the directory where the script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# 1. Cleanup & Signal Handling
echo "[1/3] Cleaning up..."
# Trap Ctrl+C (SIGINT) and SIGTERM to kill background processes
trap "echo -e '\n🛑 Stopping Rejang Console...'; sudo killall python3 chromium chromium-browser weston 2>/dev/null; exit" INT TERM

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

# Force Backlight ON (DSI/CSI Screen)
echo "Setting backlight to ON..."
for p in /sys/class/backlight/*/bl_power; do
    if [ -f "$p" ]; then sudo sh -c "echo 0 > $p"; fi
done

# 3. Start Weston Fresh
echo "[2/3] Starting Weston Compositor..."
cd "$SCRIPT_DIR"
# Force socket name to wayland-0
weston --backend=drm-backend.so --shell=desktop-shell.so --socket=wayland-0 --drm-device=card0 --config="$SCRIPT_DIR/weston.ini" > /tmp/weston.log 2>&1 &

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
BROWSER_CMD="chromium"

# 6. Start Chromium in Kiosk Mode
if command -v $BROWSER_CMD &> /dev/null; then
    echo "🚀 Launching Local Touch UI using $BROWSER_CMD..."
    # We use a simplified command that works better on modern Debian/Ubuntu
    /usr/bin/chromium \
        --enable-features=UseOzonePlatform \
        --ozone-platform=wayland \
        --no-sandbox \
        --user-data-dir=/tmp/chromium-data-$(date +%s) \
        --kiosk \
        --app="http://127.0.0.1:5000/csi?cachebust=$(date +%s)" \
        --no-first-run \
        --disable-infobars \
        --disable-session-crashed-bubble > /tmp/chromium.log 2>&1 &
else
    echo "❌ ERROR: Chromium not found. Please run: sudo apt install -y chromium-browser"
fi

echo "✨ System Ready."
exit 0