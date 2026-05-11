#!/bin/bash

# --- WAYLAND ENVIRONMENT SETUP ---
# Wayland needs a 'runtime directory' to store its communication socket.
if [ -z "$XDG_RUNTIME_DIR" ]; then
    export XDG_RUNTIME_DIR=/run/user/$(id -u)
    # If the directory doesn't exist, create it in a temporary location
    if [ ! -d "$XDG_RUNTIME_DIR" ]; then
        export XDG_RUNTIME_DIR=/tmp/wayland-runtime
        mkdir -p $XDG_RUNTIME_DIR
        chmod 700 $XDG_RUNTIME_DIR
    fi
fi

export SDL_VIDEODRIVER=wayland
export WAYLAND_DISPLAY=wayland-0
export KIVY_WINDOW=wayland
export KIVY_GL_BACKEND=sdl2

# Start Weston if it's not already running
if ! pgrep -x "weston" > /dev/null; then
    echo "Starting Weston (Wayland Compositor)..."
    # We use --tty=1 to ensure it has a place to output if running from SSH
    weston --backend=drm-backend.so --shell=kiosk-shell.so --log=${XDG_RUNTIME_DIR}/weston.log &
    sleep 3
fi

# Run the Touch UI
echo "Starting Touch UI on Wayland..."
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
python3 "$DIR/touch_controls.py"
