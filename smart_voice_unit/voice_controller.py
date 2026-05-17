#!/usr/bin/env python3
"""
Smart Voice Unit - Independent Plugin
=====================================
Voice control for Pi Music Console using Respeaker XVF3800.
This script runs independently and communicates via the local Flask API.
"""

import os
import sys
import time
import json
import requests
import pyaudio
import threading
import math
from pathlib import Path

# Try to import optional AI libraries
try:
    import sherpa_onnx
    from rapidfuzz import process, fuzz
except ImportError:
    print("[!] Error: missing dependencies. Please run './setup_voice.sh' first.")
    sys.exit(1)

# --- Configuration ---
WAKE_WORD = "HELLO SARAWAK"
BASE_URL = "http://127.0.0.1:5000"
MUSIC_DIR = Path.home() / "Music"

# Model Paths (Relative to script)
VOICE_UNIT_DIR = Path(__file__).parent
MODELS_DIR = VOICE_UNIT_DIR / "models"
# Dynamically find the KWS directory (it may have different date suffixes)
KWS_DIR = next(MODELS_DIR.glob("sherpa-onnx-kws-zipformer-gigaspeech*"), MODELS_DIR / "sherpa-onnx-kws-zipformer-gigaspeech")
ASR_DIR = MODELS_DIR / "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20"

def get_kws_config():
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

def get_asr_config():
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
        print(f"[*] Initializing Sarawak Voice Unit (REJANG system)...")
        
        # Check models
        if not KWS_DIR.exists() or not ASR_DIR.exists():
            print(f"[!] Error: Models not found in {MODELS_DIR}")
            print("[!] Please run './setup_voice.sh' to download them.")
            sys.exit(1)

        # Safety Check: Is the Music Player API online?
        self.check_api_status()

        # 1. Create Keyword Spotter
        # Tokens for 'HELLO SARAWAK'
        tokens = " ".join(list(WAKE_WORD.replace(" ", "").upper()))
        with open(VOICE_UNIT_DIR / "keywords.txt", "w") as f:
            f.write(f"{tokens} :1.5 #0.45\n")
            
        self.kws = get_kws_config()
        self.recognizer = get_asr_config()
        
        self.kws_stream = self.kws.create_stream()
        self.pa = pyaudio.PyAudio()
        self.state = "IDLE"
        self.target_artist = ""

    def send_update(self, sarawak="", me="", awake=None):
        """Send message updates to the Flask UI."""
        try:
            payload = {}
            if sarawak: payload["sarawak"] = sarawak
            if me: payload["me"] = me
            if awake is not None: payload["awake"] = awake
            requests.post(f"{BASE_URL}/api/voice/message", json=payload, timeout=0.5)
        except: pass

    def check_api_status(self):
        """Verify the main music console is reachable."""
        print(f"[*] Connecting to Music Console at {BASE_URL}...")
        try:
            r = requests.get(f"{BASE_URL}/api/ping", timeout=2)
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
        text = text.lower()
        print(f"[*] Command recognized: '{text}'")
        self.send_update(me=text)
        
        try:
            # 0. Handle follow-up state
            if self.state == "WAITING_FOR_SONG":
                if any(word in text for word in ["any", "just"]):
                    self.send_update(sarawak=f"Playing any song by {self.target_artist}")
                    self.play_by_search(self.target_artist)
                    self.state = "IDLE"
                else:
                    self.send_update(sarawak=f"Noted. Looking for {text} by {self.target_artist}")
                    self.play_by_search(f"{self.target_artist} {text}")
                    self.state = "IDLE"
                
                # After playback starts, we go back to sleep mode
                time.sleep(2)
                self.send_update(awake=False)
                return

            # 1. Special Sarawak Commands
            if "good morning" in text:
                self.send_update(sarawak="Good morning! I am Sarawak, your REJANG system assistant.")
                return

            if "thank you" in text:
                self.send_update(sarawak="You're welcome! Returning to player.", awake=False)
                # We DON'T toggle the voice service off anymore, just the UI (awake=False)
                return

            # 2. Volume Controls
            if any(word in text for word in ["louder", "increase", "up"]):
                current = self.get_current_vol()
                requests.post(f"{BASE_URL}/api/volume", json={"volume": min(100, current + 15)}, timeout=1)
                self.send_update(sarawak="Volume increased.")
                return

            if any(word in text for word in ["lower", "softer", "down"]):
                current = self.get_current_vol()
                requests.post(f"{BASE_URL}/api/volume", json={"volume": max(0, current - 15)}, timeout=1)
                self.send_update(sarawak="Volume decreased.")
                return

            # 3. Playback Controls
            if "stop" in text:
                requests.post(f"{BASE_URL}/api/stop", timeout=1)
                self.send_update(sarawak="Playback stopped.", awake=False)
                return
                
            if "pause" in text:
                requests.post(f"{BASE_URL}/api/pause", timeout=1)
                self.send_update(sarawak="Paused.")
                return

            if "resume" in text or "play" in text:
                if "taylor swift" in text:
                    self.send_update(sarawak='Noted "Taylor Swift", any particular song?')
                    self.state = "WAITING_FOR_SONG"
                    self.target_artist = "Taylor Swift"
                    return

                query = text.split("play")[-1].strip()
                if query and query != "music":
                    self.send_update(sarawak=f"Searching for {query}...")
                    self.play_by_search(query)
                else:
                    requests.post(f"{BASE_URL}/api/resume", timeout=1)
                    self.send_update(sarawak="Resuming.")
                
                time.sleep(1)
                self.send_update(awake=False)
                return

        except Exception as e:
            print(f"[!] API Error: {e}")

    def play_by_search(self, query):
        """Fuzzy match song name and play."""
        try:
            r = requests.get(f"{BASE_URL}/api/songs", timeout=2)
            if r.status_code != 200: return
            songs_data = r.json()
            songs = [s['title'] for s in songs_data]
            match = process.extractOne(query, songs, scorer=fuzz.WRatio)
            if match and match[1] > 65:
                target = next(s for s in songs_data if s['title'] == match[0])
                requests.post(f"{BASE_URL}/api/play", json={"path": target['path'], "type": target['type']}, timeout=1)
                print(f"[✓] Action: Playing '{target['title']}'")
            else:
                print(f"[!] No match for '{query}'")
        except Exception as e:
            print(f"[!] Search Error: {e}")

    def get_current_vol(self):
        try:
            r = requests.get(f"{BASE_URL}/api/volume", timeout=1)
            return r.json().get('volume', 50)
        except: return 50

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
            
            print(f"\n[>>>] Sarawak Voice Unit ACTIVE [<<<]")
            print(f"Say: '{WAKE_WORD}' followed by a command.\n")
            
            while True:
                data = stream.read(chunk_size, exception_on_overflow=False)
                samples = list(map(int, (int.from_bytes(data[i:i+2], 'little', signed=True) for i in range(0, len(data), 2))))
                
                self.kws_stream.accept_waveform(sample_rate, samples)
                
                while self.kws.is_ready(self.kws_stream):
                    self.kws.decode_stream(self.kws_stream)
                
                keyword = self.kws.get_result(self.kws_stream)
                if keyword:
                    print(f"\n[!] WAKE WORD DETECTED: {keyword}")
                    # Signal UI to wake up
                    self.send_update(sarawak="Hello!!", awake=True)
                    self.process_voice_command(stream)
                    # Reset KWS
                    self.kws_stream = self.kws.create_stream()
                
        except Exception as e:
            print(f"[!] Mic Error: {e}")
        finally:
            self.pa.terminate()

    def process_voice_command(self, mic_stream):
        """Switch to full recognition for a few seconds."""
        asr_stream = self.recognizer.create_stream()
        start_time = time.time()
        print("  Listening for command...", end="", flush=True)
        
        while time.time() - start_time < 5: # Listen for 5 seconds
            data = mic_stream.read(1024, exception_on_overflow=False)
            samples = list(map(int, (int.from_bytes(data[i:i+2], 'little', signed=True) for i in range(0, len(data), 2))))
            asr_stream.accept_waveform(16000, samples)
            
            while self.recognizer.is_ready(asr_stream):
                self.recognizer.decode_stream(asr_stream)
            
            res = self.recognizer.get_result(asr_stream).text
            if res:
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
