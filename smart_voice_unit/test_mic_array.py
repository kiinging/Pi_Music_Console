import os
import sys
import time
from pathlib import Path
import pyaudio

try:
    import sherpa_onnx
    from rapidfuzz import process, fuzz
except ImportError:
    print("Please make sure you have run the setup_voice.sh script to install dependencies.")
    sys.exit(1)

# Set up paths to the models
VOICE_UNIT_DIR = Path(__file__).parent
MODELS_DIR = VOICE_UNIT_DIR / "models"

try:
    KWS_DIR = next(MODELS_DIR.glob("sherpa-onnx-kws-zipformer-gigaspeech*"))
except StopIteration:
    KWS_DIR = MODELS_DIR / "sherpa-onnx-kws-zipformer-gigaspeech"

ASR_DIR = MODELS_DIR / "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20"

# The wake word you want to use
WAKE_WORD = "TELEFUNKEN"

# Write the wake word to keywords.txt
with open(VOICE_UNIT_DIR / "keywords.txt", "w") as f:
    f.write(f"{WAKE_WORD} :1.5 #0.45\n")

def get_kws():
    return sherpa_onnx.KeywordSpotter(
        tokens=str(KWS_DIR / "tokens.txt"),
        encoder=str(KWS_DIR / "encoder-epoch-12-avg-2-chunk-16-left-64.onnx"),
        decoder=str(KWS_DIR / "decoder-epoch-12-avg-2-chunk-16-left-64.onnx"),
        joiner=str(KWS_DIR / "joiner-epoch-12-avg-2-chunk-16-left-64.onnx"),
        keywords_file=str(VOICE_UNIT_DIR / "keywords.txt"),
        num_threads=1,
        sample_rate=16000,
        feature_dim=80,
        keywords_score=1.5,
        keywords_threshold=0.45,
        provider="cpu",
    )

def get_asr():
    return sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=str(ASR_DIR / "tokens.txt"),
        encoder=str(ASR_DIR / "encoder-epoch-99-avg-1.onnx"),
        decoder=str(ASR_DIR / "decoder-epoch-99-avg-1.onnx"),
        joiner=str(ASR_DIR / "joiner-epoch-99-avg-1.onnx"),
        num_threads=1,
        sample_rate=16000,
        feature_dim=80,
        decoding_method="greedy_search",
        provider="cpu",
    )

def main():
    print("=" * 50)
    print("  ReSpeaker USB 4 Mic Array Tester")
    print("=" * 50)
    
    pa = pyaudio.PyAudio()
    print("\nDetecting Microphones...")
    mic_index = None
    
    # List all input devices
    for i in range(pa.get_device_count()):
        dev = pa.get_device_info_by_index(i)
        name = dev.get('name', '').lower()
        if dev['maxInputChannels'] > 0:
            print(f"[{i}] {dev['name']}")
            # Look for ReSpeaker keywords
            if any(key in name for key in ['respeaker', 'xmos', 'xv']):
                mic_index = i

    if mic_index is not None:
        print(f"\n[+] Successfully auto-detected ReSpeaker Mic Array at index {mic_index}")
    else:
        print("\n[!] ReSpeaker not automatically found.")
        try:
            mic_index = int(input("Please enter the index of your ReSpeaker microphone from the list above: "))
        except ValueError:
            print("Invalid index entered. Exiting.")
            sys.exit(1)

    print("\nLoading AI Models (This might take a few seconds)...")
    try:
        kws = get_kws()
        asr = get_asr()
        print("[+] Models loaded successfully!")
    except Exception as e:
        print(f"[!] Error loading models: {e}")
        print("Please ensure the models are downloaded correctly.")
        sys.exit(1)

    print(f"\n" + "-"*50)
    print(f" PHASE 1: WAKE WORD DETECTION")
    print(f" Please say: '{WAKE_WORD}'")
    print(f"-"*50)

    try:
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=16000,
            input=True,
            input_device_index=mic_index,
            frames_per_buffer=1024
        )
    except Exception as e:
        print(f"[!] Error opening microphone: {e}")
        sys.exit(1)

    kws_stream = kws.create_stream()

    try:
        while True:
            data = stream.read(1024, exception_on_overflow=False)
            samples = list(map(int, (int.from_bytes(data[i:i+2], 'little', signed=True) for i in range(0, len(data), 2))))
            
            kws_stream.accept_waveform(16000, samples)
            while kws.is_ready(kws_stream):
                kws.decode_stream(kws_stream)
            
            keyword = kws.get_result(kws_stream)
            
            if keyword:
                print(f"\n[TERMINAL REPLY] >>> Yes master, I heard you! You called: {keyword}")
                
                print(f"\n" + "-"*50)
                print(f" PHASE 2: COMMAND RECOGNITION")
                print(f" Now say something like 'play hotel california' or 'play some music'...")
                print(f"-"*50)
                
                # Switch to ASR for 5 seconds to listen for command
                asr_stream = asr.create_stream()
                start_time = time.time()
                print("Listening for 5 seconds...", end="", flush=True)
                
                while time.time() - start_time < 5:
                    data = stream.read(1024, exception_on_overflow=False)
                    samples = list(map(int, (int.from_bytes(data[i:i+2], 'little', signed=True) for i in range(0, len(data), 2))))
                    asr_stream.accept_waveform(16000, samples)
                    
                    while asr.is_ready(asr_stream):
                        asr.decode_stream(asr_stream)
                    
                    # Optional: Print dots to show it's listening
                    res = asr.get_result(asr_stream).text
                    if res:
                        print(".", end="", flush=True)
                
                full_text = asr.get_result(asr_stream).text
                print(f"\n\n[TERMINAL REPLY] >>> I heard you say: '{full_text}'")
                
                # Process the command
                if "play" in full_text.lower():
                    # Extract what comes after "play"
                    query = full_text.lower().split("play")[-1].strip()
                    
                    if not query or query == "music":
                        print("[TERMINAL REPLY] >>> You just said 'play music'. I would resume playback here.")
                    else:
                        print(f"[TERMINAL REPLY] >>> You want to search for song: '{query}'")
                        print(">>> Searching your Music folder...")
                        
                        MUSIC_DIR = Path.home() / "Music"
                        try:
                            # Create directory if it doesn't exist for some reason
                            MUSIC_DIR.mkdir(parents=True, exist_ok=True)
                            
                            songs = [f.name for f in MUSIC_DIR.iterdir() if f.suffix.lower() in ('.mp3', '.mkv', '.mp4', '.flac', '.wav')]
                            
                            if not songs:
                                print(f"[TERMINAL REPLY] >>> The folder {MUSIC_DIR} is empty. I cannot find any songs.")
                            else:
                                match = process.extractOne(query, songs, scorer=fuzz.WRatio)
                                if match and match[1] > 65:
                                    print(f"[TERMINAL REPLY] >>> SUCCESS! I found a match: '{match[0]}' (Confidence: {match[1]:.1f}%)")
                                    print("[TERMINAL REPLY] >>> In the real app, I would now play this song.")
                                else:
                                    print(f"[TERMINAL REPLY] >>> No good match found for '{query}'. I couldn't find a song with that name.")
                        except Exception as e:
                            print(f"[TERMINAL REPLY] >>> Error searching for songs: {e}")
                else:
                    print("[TERMINAL REPLY] >>> I didn't hear the word 'play', so I won't search for a song.")
                
                print(f"\n" + "-"*50)
                print(" TEST COMPLETE - YOU CAN CALL THE WAKE WORD AGAIN")
                print(" Or press Ctrl+C to exit the program.")
                print(f"-"*50 + "\n")
                
                # Reset KWS stream to listen for wake word again
                kws_stream = kws.create_stream()
                
    except KeyboardInterrupt:
        print("\n\n[+] Exiting test script. Have a great day!")
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()

if __name__ == "__main__":
    main()
