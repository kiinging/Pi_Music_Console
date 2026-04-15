#!/usr/bin/env bash
# =============================================================================
# Pi Music Console — Full Installer
# =============================================================================
# Installs all dependencies and the pi-music systemd service.
# No X server. No display manager. mpv plays directly to HDMI via KMS/DRM.
#
# Run with:  sudo bash install.sh
# =============================================================================
set -e

if [ "$EUID" -ne 0 ]; then
  echo "ERROR: Please run as root:  sudo bash install.sh"
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
echo "=== Pi Music Console Installer ==="
echo "User: $USER_NAME"
echo "Home: $HOME_DIR"
echo "Repo: $REPO_DIR"
echo ""

echo "[1/4] Installing system packages..."
apt-get update -qq
apt-get install -y \
    alsa-utils \
    mpv \
    ffmpeg \
    git \
    i2c-tools \
    python3-pip \
    python3-venv \
    python3-gpiozero \
    python3-lgpio \
    liblgpio-dev \
    python3-evdev \
    python3-smbus

echo "[2/4] Creating Python virtual environment..."
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

# Replace placeholders with actual user and paths
sed -i "s|/home/pizza|$HOME_DIR|g"   "$SERVICE_FILE"
sed -i "s|User=pizza|User=$USER_NAME|g"   "$SERVICE_FILE"
sed -i "s|Group=pizza|Group=$USER_NAME|g" "$SERVICE_FILE"

systemctl daemon-reload
systemctl enable pi-music.service

echo ""
echo "✓ Done! Service installed and enabled."
echo ""
echo "Next steps:"
echo "  sudo reboot"
echo ""
echo "After reboot:"
echo "  • mpv plays video/audio directly to HDMI (no X server needed)"
echo "  • Open browser on phone → http://$(hostname -I | awk '{print $1}'):5000"
echo "  • Check logs: sudo journalctl -u pi-music -f"
echo ""