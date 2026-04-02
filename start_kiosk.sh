#!/usr/bin/env bash
# Pi Music Console – GUI Launcher
# Optimized for Raspberry Pi OS (Pi 5)

# Get the directory of this script
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Starting Pi Music Console..."

# Ensure we are in the right directory
cd "$DIR"

# Launch the Python app
# On Raspberry Pi OS Desktop, the GUI environment is already active.
/usr/bin/python3 music_player.py
