#!/usr/bin/env bash
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="$(whoami)"
HOME_DIR="/home/$USER_NAME"

echo ""
echo "=== Pi Music Console Dependency Installer ==="
echo "Repo: $REPO_DIR"
echo "User: $USER_NAME"
echo ""

echo "[1/4] Installing system packages..."

sudo apt update
sudo apt install -y \
    alsa-utils \
    mpv \
    ffmpeg \
    git \
    i2c-tools \
    python3-pip \
    python3-venv \
    python3-tk \
    python3-gpiozero \
    python3-lgpio \
    liblgpio-dev \
    python3-evdev \
    python3-smbus

echo "[2/4] Creating Python virtual environment..."

cd "$REPO_DIR"

if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

source venv/bin/activate
pip install --upgrade pip

if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
fi

deactivate

echo "[3/4] Configuring hardware permissions..."

sudo groupadd -f gpio
sudo usermod -a -G gpio,audio,video,input,render "$USER_NAME"

echo "[4/4] Done!"

echo ""
echo "Reboot required:"
echo "sudo reboot"
echo ""