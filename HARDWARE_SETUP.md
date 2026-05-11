# Hardware Setup & Manual Testing Guide (Raspberry Pi OS)

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

### ── 1.1 Audio Output (Amplifier Connection) ────────────────

If you are connecting the DAC directly to an amplifier (bypassing the 3.5mm jack), use the following pins on the DAC board:

| DAC PIN | FUNCTION | CONNECTION |
| :--- | :--- | :--- |
| **L** | Left Channel | Amplifier Left Input |
| **R** | Right Channel | Amplifier Right Input |
| **G** | Audio Ground | Amplifier GND / Shield |

> [!TIP]
> **Line-Level Output**: The PCM5122 provides a ~2V RMS line-level output. This is perfect for power amplifiers but not designed to drive low-impedance headphones directly.

> [!IMPORTANT]
> **PIN CHANGE**: I have moved the Encoder **DT** pin from 18 to **27**. 
> This is because Pin 18 (GPIO 18) is required by the I2S DAC for the **Bit Clock (BCK)**.

---

## ── 2. Configuration (Raspberry Pi OS) ──────────────────────────

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
Run the new installer:
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
Run the Python test script:
```bash
python3 test_encoder.py
```
*Turn the knob; you should see "Clockwise" or "Counter-clockwise" printed.*

### Step E: Verify GUI Autostart
On Raspberry Pi OS (Pi 5/Wayland), the app handles its own window. To test it manually from the desktop:
```bash
python3 music_player.py
```

---

## ── 3. Troubleshooting (Pi 5 / Bookworm) ─────────────────────

1.  **Mixer Name**: If volume control doesn't work, run `amixer scontrols`. If it says "Digital" instead of "Master", update `ALSA_MIXER` in `music_player.py`.
2.  **Display Orientation**: If your 5" screen is upside down, use the **Screen Configuration** tool in the Raspberry Pi OS menu.
3.  **Permissions**: Ensure your user is in the `gpio` and `audio` groups (the installer does this).
4.  **GPIO Chip**: Pi 5 uses the RP1 chip. The code uses `lgpio` (via `gpiozero`) which is the correct backend for this hardware.
