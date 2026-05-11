#!/usr/bin/env bash
# =============================================================================
# CLEANUP — Remove All Pi Music Console Services
# =============================================================================
# Wipes everything added by install_1, install_2, and install_3 so you can
# start fresh or test a single step in isolation.
#
# Run with:  sudo bash remove_all_services.sh
# =============================================================================
set -e

if [ "$EUID" -ne 0 ]; then
  echo "ERROR: Please run as root:  sudo bash remove_all_services.sh"
  exit 1
fi

USER_NAME="${SUDO_USER:-$(whoami)}"
if [ "$USER_NAME" == "root" ]; then
  echo "ERROR: Run with sudo from your normal user account, not as root directly."
  exit 1
fi

HOME_DIR=$(getent passwd "$USER_NAME" | cut -d: -f6)

echo ""
echo "=== Removing ALL Pi Music Console Services ==="
echo ""

# ── Step 3: pi-music.service ──────────────────────────────────────────────────
echo "[1/3] Removing pi-music.service..."
if systemctl is-active --quiet pi-music.service 2>/dev/null; then
  systemctl stop pi-music.service && echo "      Stopped."
fi
if systemctl is-enabled --quiet pi-music.service 2>/dev/null; then
  systemctl disable pi-music.service && echo "      Disabled."
fi
if [ -f /etc/systemd/system/pi-music.service ]; then
  rm /etc/systemd/system/pi-music.service && echo "      Deleted service file."
else
  echo "      Not found — skipping."
fi

# ── Step 2: X server ~/.bash_profile entry ────────────────────────────────────
echo "[2/3] Removing X server auto-start from ~/.bash_profile..."
PROFILE_FILE="$HOME_DIR/.bash_profile"
if [ -f "$PROFILE_FILE" ] && grep -q "startx" "$PROFILE_FILE"; then
  # Remove the block we added (from the comment to the fi line)
  sed -i '/# ── Auto-start X on TTY1/,/^fi$/d' "$PROFILE_FILE"
  echo "      Removed startx block from $PROFILE_FILE"
else
  echo "      No startx entry found — skipping."
fi

# ── Step 1: getty autologin override ─────────────────────────────────────────
echo "[3/3] Removing autologin override for getty@tty1..."
OVERRIDE_FILE="/etc/systemd/system/getty@tty1.service.d/autologin.conf"
if [ -f "$OVERRIDE_FILE" ]; then
  rm "$OVERRIDE_FILE" && echo "      Deleted $OVERRIDE_FILE"
  # Remove the directory if now empty
  rmdir --ignore-fail-on-non-empty "/etc/systemd/system/getty@tty1.service.d"
else
  echo "      Not found — skipping."
fi

# ── Reload systemd ────────────────────────────────────────────────────────────
systemctl daemon-reload
systemctl reset-failed 2>/dev/null || true

echo ""
echo "✓ All services removed. The Pi is back to a clean state."
echo ""
echo "Verify nothing is left:"
echo "  systemctl status pi-music       # should say 'not found'"
echo "  systemctl status getty@tty1     # should be back to normal"
echo ""
echo "To start fresh with Step 1 only:"
echo "  sudo bash install_1_autologin.sh"
echo ""
