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
    xorg \
    openbox \
    xserver-xorg-legacy \
    git \
    i2c-tools \
    python3-smbus

# ── 2. Python packages (pip) ────────────────────────────────
echo "[2/3] Checking Python requirements..."
pip3 install --break-system-packages -r "$REPO_DIR/requirements.txt" 2>/dev/null || true

# ── 3. Directory Setup ──────────────────────────────────────
echo "[3/3] Creating music folder..."
mkdir -p "$HOME/music"
echo "      Folder: $HOME/music"

echo ""
echo "=== Setup Complete! ==="
echo "Next steps for Hardware Testing:"
echo "  1. DAC: Add 'dtoverlay=iqaudio-dac' to /boot/firmware/config.txt"
echo "  2. Test Audio: Run './test_audio.sh'"
echo "  3. Test Encoder: Run 'python3 test_encoder.py'"
echo ""
