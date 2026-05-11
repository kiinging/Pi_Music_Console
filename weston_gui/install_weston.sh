#!/bin/bash

# --- LEARNING NOTE: What is Weston? ---
# Weston is the "reference implementation" of a Wayland compositor.
# Think of it as the engine that draws windows and handles your touch screen
# on a modern Linux system (replacing the old X11 system).

echo "Step 1: Installing Weston and SDL2 libraries..."
sudo apt update
sudo apt install -y weston wayland-protocols seatd libsdl2-2.0-0 libsdl2-dev libwayland-client0

# --- LEARNING NOTE: Permissions ---
# On a server OS, your user needs permission to touch the GPU and Input devices.
echo "Setting hardware permissions for user $USER..."
sudo usermod -aG video,render,input,seat $USER

# --- LEARNING NOTE: Why not Git Clone? ---
# Cloning from GitHub is usually for developers who want to MODIFY the code.
# For a stable GUI, 'apt install' is better because it ensures everything 
# matches your OS version.

echo "Step 2: Installing Python UI tools..."
# 'python3-kivy' is what we use to build the touch buttons.
# 'python3-requests' allows the buttons to talk to your music player.
sudo apt install -y python3-kivy python3-requests

echo "Step 3: Creating a simple configuration..."
mkdir -p ~/.config
cat <<EOF > ~/.config/weston.ini
[core]
# kiosk-shell makes your app go fullscreen immediately
shell=kiosk-shell.so
# drm-backend is the fastest way to talk to the Pi 5 GPU
backend=drm-backend.so

[output]
name=DSI-1
mode=800x480
EOF

echo "Setup Complete!"
echo "To learn more, run 'man weston' or 'man weston.ini' on your Pi."
