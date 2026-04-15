#!/usr/bin/env bash
# =============================================================================
# STEP 2 of 3 — X Display Server Auto-Start on Login
# =============================================================================
# This sets up X server (Openbox) to start automatically when the auto-logged-in
# user reaches the TTY. It uses ~/.bash_profile so X only starts on TTY1.
#
# Prerequisite:  Step 1 (autologin) must be working first.
#
# Test after reboot:
#   The display should show a blank Openbox desktop (black screen is normal).
#   No music app runs yet.
#
# Run with:  sudo bash install_2_xserver.sh
# =============================================================================
set -e

if [ "$EUID" -ne 0 ]; then
  echo "ERROR: Please run as root:  sudo bash install_2_xserver.sh"
  exit 1
fi

USER_NAME="${SUDO_USER:-$(whoami)}"
if [ "$USER_NAME" == "root" ]; then
  echo "ERROR: Run with sudo from your normal user account, not as root directly."
  exit 1
fi

HOME_DIR=$(getent passwd "$USER_NAME" | cut -d: -f6)

echo ""
echo "=== STEP 2: X Server Auto-Start ==="
echo "User: $USER_NAME"
echo "Home: $HOME_DIR"
echo ""

# ── Install required packages ─────────────────────────────────────────────────
echo "[1/3] Installing Xorg + Openbox..."
apt-get update -qq
apt-get install -y xorg openbox xinit x11-xserver-utils

# ── Write ~/.bash_profile to auto-start X on TTY1 ────────────────────────────
PROFILE_FILE="$HOME_DIR/.bash_profile"

echo "[2/3] Writing $PROFILE_FILE ..."

# Only add if not already there
if grep -q "startx" "$PROFILE_FILE" 2>/dev/null; then
  echo "      (startx entry already exists — skipping)"
else
  cat >> "$PROFILE_FILE" << 'PROFILE'

# ── Auto-start X on TTY1 (added by install_2_xserver.sh) ──
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
  exec startx -- -nocursor 2>/tmp/xorg.log
fi
PROFILE
  chown "$USER_NAME:$USER_NAME" "$PROFILE_FILE"
  echo "      Written."
fi

# ── Minimal Openbox autostart (does nothing yet) ──────────────────────────────
OPENBOX_DIR="$HOME_DIR/.config/openbox"
mkdir -p "$OPENBOX_DIR"
chown -R "$USER_NAME:$USER_NAME" "$OPENBOX_DIR"

if [ ! -f "$OPENBOX_DIR/autostart" ]; then
  cat > "$OPENBOX_DIR/autostart" << 'OB'
# Openbox autostart — Step 2 placeholder
# The music app will be added here in Step 3.
xset s off &
xset -dpms &
xset s noblank &
OB
  chown "$USER_NAME:$USER_NAME" "$OPENBOX_DIR/autostart"
  echo "[3/3] Written: $OPENBOX_DIR/autostart"
else
  echo "[3/3] $OPENBOX_DIR/autostart already exists — not overwritten."
fi

echo ""
echo "✓ Done! X server configured."
echo ""
echo "Next steps:"
echo "  sudo reboot"
echo "  (After reboot, display should power on — a blank/black desktop is correct)"
echo "  Check for errors:  cat /tmp/xorg.log"
echo "  Once confirmed, run:  sudo bash install_3_pimusic.sh"
echo ""
