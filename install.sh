#!/usr/bin/env bash
# =============================================================
#  Pi Music Console – Dependency Installer (v3)
#  "Bottom-Up" Manual Test Version
#  Fixed for Ubuntu 24.04 + Pi 5
# =============================================================
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="$(whoami)"

echo ""
echo "=== Pi Music Console Dependency Installer (v3) ==="
echo "Repo  : $REPO_DIR"
echo "User  : $USER_NAME"
echo ""

# ── 1. System packages ──────────────────────────────────────
echo "[1/3] Installing system packages (apt)..."
sudo apt-get update -qq
sudo apt-get install -y \
    alsa-utils \
    mpv \
    ffmpeg \
    python3-pip \
    python3-tk \
    python3-gpiozero \
    python3-evdev \
    python3-lgpio \
    liblgpio-dev \
    xorg \
    openbox \
    xserver-xorg-legacy \
    git \
    i2c-tools \
    python3-smbus

# ── 2. Python packages (pip) ────────────────────────────────
echo "[2/3] Checking Python requirements..."
pip3 install --break-system-packages -r "$REPO_DIR/requirements.txt" 2>/dev/null || true

# ── 3. Configuration (Xorg & Hardware Permissions) ──────────
echo "[3/4] Configuring hardware for Pi 5 / Ubuntu Server..."

# Check config.txt for the required graphics overlay
CONFIG_FILE="/boot/firmware/config.txt"
if [ -f "$CONFIG_FILE" ]; then
    if ! grep -q "dtoverlay=vc4-kms-v3d" "$CONFIG_FILE"; then
        echo "WARNING: 'dtoverlay=vc4-kms-v3d' not found in $CONFIG_FILE."
        echo "         This is usually required for the X server on Pi 5."
        echo "         Please add it manually and reboot."
    fi
fi

# Force the 'modesetting' driver (fixes "cannot run in framebuffer mode")
sudo mkdir -p /etc/X11/xorg.conf.d
sudo tee /etc/X11/xorg.conf.d/99-kms.conf > /dev/null <<EOF
Section "Device"
    Identifier "Card0"
    Driver "modesetting"
    Option "kmsdev" "/dev/dri/card0"
EndSection
EOF

# GPIO Permissions (Essential for Ubuntu Server)
# Ensure 'gpio' group exists
sudo groupadd -f gpio
# Create udev rule to grant 'gpio' group access to /dev/gpiochip*
sudo tee /etc/udev/rules.d/99-gpio.rules > /dev/null <<EOF
KERNEL=="gpiochip*", ACTION=="add", PROGRAM="/bin/sh -c 'chown root:gpio /dev/%k && chmod 775 /dev/%k'"
EOF
sudo udevadm control --reload-rules && sudo udevadm trigger

# Allow non-root users to start X server and give them a console
if [ -f /etc/X11/Xwrapper.config ]; then
    sudo sed -i 's/allowed_users=.*/allowed_users=anybody/' /etc/X11/Xwrapper.config
else
    echo "allowed_users=anybody" | sudo tee /etc/X11/Xwrapper.config > /dev/null
fi

# Add user to required groups for hardware access (Critical for Pi 5 + Ubuntu)
echo "      - Adding $USER_NAME to 'video', 'render', 'gpio', 'i2c', and 'input' groups..."
for grp in video render gpio i2c input; do
    if getent group "$grp" > /dev/null; then
        sudo usermod -a -G "$grp" "$USER_NAME"
    fi
done
echo "      - Created /etc/X11/xorg.conf.d/99-kms.conf"
echo "      - Set up /etc/udev/rules.d/99-gpio.rules"

# ── 4. Directory Setup ──────────────────────────────────────
echo "[4/4] Creating music folder..."
mkdir -p "$HOME/music"
echo "      Folder: $HOME/music"

echo ""
echo "=== Setup Complete! ==="
echo "Next steps for Hardware Testing:"
echo "  1. DAC: Add 'dtoverlay=hifiberry-dac' to /boot/firmware/config.txt"
echo "  2. Test Audio: Run './test_audio.sh'"
echo "  3. Test Encoder: Run 'python3 test_encoder.py'"
echo ""
