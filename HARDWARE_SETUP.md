# Hardware Setup & Manual Testing Guide

This guide describes how to connect the Adafruit PCM5122 DAC and a Rotary Encoder to your Raspberry Pi 5.

## ── 1. Wiring Table (Pi 5) ──────────────────────────────────

| COMPONENT | PIN NAME | PI GPIO (BCM) | PI PHYSICAL PIN |
| :--- | :--- | :--- | :--- |
| **PCM5122 DAC** | **VIN (3.3V)** | 3.3V | Pin 1 |
| | **GND** | GND | Pin 6 |
| | **LCK (WSEL)** | **GPIO 19** | Pin 35 |
| | **DIN** | **GPIO 21** | Pin 40 |
| | **BCK (CLK)** | **GPIO 18** | **Pin 12** |
| | **SDA/SCL** | **GPIO 2/3** | Pins 3/5 |
| **Rotary Encoder**| **CLK** | **GPIO 17** | Pin 11 |
| | **DT** | **GPIO 27** | **Pin 13** |
| | **GND** | GND | Pin 9 |

> [!IMPORTANT]
> **PIN CHANGE**: I have moved the Encoder **DT** pin from 18 to **27**. 
> This is because Pin 18 (GPIO 18) is required by the I2S DAC for the **Bit Clock (BCK)**.

---

## ── 2. Configuration (Bottom-Up) ──────────────────────────

### Step A: Enable the DAC
1. Run: `sudo nano /boot/firmware/config.txt`
2. Add or modify these lines at the bottom:
   ```text
   # Disable onboard audio to avoid conflicts
   dtparam=audio=off
   dtparam=i2s=on
   dtoverlay=hifiberry-dac
   ```
3. Save and Reboot: `sudo reboot`

### Step B: Install Dependencies
Run my new fixed installer:
```bash
bash install.sh
```

### Step C: Test Audio
Run the test script to see if the DAC is working:
```bash
bash test_audio.sh
```
*You should hear a sine wave tone.*

### Step D: Test Encoder
Run the Python test script (ensure your wiring matches the table above):
```bash
python3 test_encoder.py
```
*Turn the knob; you should see "Clockwise" or "Counter-clockwise" printed.*

### Step E: Test GUI (Headless)
To see if your screen can display windows without a full desktop:
```bash
startx /usr/bin/python3 music_player.py
```
*(Note: music_player.py must be in the current directory).*

### Troubleshooting Pi 5 / Ubuntu Server
If you see a "Fatal server error" or "can not open gpiochip":
1.  **Check config.txt**: Ensure `dtoverlay=vc4-kms-v3d` is present in `/boot/firmware/config.txt`.
2.  **Ubuntu Server GPIO**: Ubuntu lacks default GPIO rules. Run `bash install.sh` to create the `/etc/udev/rules.d/99-gpio.rules` and the `gpio` group.
3.  **Verify Permissions**: Run `ls -l /dev/gpiochip*`. You should see `root:gpio`. If you see `root:root`, the udev rule didn't trigger; run `sudo udevadm trigger`.
4.  **REBOOT**: You MUST reboot after running the installer for group memberships and udev rules to apply to your session.
5.  **Force Hotplug**: If your 5" screen isn't being detected, add `video=HDMI-A-1:800x480M@60D` to your kernel command line in `/boot/firmware/cmdline.txt`.
