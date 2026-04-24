#!/bin/bash
# setup_voice.sh - Dedicated setup for the Smart Voice Unit

# 1. Install System Dependencies
echo "--- Installing PortAudio & Dependencies ---"
sudo apt-get update
sudo apt-get install -y libasound2-dev portaudio19-dev libsndfile1 python3-pip wget bzip2

# 2. Install Python Packages
echo "--- Installing Python Libraries ---"
pip3 install --upgrade pip
pip3 install sherpa-onnx pyaudio rapidfuzz requests

# 3. Download AI Models
echo "--- Downloading Offline AI Models ---"
mkdir -p models && cd models

# Keyword Spotting (KWS)
if [ ! -d "sherpa-onnx-kws-zipformer-gigaspeech-2024-01-07" ]; then
    echo "Downloading KWS Model..."
    wget -q https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/sherpa-onnx-kws-zipformer-gigaspeech-2024-01-07.tar.bz2
    tar xf sherpa-onnx-kws-zipformer-gigaspeech-2024-01-07.tar.bz2
    rm sherpa-onnx-kws-zipformer-gigaspeech-2024-01-07.tar.bz2
fi

# Streaming ASR (Speech-to-Text)
if [ ! -d "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20" ]; then
    echo "Downloading ASR Model..."
    wget -q https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20.tar.bz2
    tar xf sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20.tar.bz2
    rm sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20.tar.bz2
fi

cd ..

echo "----------------------------------------"
echo "Setup Complete! Smart Voice Unit is ready."
echo "To start listening: python3 voice_controller.py"
echo "----------------------------------------"
