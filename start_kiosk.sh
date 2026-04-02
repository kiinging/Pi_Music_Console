#!/usr/bin/env bash
# Pi Music Console – Kiosk Launcher
# This script starts the X server and then the Python GUI.

# 1. Clean up old X locks if they exist
rm -f /tmp/.X0-lock

# 2. Start the Python GUI through xinit
# -- :0  means use display 0
# vt7    means use virtual terminal 7
# -auth  points to the user's .Xauthority
echo "Starting Pi Music Console Kiosk..."
xinit /usr/bin/python3 "$(dirname "$0")/music_player.py" -- :0 vt7 -nolisten tcp
