#!/usr/bin/env bash
# =============================================================
#  Pi Music Console – Dependency Installer (v4)
#  Optimized for Raspberry Pi 5 + Raspberry Pi OS (Bookworm)
# =============================================================
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="$(whoami)"
HOME_DIR="/home/$USER_NAME"

echo ""
echo "=== Pi Music Console Dependency Installer (v4) ==="
echo "Repo      : $REPO_DIR"
echo "User      : $USER_NAME"
echo "OS Target : Raspberry Pi OS (Pi 5)"
echo ""

# ── 1. System packages ──────────────────────────────────────
echo "[1/4] Installing system packages (apt)..."
sudo apt-get update -qq
sudo apt-get install -y \
    alsa-utils \
    mpv \
    ffmpeg \
    python3-pip \
    python3-tk \
    python3-gpiozero \
    python3-lgpio \
    liblgpio-dev \
    git \
    i2c-tools \
    python3-smbus

# ── 2. Python packages (pip) ────────────────────────────────
echo "[2/4] Checking Python requirements..."
if [ -f "$REPO_DIR/requirements.txt" ]; then
    pip3 install --break-system-packages -r "$REPO_DIR/requirements.txt" 2>/dev/null || true
fi

# ── 3. Hardware Permissions ─────────────────────────────────
echo "[3/4] Configuring hardware permissions..."

# Ensure 'gpio' group exists and add user
sudo groupadd -f gpio
sudo usermod -a -G gpio,audio,video,input,render "$USER_NAME"

# ── 4. Autostart & Directory Setup ──────────────────────────
echo "[4/4] Setting up Autostart and Folders..."

# Create music folder
mkdir -p "$HOME_DIR/music"

# Create autostart directory
mkdir -p "$HOME_DIR/.config/autostart"

# Create the .desktop autostart file
cat <<EOF > "$HOME_DIR/.config/autostart/pi-music.desktop"
[Desktop Entry]
Type=Application
Name=Pi Music Console
Comment=Touchscreen Music Player
Exec=$REPO_DIR/start_kiosk.sh
Terminal=false
Categories=AudioVideo;Player;
EOF

chmod +x "$HOME_DIR/.config/autostart/pi-music.desktop"

# Ensure start_kiosk is executable
chmod +x "$REPO_DIR/start_kiosk.sh"

echo ""
echo "=== Setup Complete! ==="
echo "Next steps:"
echo "  1. DAC: Ensure 'dtoverlay=hifiberry-dac' is in /boot/firmware/config.txt"
echo "  2. Reboot: Run 'sudo reboot' for permissions and autostart to take effect."
echo "  3. Music: Put some songs in '~/music'."
echo ""
