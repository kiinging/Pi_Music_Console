#!/usr/bin/env bash
# =============================================================
#  Pi Music Console – One-Shot Installer (v2)
#  Fixed for Ubuntu 24.04 + Pi 5 (PEP 668 & lgpio fix)
#  Usage:  bash install.sh
# =============================================================
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_SRC="$REPO_DIR/pi-music.service"
SERVICE_DEST="/etc/systemd/system/pi-music.service"
MUSIC_DIR="$HOME/music"
USER_NAME="$(whoami)"

echo ""
echo "=== Pi Music Console Installer (v2) ==="
echo "Repo  : $REPO_DIR"
echo "User  : $USER_NAME"
echo ""

# ── 1. System packages ──────────────────────────────────────
echo "[1/5] Installing system packages (apt)..."
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
    xinit \
    x11-xserver-utils \
    git

# ── 2. Python packages (pip - backup only) ──────────────────
echo "[2/5] Checking Python packages..."
# Most are already installed via 'apt' above. This is just a safety.
pip3 install --break-system-packages -r "$REPO_DIR/requirements.txt" 2>/dev/null || true

# ── 3. Create ~/music folder ────────────────────────────────
echo "[3/5] Creating music folder..."
mkdir -p "$MUSIC_DIR"
echo "      Folder: $MUSIC_DIR"

# ── 4. Auto-login + auto-start X ────────────────────────────
echo "[4/5] Setting up auto-login and auto-start X..."

# Auto-login override for getty@tty1
GETTY_DIR="/etc/systemd/system/getty@tty1.service.d"
sudo mkdir -p "$GETTY_DIR"
sudo tee "$GETTY_DIR/autologin.conf" > /dev/null <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $USER_NAME --noclear %I \$TERM
EOF

# ~/.bash_profile: start X on tty1
BASH_PROFILE="$HOME/.bash_profile"
if ! grep -q "startx" "$BASH_PROFILE" 2>/dev/null; then
    cat >> "$BASH_PROFILE" <<'EOF'

# Auto-start X on tty1
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    exec startx -- -nocursor 2>/dev/null
fi
EOF
    echo "      Added startx to $BASH_PROFILE"
fi

# Openbox autostart → launch music player
OPENBOX_CFG="$HOME/.config/openbox"
mkdir -p "$OPENBOX_CFG"
AUTOSTART="$OPENBOX_CFG/autostart"
if ! grep -q "music_player" "$AUTOSTART" 2>/dev/null; then
    cat >> "$AUTOSTART" <<EOF

# Pi Music Console
sleep 2
python3 $REPO_DIR/music_player.py &
EOF
    echo "      Added music_player.py to Openbox autostart"
fi

# ── 5. Install & enable systemd service ─────────────────────
echo "[5/5] Installing systemd service..."

# Patch the service file with the actual username and repo path
sed \
    -e "s|User=pizza|User=$USER_NAME|g" \
    -e "s|Group=pizza|Group=$USER_NAME|g" \
    -e "s|/home/pizza/Pi_Music_Console/music_player.py|$REPO_DIR/music_player.py|g" \
    -e "s|/home/pizza/.Xauthority|$HOME/.Xauthority|g" \
    -e "s|HOME=/home/pizza|HOME=$HOME|g" \
    -e "s|WorkingDirectory=/home/pizza|WorkingDirectory=$HOME|g" \
    "$SERVICE_SRC" | sudo tee "$SERVICE_DEST" > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable pi-music.service
echo "      Service enabled: pi-music.service"

echo ""
echo "=== Done! ==="
echo "Next steps: "
echo "  1. Reboot:    sudo reboot"
echo ""
