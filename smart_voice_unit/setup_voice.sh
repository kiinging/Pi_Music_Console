#!/bin/bash
# setup_voice.sh - Dedicated setup for the Smart Voice Unit
set -e

# 1. Install System Dependencies
echo "--- Installing PortAudio & Dependencies ---"
sudo apt-get update
sudo apt-get install -y libasound2-dev portaudio19-dev libsndfile1 python3-pip wget bzip2

# 2. Install Python Packages
echo "--- Installing Python Libraries ---"
pip3 install --upgrade pip --break-system-packages
pip3 install sherpa-onnx pyaudio rapidfuzz requests --break-system-packages

# 3. Download AI Models
echo "--- Downloading Offline AI Models ---"
mkdir -p models && cd models

# Keyword Spotting (KWS)
KWS_MODEL="sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01"
if [ ! -d "$KWS_MODEL" ]; then
    echo "Downloading KWS Model (this may take a minute)..."
    URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/${KWS_MODEL}.tar.bz2"
    wget -c --show-progress "$URL"
    
    echo "Extracting KWS Model..."
    if tar xf "${KWS_MODEL}.tar.bz2"; then
        rm "${KWS_MODEL}.tar.bz2"
    else
        echo "[!] Error: KWS Model extraction failed. The file may be corrupted."
        rm -f "${KWS_MODEL}.tar.bz2"*
        exit 1
    fi
fi

# Streaming ASR (Speech-to-Text)
ASR_MODEL="sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20"
if [ ! -d "$ASR_MODEL" ]; then
    echo "Downloading ASR Model (this may take a minute)..."
    URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/${ASR_MODEL}.tar.bz2"
    
    # Use wget -c to resume, but handle the case where the file exists but is corrupted
    # and wget might create .1, .2 files. We prefer resuming the original file.
    wget -c --show-progress "$URL"
    
    echo "Extracting ASR Model..."
    if tar xf "${ASR_MODEL}.tar.bz2"; then
        rm "${ASR_MODEL}.tar.bz2"
    else
        echo "[!] Error: ASR Model extraction failed. Deleting partial file and retrying might be necessary."
        # Clean up partial files to avoid .1, .2 mess
        rm -f "${ASR_MODEL}.tar.bz2"*
        exit 1
    fi
fi

cd ..

echo "----------------------------------------"
echo "Setup Complete! Smart Voice Unit is ready."
echo "To start listening: python3 voice_controller.py"
echo "----------------------------------------"

