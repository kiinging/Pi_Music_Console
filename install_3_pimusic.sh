#!/usr/bin/env bash
# =============================================================================
# STEP 3 of 3 — Pi Music App as a Systemd Service
# =============================================================================
# This installs the pi-music.service now that auto-login (Step 1) and X server
# (Step 2) are confirmed working.
#
# Prerequisite:  Steps 1 and 2 must be working and stable.
#
# Run with:  sudo bash install_3_pimusic.sh
# =============================================================================
set -e

if [ "$EUID" -ne 0 ]; then
  echo "ERROR: Please run as root:  sudo bash install_3_pimusic.sh"
  exit 1
fi

USER_NAME="${SUDO_USER:-$(whoami)}"
if [ "$USER_NAME" == "root" ]; then
  echo "ERROR: Run with sudo from your normal user account, not as root directly."
  exit 1
fi

HOME_DIR=$(getent passwd "$USER_NAME" | cut -d: -f6)
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "=== STEP 3: Pi Music Service ==="
echo "User:  $USER_NAME"
echo "Home:  $HOME_DIR"
echo "Repo:  $REPO_DIR"
echo ""

# ── Install Python deps ───────────────────────────────────────────────────────
echo "[1/4] Installing audio packages..."
apt-get update -qq
apt-get install -y alsa-utils mpv ffmpeg python3-pip python3-venv python3-tk \
    python3-gpiozero python3-lgpio liblgpio-dev python3-evdev python3-smbus \
    i2c-tools git

echo "[2/4] Setting up Python virtual environment..."
cd "$REPO_DIR"
if [ ! -d "venv" ]; then
    sudo -u "$USER_NAME" python3 -m venv --system-site-packages venv
fi
sudo -u "$USER_NAME" bash -c "source '$REPO_DIR/venv/bin/activate' && pip install --upgrade pip --quiet"
if [ -f "requirements.txt" ]; then
    sudo -u "$USER_NAME" bash -c "source '$REPO_DIR/venv/bin/activate' && pip install -r requirements.txt --quiet"
fi

echo "[3/4] Fixing group permissions..."
groupadd -f gpio
usermod -a -G gpio,audio,video,input,render "$USER_NAME"
mkdir -p "$HOME_DIR/Music"
chown "$USER_NAME:$USER_NAME" "$HOME_DIR/Music"

echo "[4/4] Installing pi-music.service..."
SERVICE_FILE="/etc/systemd/system/pi-music.service"
cp "$REPO_DIR/pi-music.service" "$SERVICE_FILE"

# Replace placeholders with actual paths
sed -i "s|/home/pizza|$HOME_DIR|g"   "$SERVICE_FILE"
sed -i "s|User=pizza|User=$USER_NAME|g"   "$SERVICE_FILE"
sed -i "s|Group=pizza|Group=$USER_NAME|g" "$SERVICE_FILE"

systemctl daemon-reload
systemctl enable pi-music.service

echo ""
echo "✓ Done! pi-music.service installed and enabled."
echo ""
echo "Next steps:"
echo "  sudo reboot"
echo "  Check status:  sudo systemctl status pi-music"
echo "  Watch logs:    sudo journalctl -u pi-music -f"
echo ""
