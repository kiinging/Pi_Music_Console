# 🎵 Pi Music Console (Pure Web Edition)

A premium touchscreen music player for **Raspberry Pi 5** featuring a modern Web UI, PCM5122 DAC support, and auto-boot kiosk mode powered by Wayland/Weston.

---

## 🏗️ System Architecture

This project has moved away from X11 and Kivy to a **Pure Web Path** for maximum reliability and performance on Raspberry Pi 5.

```mermaid
graph TD
    A[Power ON] --> B[Debian 13 Trixie Boots]
    B --> C[Auto Login tty1]
    C --> D[startup.sh via .bash_profile]
    D --> E[Weston (Desktop Shell) Starts]
    F[Flask API Backend Starts]
    G[Chromium Kiosk Mode Launches]
    G --> H[Web UI on 5-inch CSI Screen]
```

---

## ⚡ Quick Start

### 1. Installation
Run the installer on your Pi to set up dependencies and the boot environment.
```bash
git clone https://github.com/kiinging/Pi_Music_Console.git
cd Pi_Music_Console
bash install.sh
```

### 2. Add Music
Copy your media files to `~/Music` or `~/Videos`.
```bash
mkdir -p ~/Music ~/Videos
# Transfer files...
```

### 3. Startup
The system is designed to start automatically on boot. To start manually:
```bash
bash scripts/startup.sh
```

---

## 📦 Hardware Requirements
- **Raspberry Pi 5**
- **5-inch CSI/DSI/HDMI Touchscreen** (800x480)
- **PCM5122 HiFi DAC** (e.g., HiFiBerry DAC+)
- **Rotary Encoder** (GPIO 17, 18)

---

## 🖥️ Software Stack
- **OS:** Debian GNU/Linux 13 (trixie)
- **Display Server:** Weston (Wayland)
- **Browser:** Chromium (Ozone/Wayland)
- **Backend:** Python 3 + Flask + MPV
- **Frontend:** Vanilla HTML5 / CSS3 / JS

---

## 🔧 Configuration

### Audio (PCM5122)
Ensure `/boot/firmware/config.txt` has:
```ini
dtoverlay=hifiberry-dacplus
```

### Boot Sequence
The system uses `agetty` for auto-login on `tty1`, which then triggers `scripts/startup.sh` via `~/.bash_profile`.

---

## 🐛 Troubleshooting
- **Black Screen:** Check `/tmp/weston.log`. Ensure no Xorg session is running.
- **No Sound:** Run `aplay -l` to verify the DAC is detected as Card 0 or 1.
- **Touch Issues:** Weston handles touch natively; ensure your screen is supported by the kernel.

---
*Built for Curtin Electronic Fundamentals 2026.*