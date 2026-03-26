

# 🎵 Project: Pi Music Console

## Goal

Create a **Raspberry Pi 5 music player system** that:

* boots directly into a GUI (no login screen)
* shows a simple touchscreen music interface
* automatically scans a USB or music folder
* plays MP4 audio
* outputs sound through PCM5122 DAC
* allows volume control using rotary encoder
* sends audio to Class A amplifier
* runs on Ubuntu Server (lightweight)

---

# 🧱 System Architecture

```
Power ON
   ↓
Ubuntu boots
   ↓
Auto login pizza
   ↓
Start Python GUI
   ↓
Scan music folder
   ↓
Show music list on touchscreen
   ↓
Touch to play music
   ↓
PCM5122 DAC output
   ↓
Rotary encoder adjusts volume
   ↓
JHL 1969 Class A amplifier
   ↓
Speaker
```

---

# 🖥️ Software to Install

## Update system

```bash
sudo apt update
sudo apt upgrade -y
```

---

# 🎧 Audio Support

Install audio packages

```bash
sudo apt install alsa-utils mpv ffmpeg
```

### Why

* alsa-utils → control DAC
* mpv → play MP4 audio
* ffmpeg → audio decoding

---

# 🎛️ PCM5122 DAC Setup

Check device:

```bash
aplay -l
```

You should see something like:

```
card 0: sndrpihifiberry
```

Set default audio:

```bash
sudo nano /etc/asound.conf
```

Add:

```bash
defaults.pcm.card 0
defaults.ctl.card 0
```

Test:

```bash
speaker-test
```

or

```bash
mpv music.mp4
```

---

# 🐍 Python GUI

Install Python GUI tools

```bash
sudo apt install python3-pip python3-tk
pip3 install gpiozero evdev
```

---

# 🎵 Music Player Library

Install MPV Python binding

```bash
pip3 install python-mpv
```

This allows Python to control music.

---

# 📁 Music Folder

Create folder

```bash
mkdir ~/music
```

Put MP4 files here:

```
/home/pizza/music
```

Downloaded from **4K Downloader**.

---

# 🎨 GUI Design

Simple screen:

```
-----------------------
 Pi Music Console
-----------------------

[ Song 1 ]
[ Song 2 ]
[ Song 3 ]
[ Song 4 ]

Volume: 60%

[ Play ]  [ Stop ]
```

Touch screen selects song.

Encoder controls volume.

---

# 🧾 Python Music GUI Example

```python
import os
import tkinter as tk
import mpv

music_folder = "/home/pizza/music"

player = mpv.MPV()

root = tk.Tk()
root.title("Pi Music Console")
root.geometry("800x480")

def play_song(song):
    player.play(song)

files = os.listdir(music_folder)

for file in files:
    if file.endswith(".mp4"):
        path = music_folder + "/" + file
        btn = tk.Button(root, text=file, height=2,
                        command=lambda p=path: play_song(p))
        btn.pack(fill="x")

root.mainloop()
```

---

# 🎛️ Rotary Encoder Volume Control

Connect encoder:

```
CLK → GPIO17
DT → GPIO18
SW → GPIO27
```

Install GPIO

```bash
pip3 install RPi.GPIO
```

Example:

```python
from gpiozero import RotaryEncoder
import os

encoder = RotaryEncoder(17, 18)

def volume_up():
    os.system("amixer set Master 5%+")

def volume_down():
    os.system("amixer set Master 5%-")

encoder.when_rotated_clockwise = volume_up
encoder.when_rotated_counter_clockwise = volume_down
```

Now rotating changes volume.

---

# 🚀 Auto Boot GUI

Enable auto login

```bash
sudo systemctl edit getty@tty1
```

Add:

```ini
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin pizza --noclear %I $TERM
```

---

# Start GUI automatically

```bash
nano ~/.bash_profile
```

Add:

```bash
python3 /home/pizza/music_player.py
```

---

# 📺 Boot Result

Power ON:

```
Ubuntu boot
↓
Auto login
↓
Python GUI
↓
Music list appears
↓
Touch to play
↓
Encoder adjusts volume
↓
PCM5122 outputs sound
↓
Amplifier plays music
```

Exactly like a **standalone music console**.

---

# 🎯 Recommended Extra Features

## USB auto detect

Install:

```bash
sudo apt install udisks2
```

Detect USB and copy music.

---

## Bigger touch buttons

In Python:

```python
font=("Arial", 20)
```

---

## Volume display

Show:

```
Volume: 75%
```

on screen.

---

## Boot logo

Show:

```
Pi Music Console
Loading...
```

before GUI.

---

# 🧠 Final System

## Hardware

* Pi 5
* 5 inch screen
* PCM5122 DAC
* Rotary encoder
* USB music
* 1969 JHL amplifier
* Speaker

---

## Software

* Ubuntu Server
* ALSA
* MPV
* Python
* Tkinter GUI
* GPIO encoder
* Auto boot

---

# 👍 Result

You get:

* no login screen
* touch music selection
* MP4 playback
* DAC output
* encoder volume
* amplifier output
* embedded music system

Like a **mini HiFi music console**.

---

If you want, I can **write a complete `music_player.py` (full working version with USB detection + encoder + volume display + play/pause buttons)** so you can run it directly on your Pi.
