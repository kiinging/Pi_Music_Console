#!/bin/bash

# 1. Clean up
sudo killall weston 2>/dev/null
sleep 1

# 2. Setup Runtime Dir
if [ -z "$XDG_RUNTIME_DIR" ]; then
    export XDG_RUNTIME_DIR=/run/user/$(id -u)
    if [ ! -d "$XDG_RUNTIME_DIR" ]; then
        export XDG_RUNTIME_DIR=/tmp/wayland-runtime
        mkdir -p $XDG_RUNTIME_DIR
        chmod 700 $XDG_RUNTIME_DIR
    fi
fi

# 3. Start Weston Fresh
echo "Starting Fresh Weston..."
weston --backend=drm-backend.so --shell=kiosk-shell.so --log=${XDG_RUNTIME_DIR}/weston.log &
sleep 4

# 4. Diagnostics
echo "Checking for Wayland socket..."
ls -l $XDG_RUNTIME_DIR/wayland-0

# 5. Run Minimal App
export SDL_VIDEODRIVER=wayland
export WAYLAND_DISPLAY=wayland-0
export KIVY_WINDOW=wayland

echo "Starting Minimal Test App..."
python3 test_gui.py
