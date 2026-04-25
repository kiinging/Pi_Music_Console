#!/usr/bin/env python3
"""
Smart Voice Unit - Independent Plugin
=====================================
Voice control for Pi Music Console using Respeaker XVF3800.
This script runs independently and communicates via the local Flask API.
Compatible with sherpa-onnx >= 1.12.x
"""

import os
import sys
import time
import json
import requests
import pyaudio
import threading
import math
import numpy as np
from pathlib import Path

# Try to import optional AI libraries
try:
    import sherpa_onnx
    from rapidfuzz import process, fuzz
except ImportError:
    print("[!] Error: missing dependencies. Please run './setup_voice.sh' first.")
    sys.exit(1)

# --- Configuration ---
WAKE_WORD = "TELEFUNKEN"
BASE_URL = "http://127.0.0.1:5000"
MUSIC_DIR = Path.home() / "Music"

# Model Paths (Relative to script)
VOICE_UNIT_DIR = Path(__file__).parent
MODELS_DIR = VOICE_UNIT_DIR / "models"
# Dynamically find the KWS directory (it may have different date suffixes)
KWS_DIR = next(MODELS_DIR.glob("sherpa-onnx-kws-zipformer-gigaspeech*"), MODELS_DIR / "sherpa-onnx-kws-zipformer-gigaspeech")
ASR_DIR = MODELS_DIR / "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20"


def create_keyword_spotter():
    """Create KWS using the new flat-argument API (sherpa-onnx >= 1.12)."""
    return sherpa_onnx.KeywordSpotter(
        tokens=str(KWS_DIR / "tokens.txt"),
        encoder=str(KWS_DIR / "encoder-epoch-12-avg-2-chunk-16-left-64.onnx"),
        decoder=str(KWS_DIR / "decoder-epoch-12-avg-2-chunk-16-left-64.onnx"),
        joiner=str(KWS_DIR / "joiner-epoch-12-avg-2-chunk-16-left-64.onnx"),
        keywords_file=str(VOICE_UNIT_DIR / "keywords.txt"),
        num_threads=2,
        sample_rate=16000,
        feature_dim=80,
        keywords_score=1.5,
        keywords_threshold=0.45,
        provider="cpu",
    )


def create_asr_recognizer():
    """Create ASR using the new from_transducer() factory method (sherpa-onnx >= 1.12)."""
    return sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=str(ASR_DIR / "tokens.txt"),
        encoder=str(ASR_DIR / "encoder-epoch-99-avg-1.onnx"),
        decoder=str(ASR_DIR / "decoder-epoch-99-avg-1.onnx"),
        joiner=str(ASR_DIR / "joiner-epoch-99-avg-1.onnx"),
        num_threads=2,
        sample_rate=16000,
        feature_dim=80,
        decoding_method="greedy_search",
        provider="cpu",
    )


class VoiceAssistant:
    def __init__(self):
        print(f"[*] Initializing Smart Voice Unit...")

        # Check models exist
        if not KWS_DIR.exists() or not ASR_DIR.exists():
            print(f"[!] Error: Models not found in {MODELS_DIR}")
            print("[!] Please run './setup_voice.sh' to download them.")
            sys.exit(1)

        # Safety Check: Is the Music Player API online?
        self.check_api_status()

        # Write keyword file
        with open(VOICE_UNIT_DIR / "keywords.txt", "w") as f:
            f.write(f"{WAKE_WORD}\n")

        print("[*] Loading KWS model (wake word)...")
        self.kws = create_keyword_spotter()

        print("[*] Loading ASR model (speech recognition)...")
        self.recognizer = create_asr_recognizer()

        self.kws_stream = self.kws.create_stream()
        self.pa = pyaudio.PyAudio()
        print("[✓] Models loaded successfully.")

    def check_api_status(self):
        """Verify the main music console is reachable."""
        print(f"[*] Connecting to Music Console at {BASE_URL}...")
        try:
            r = requests.get(f"{BASE_URL}/status", timeout=2)
            if r.status_code == 200:
                print("[✓] Music Console connected.")
            else:
                print(f"[!] Warning: Console returned status {r.status_code}")
        except Exception as e:
            print(f"[!] ERROR: Could not reach Music Console API ({e})")
            print("[!] Voice Unit will run but commands may fail.")

    def find_mic_index(self):
        """Specifically look for XMOS / XVF3800 / ReSpeaker."""
        for i in range(self.pa.get_device_count()):
            dev = self.pa.get_device_info_by_index(i)
            name = dev.get('name', '').lower()
            if any(key in name for key in ['respeaker', 'xmos', 'xv']):
                print(f"[+] Found Mic Array: {dev['name']} (Index {i})")
                return i
        print("[!] Warning: ReSpeaker XVF3800 not found. Falling back to default mic.")
        return None

    def execute_command(self, text):
        text = text.lower().strip()
        if not text:
            return
        print(f"[*] Command recognized: '{text}'")

        try:
            # Volume Controls
            if any(word in text for word in ["louder", "increase", "volume up", "up"]):
                current = self.get_current_vol()
                requests.post(f"{BASE_URL}/volume_set", json={"volume": min(100, current + 15)}, timeout=1)
                print("[✓] Action: Volume Up")
                return

            if any(word in text for word in ["lower", "softer", "volume down", "down"]):
                current = self.get_current_vol()
                requests.post(f"{BASE_URL}/volume_set", json={"volume": max(0, current - 15)}, timeout=1)
                print("[✓] Action: Volume Down")
                return

            # Playback Controls
            if "stop" in text:
                requests.post(f"{BASE_URL}/stop", timeout=1)
                print("[✓] Action: Stop")
                return

            if "pause" in text:
                requests.post(f"{BASE_URL}/pause", timeout=1)
                print("[✓] Action: Pause")
                return

            if "resume" in text or "play" in text:
                query = text.split("play")[-1].strip() if "play" in text else ""
                if query and query not in ("", "music", "something"):
                    self.play_by_search(query)
                else:
                    requests.post(f"{BASE_URL}/resume", timeout=1)
                    print("[✓] Action: Resume Playback")
                return

        except Exception as e:
            print(f"[!] API Error: {e}")

    def play_by_search(self, query):
        """Fuzzy match song name and play."""
        try:
            songs = [f.name for f in MUSIC_DIR.iterdir() if f.suffix.lower() in ('.mp3', '.mkv', '.mp4', '.flac')]
            match = process.extractOne(query, songs, scorer=fuzz.WRatio)
            if match and match[1] > 65:
                song_name = match[0]
                requests.post(f"{BASE_URL}/play", json={"filename": song_name}, timeout=1)
                print(f"[✓] Action: Playing '{song_name}' ({match[1]}% match)")
            else:
                print(f"[!] No match for '{query}'")
        except Exception as e:
            print(f"[!] Search Error: {e}")

    def get_current_vol(self):
        try:
            r = requests.get(f"{BASE_URL}/status", timeout=1)
            return r.json().get('volume', 50)
        except:
            return 50

    def listen_loop(self):
        mic_idx = self.find_mic_index()
        sample_rate = 16000
        chunk_size = 1024

        try:
            stream = self.pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=sample_rate,
                input=True,
                input_device_index=mic_idx,
                frames_per_buffer=chunk_size
            )

            print(f"\n[>>>] Smart Voice Unit ACTIVE [<<<]")
            print(f"Say: '{WAKE_WORD}' followed by a command.\n")

            while True:
                data = stream.read(chunk_size, exception_on_overflow=False)
                # Convert raw bytes to normalized float32 samples
                samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0

                self.kws_stream.accept_waveform(sample_rate, samples)

                while self.kws.is_ready(self.kws_stream):
                    self.kws.decode_stream(self.kws_stream)

                keyword = self.kws.get_result(self.kws_stream)
                if keyword:
                    print(f"\n[!] WAKE WORD DETECTED: {keyword}")
                    self.process_voice_command(stream, sample_rate)
                    # Reset KWS stream for next detection
                    self.kws_stream = self.kws.create_stream()

        except Exception as e:
            print(f"[!] Mic Error: {e}")
        finally:
            self.pa.terminate()

    def process_voice_command(self, mic_stream, sample_rate):
        """Switch to full ASR recognition for a few seconds."""
        asr_stream = self.recognizer.create_stream()
        start_time = time.time()
        print("  Listening for command...", end="", flush=True)

        while time.time() - start_time < 5:  # Listen for 5 seconds
            data = mic_stream.read(1024, exception_on_overflow=False)
            samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            asr_stream.accept_waveform(sample_rate, samples)

            while self.recognizer.is_ready(asr_stream):
                self.recognizer.decode_stream(asr_stream)

            res = self.recognizer.get_result(asr_stream)
            if res.text:
                print(".", end="", flush=True)

        full_text = self.recognizer.get_result(asr_stream).text
        print(f"\n[+] Processing: '{full_text}'")
        if full_text.strip():
            self.execute_command(full_text)


if __name__ == "__main__":
    try:
        assistant = VoiceAssistant()
        assistant.listen_loop()
    except KeyboardInterrupt:
        print("\n[*] Smart Voice Unit stopping...")
