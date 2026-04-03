#!/usr/bin/env bash

DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Starting Pi Music Console..."

cd "$DIR"

export DISPLAY=:0
export XAUTHORITY=/home/$USER/.Xauthority

/usr/bin/python3 music_player.py