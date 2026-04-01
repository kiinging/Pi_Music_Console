#!/bin/bash
# Pi Music Console – Audio Test Script
# Verification for PCM5122 I2S DAC

echo "========================================"
echo "   Pi Music Console: Audio Hardware Test"
echo "========================================"
echo ""

# 1. Check if the card is detected
echo "[1/2] Checking ALSA sound cards..."
if aplay -l | grep -q "PCM51"; then
    echo "SUCCESS: PCM5122 DAC detected!"
    aplay -l | grep "card"
else
    echo "ERROR: DAC not found."
    echo "Did you add 'dtoverlay=iqaudio-dac' to /boot/firmware/config.txt?"
    echo "Current cards detected:"
    aplay -l
    exit 1
fi

echo ""
# 2. Play test tone
echo "[2/2] Starting Sine Wave Test (440Hz)..."
echo "      Outputting to all channels."
echo "      PRESS CTRL+C TO STOP"
echo ""

speaker-test -t sine -f 440 -c 2
