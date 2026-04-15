#!/usr/bin/env bash
# =============================================================================
# STEP 1 of 3 — Passwordless Auto-Login on TTY1
# =============================================================================
# This configures systemd-getty to automatically log in your user on TTY1
# without asking for a password.
#
# Test after reboot:
#   The terminal should log in automatically. No other services are started.
#
# Run with:  sudo bash install_1_autologin.sh
# =============================================================================
set -e

if [ "$EUID" -ne 0 ]; then
  echo "ERROR: Please run as root:  sudo bash install_1_autologin.sh"
  exit 1
fi

USER_NAME="${SUDO_USER:-$(whoami)}"
if [ "$USER_NAME" == "root" ]; then
  echo "ERROR: Run with sudo from your normal user account, not as root directly."
  exit 1
fi

echo ""
echo "=== STEP 1: Auto-Login (no password) ==="
echo "User: $USER_NAME"
echo ""

# ── Create the getty override drop-in ────────────────────────────────────────
OVERRIDE_DIR="/etc/systemd/system/getty@tty1.service.d"
OVERRIDE_FILE="$OVERRIDE_DIR/autologin.conf"

mkdir -p "$OVERRIDE_DIR"

cat > "$OVERRIDE_FILE" << EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $USER_NAME --noclear %I \$TERM
Type=idle
EOF

echo "Written: $OVERRIDE_FILE"

# ── Reload & restart getty ────────────────────────────────────────────────────
systemctl daemon-reload
systemctl restart "getty@tty1.service"

echo ""
echo "✓ Done! Auto-login configured for user: $USER_NAME"
echo ""
echo "Next steps:"
echo "  sudo reboot"
echo "  (After reboot, TTY1 should log in automatically — no password needed)"
echo "  Once confirmed, run:  sudo bash install.sh"
echo ""
