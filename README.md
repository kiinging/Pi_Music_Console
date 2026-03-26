# 🎵 Pi Music Console

A touchscreen music player for **Raspberry Pi 5** with PCM5122 DAC, rotary encoder volume control, and auto-boot kiosk mode.

---

## 📦 Hardware Requirements

| Component | Detail |
|---|---|
| Raspberry Pi 5 | Main controller |
| 5-inch HDMI touchscreen | 800 × 480 resolution |
| PCM5122 HiFiBerry DAC+ | I²C / I²S audio output |
| Rotary encoder (KY-040) | Volume control |
| Class-A amplifier (JHL 1969) | Speaker driver |
| Speaker | Audio output |

### Rotary Encoder Wiring (BCM numbering)

| Encoder Pin | Pi GPIO |
|---|---|
| CLK | GPIO 17 |
| DT | GPIO 18 |
| GND | GND |
| VCC | 3.3 V |

> **SW (button) pin is not used** – volume is controlled by rotation only.

---

## 🖥️ Software Requirements

### OS

Ubuntu Server 24.04 LTS (64-bit) – minimal install on Raspberry Pi 5.

### System packages

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y \
    alsa-utils \
    mpv \
    ffmpeg \
    python3-pip \
    python3-tk \
    python3-gpiozero \
    xorg \
    openbox \
    xinit \
    x11-xserver-utils
```

### Python packages

```bash
pip3 install gpiozero RPi.GPIO evdev
```

> `python-mpv` is **not** required – the player calls `mpv` as a subprocess.

---

## 📁 Music Folder

Create the music folder and add your MP4/MP3/FLAC files:

```bash
mkdir -p ~/music
# Copy or download files into ~/music/
```

Supported formats: `.mp4`, `.mp3`, `.flac`, `.wav`, `.ogg`, `.m4a`, `.aac`

---

## 🎛️ PCM5122 DAC Setup

### Enable HiFiBerry overlay

```bash
sudo nano /boot/firmware/config.txt
```

Add (or uncomment):

```ini
dtoverlay=hifiberry-dacplus
```

### Set ALSA default device

```bash
sudo nano /etc/asound.conf
```

Paste:

```
defaults.pcm.card 0
defaults.ctl.card 0
```

### Test audio

```bash
aplay -l            # should list card 0: sndrpihifiberry
speaker-test -c 2   # stereo sine wave test
```

---

## 🚀 Auto-login Setup

Enable passwordless console login for user `pizza`:

```bash
sudo systemctl edit getty@tty1
```

Paste into the override editor:

```ini
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin pizza --noclear %I $TERM
```

Save and exit (`Ctrl+O`, `Ctrl+X`).

### Start X automatically on login

```bash
nano ~/.bash_profile
```

Add at the bottom:

```bash
# Auto-start X if on tty1 and X is not already running
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    exec startx -- -nocursor
fi
```

### Configure Openbox to launch the music player

```bash
mkdir -p ~/.config/openbox
nano ~/.config/openbox/autostart
```

Add:

```bash
sleep 2
python3 /home/pizza/Pi_Music_Console/music_player.py &
```

---

## ⚙️ systemd Service Setup

The service file `pi-music.service` is included in this repository.

### 1 — Copy the script to your home directory area

```bash
# On the Pi, after git pull:
cd ~/Pi_Music_Console
```

### 2 — Copy the service file to systemd

```bash
sudo cp pi-music.service /etc/systemd/system/
```

### 3 — Reload systemd and enable the service

```bash
sudo systemctl daemon-reload
sudo systemctl enable pi-music.service
sudo systemctl start pi-music.service
```

### 4 — Check status

```bash
sudo systemctl status pi-music.service
journalctl -u pi-music -f     # live logs
```

### 5 — Restart / stop

```bash
sudo systemctl restart pi-music.service
sudo systemctl stop pi-music.service
```

---

## 📖 How It Works

```
Power ON
  ↓
Ubuntu boots
  ↓
Auto login (pizza)
  ↓
~/.bash_profile → startx
  ↓
Openbox → music_player.py
  ↓
Tkinter GUI (800×480 fullscreen)
  ↓
Scan ~/music for audio files
  ↓
Touch a song → mpv plays it
  ↓
Rotary encoder → amixer adjusts ALSA volume
  ↓
PCM5122 DAC → JHL Class-A amp → Speaker
```

---

## 🔧 Deployment (Git Workflow)

### On your development machine

```bash
git add .
git commit -m "feat: add music player GUI and service"
git push origin main
```

### On the Raspberry Pi

```bash
cd ~/Pi_Music_Console
git pull origin main
sudo systemctl restart pi-music.service
```

---

## 📋 File Overview

| File | Purpose |
|---|---|
| `music_player.py` | Main Python Tkinter GUI |
| `pi-music.service` | systemd unit file for auto-start |
| `README.md` | This file |
| `README_projectDescription.md` | Project design notes |

---

## 🐛 Troubleshooting

| Problem | Fix |
|---|---|
| No sound | Run `aplay -l` – check card name; verify `/etc/asound.conf` |
| GUI not starting | Check `journalctl -u pi-music -f`; verify `DISPLAY=:0` |
| Encoder not working | Check GPIO wiring; run `pinout` on the Pi |
| `mpv` not found | `sudo apt install mpv` |
| `amixer` fails | `sudo apt install alsa-utils` |
| Permission denied on GPIO | Add user to `gpio` group: `sudo usermod -aG gpio pizza` |

---

*Built for Curtin Electronic Fundamentals 2026 — Pi Music Console project.*
