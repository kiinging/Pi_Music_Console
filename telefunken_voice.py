#!/usr/bin/env python3
import os
import sys
import time
import json
import requests
import pyaudio
import threading
import sherpa_onnx
from pathlib import Path
from rapidfuzz import process, fuzz

# --- Configuration ---
WAKE_WORD = "TELEFUNKEN"
BASE_URL = "http://127.0.0.1:5000"
MUSIC_DIR = Path.home() / "Music"

# Model Paths (Relative to script)
KWS_DIR = Path(__file__).parent / "models/sherpa-onnx-kws-zipformer-gigaspeech-2024-01-07"
ASR_DIR = Path(__file__).parent / "models/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20"

def get_kws_config():
    return sherpa_onnx.KeywordSpotterConfig(
        feat_config=sherpa_onnx.FeatureConfig(sample_rate=16000, feature_dim=80),
        model_config=sherpa_onnx.OnlineModelConfig(
            transducer=sherpa_onnx.OnlineTransducerModelConfig(
                encoder=str(KWS_DIR / "encoder-epoch-12-avg-2-chunk-16-left-64.onnx"),
                decoder=str(KWS_DIR / "decoder-epoch-12-avg-2-chunk-16-left-64.onnx"),
                joiner=str(KWS_DIR / "joiner-epoch-12-avg-2-chunk-16-left-64.onnx"),
            ),
            tokens=str(KWS_DIR / "tokens.txt"),
            num_threads=2,
            provider="cpu",
        ),
        keywords_file=str(Path(__file__).parent / "keywords.txt"),
    )

def get_asr_config():
    return sherpa_onnx.OnlineRecognizerConfig(
        feat_config=sherpa_onnx.FeatureConfig(sample_rate=16000, feature_dim=80),
        model_config=sherpa_onnx.OnlineModelConfig(
            transducer=sherpa_onnx.OnlineTransducerModelConfig(
                encoder=str(ASR_DIR / "encoder-epoch-99-avg-1.onnx"),
                decoder=str(ASR_DIR / "decoder-epoch-99-avg-1.onnx"),
                joiner=str(ASR_DIR / "joiner-epoch-99-avg-1.onnx"),
            ),
            tokens=str(ASR_DIR / "tokens.txt"),
            num_threads=2,
            provider="cpu",
        ),
        decoding_method="greedy_search",
    )

class TelefunkenAssistant:
    def __init__(self):
        print(f"[*] Initializing Telefunken Voice Brain...")
        
        # 1. Create Keyword Spotter
        with open("keywords.txt", "w") as f:
            f.write(f"{WAKE_WORD} :1.5 #0.45\n")
            
        self.kws = sherpa_onnx.KeywordSpotter(get_kws_config())
        self.recognizer = sherpa_onnx.OnlineRecognizer(get_asr_config())
        
        self.stream = self.recognizer.create_stream()
        self.kws_stream = self.kws.create_stream()
        
        self.pa = pyaudio.PyAudio()
        self.is_listening = False
        self.last_volume = 50

    def find_mic_index(self):
        """Find the XMOS / ReSpeaker device index."""
        for i in range(self.pa.get_device_count()):
            dev = self.pa.get_device_info_by_index(i)
            name = dev.get('name', '').lower()
            if 'respeaker' in name or 'xmos' in name or 'xv' in name:
                print(f"[+] Found Mic Array: {dev['name']} (Index {i})")
                return i
        print("[!] Warning: ReSpeaker not found. Using default microphone.")
        return None

    def get_music_files(self):
        files = []
        exts = ('.mp3', '.mkv', '.mp4', '.flac', '.wav', '.m4a')
        for f in MUSIC_DIR.iterdir():
            if f.suffix.lower() in exts:
                files.append(f.name)
        return files

    def execute_command(self, text):
        text = text.lower()
        print(f"[*] Analyzing intent: '{text}'")
        
        # 1. Volume Controls
        if "louder" in text or "increase" in text or "up" in text:
            requests.post(f"{BASE_URL}/volume_set", json={"volume": min(100, self.get_current_vol() + 15)})
            print("[✓] Action: Volume Up")
            return

        if "lower" in text or "softer" in text or "down" in text:
            requests.post(f"{BASE_URL}/volume_set", json={"volume": max(0, self.get_current_vol() - 15)})
            print("[✓] Action: Volume Down")
            return

        # 2. Playback Controls
        if "stop" in text:
            requests.post(f"{BASE_URL}/stop")
            print("[✓] Action: Stop")
            return
            
        if "pause" in text:
            requests.post(f"{BASE_URL}/pause")
            print("[✓] Action: Pause")
            return

        if "play" in text or "start" in text:
            # Extract target song
            query = text.split("play")[-1].strip()
            if query:
                songs = self.get_music_files()
                match = process.extractOne(query, songs, scorer=fuzz.WRatio)
                if match and match[1] > 60:
                    song_name = match[0]
                    requests.post(f"{BASE_URL}/play", json={"filename": song_name})
                    print(f"[✓] Action: Playing '{song_name}' (Match: {match[1]}%)")
                else:
                    print(f"[!] Could not find song matching '{query}'")

    def get_current_vol(self):
        try:
            r = requests.get(f"{BASE_URL}/status")
            return r.json().get('volume', 50)
        except: return 50

    def run(self):
        mic_idx = self.find_mic_index()
        
        # Open Microphone Stream (16kHz, Mono)
        sample_rate = 16000
        chunk_size = 1024
        
        stream = self.pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=sample_rate,
            input=True,
            input_device_index=mic_idx,
            frames_per_buffer=chunk_size
        )
        
        print(f"\n[>>>] Telefunken Listening... Try saying 'Hello Telefunken' [<<<]\n")
        
        try:
            while True:
                data = stream.read(chunk_size, exception_on_overflow=False)
                samples = list(map(int, (int.from_bytes(data[i:i+2], 'little', signed=True) for i in range(0, len(data), 2))))
                
                # Push to KWS stream
                self.kws_stream.accept_waveform(sample_rate, samples)
                
                # Check for Wake Word
                if self.kws.is_ready(self.kws_stream):
                    keyword = self.kws.get_keyword(self.kws_stream)
                    if keyword:
                        print(f"\n[!] WAKE WORD DETECTED: {keyword}")
                        print("[*] Roger! I'm listening...")
                        
                        # Switch to ASR for 5 seconds
                        self.listen_and_obey(stream)
                        
                        # Reset streams
                        self.kws_stream = self.kws.create_stream()
                
                self.kws.decode(self.kws_stream)
                
        except KeyboardInterrupt:
            print("\nShutting down Telefunken...")
        finally:
            stream.stop_stream()
            stream.close()
            self.pa.terminate()

    def listen_and_obey(self, mic_stream):
        """Transcribe speech for 5 seconds after wake word."""
        asr_stream = self.recognizer.create_stream()
        start_time = time.time()
        full_text = ""
        
        # Visual feedback: indicate we are listening
        print("  Listening for command...", end="", flush=True)
        
        while time.time() - start_time < 5:
            data = mic_stream.read(1024, exception_on_overflow=False)
            samples = list(map(int, (int.from_bytes(data[i:i+2], 'little', signed=True) for i in range(0, len(data), 2))))
            asr_stream.accept_waveform(16000, samples)
            
            while self.recognizer.is_ready(asr_stream):
                self.recognizer.decode_stream(asr_stream)
            
            new_text = self.recognizer.get_result(asr_stream).text
            if new_text and new_text != full_text:
                full_text = new_text
                print(".", end="", flush=True)

        print(f"\n[+] I heard: '{full_text}'")
        if full_text.strip():
            self.execute_command(full_text)

if __name__ == "__main__":
    # Check if models exist
    if not KWS_DIR.exists() or not ASR_DIR.exists():
        print("[!] Error: Model directories not found.")
        print("[!] Please run './voice_setup.sh' first to download the AI models.")
        sys.exit(1)
        
    assistant = TelefunkenAssistant()
    assistant.run()
