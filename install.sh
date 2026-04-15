#!/usr/bin/env bash
set -e

# Detect the real user even if run with sudo
if [ "$EUID" -ne 0 ]; then
  echo "ERROR: Please run as root (use: sudo bash install.sh)"
  exit 1
fi

USER_NAME="${SUDO_USER:-$(whoami)}"
if [ "$USER_NAME" == "root" ]; then
    echo "ERROR: You are running as root directly. Please run as your normal user with sudo."
    exit 1
fi

HOME_DIR=$(getent passwd "$USER_NAME" | cut -d: -f6)
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

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
    python3-smbus \
    xorg \
    openbox \
    xinit \
    x11-xserver-utils

echo "[2/4] Creating Python virtual environment..."

cd "$REPO_DIR"

if [ ! -d "venv" ]; then
    python3 -m venv --system-site-packages venv
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

mkdir -p "$HOME_DIR/Music"

echo "[4/4] Installing systemd service..."

SERVICE_FILE="/etc/systemd/system/pi-music.service"
sudo cp "$REPO_DIR/pi-music.service" "$SERVICE_FILE"

# Replace placeholders with actual user and paths
sudo sed -i "s|/home/pizza|$HOME_DIR|g" "$SERVICE_FILE"
sudo sed -i "s|User=pizza|User=$USER_NAME|g" "$SERVICE_FILE"
sudo sed -i "s|Group=pizza|Group=$USER_NAME|g" "$SERVICE_FILE"

sudo systemctl daemon-reload
sudo systemctl enable pi-music.service

echo "[4/4] Done! Service installed and enabled."

echo ""
echo "Reboot required:"
echo "sudo reboot"
echo ""