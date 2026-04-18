#!/bin/bash
# voice_setup.sh - Setup Telefunken Voice Assistant for Pi 5

echo "--- Installing System Dependencies ---"
sudo apt-get update
sudo apt-get install -y libasound2-dev portaudio19-dev libsndfile1 python3-pip wget bzip2

echo "--- Installing Python Libraries ---"
pip3 install --upgrade pip
pip3 install sherpa-onnx pyaudio rapidfuzz requests

echo "--- Downloading AI Models (Telefunken) ---"
# Create models directory
mkdir -p models && cd models

# 1. Download Keyword Spotting (KWS) Model
if [ ! -d "sherpa-onnx-kws-zipformer-gigaspeech-2024-01-07" ]; then
    echo "Downloading KWS Model..."
    wget -q https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/sherpa-onnx-kws-zipformer-gigaspeech-2024-01-07.tar.bz2
    tar xf sherpa-onnx-kws-zipformer-gigaspeech-2024-01-07.tar.bz2
    rm sherpa-onnx-kws-zipformer-gigaspeech-2024-01-07.tar.bz2
fi

# 2. Download Bilingual ASR Model (for Song Names)
if [ ! -d "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20" ]; then
    echo "Downloading ASR Model (ZH/EN)..."
    wget -q https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20.tar.bz2
    tar xf sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20.tar.bz2
    rm sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20.tar.bz2
fi

cd ..
echo "--- Setup Complete! ---"
echo "You can now run: python3 telefunken_voice.py"
