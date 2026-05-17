import time
import sys

# =============================================================================
# REJANG CONSOLE - VOICE SERVICE (XVF3800 STUB)
# =============================================================================

def listen():
    print("Voice Service: Listening for commands via ReSpeaker XVF3800...")
    try:
        while True:
            # Placeholder for XMOS XVF3800 USB HID or I2C communication
            # logic: if command == "volume up": requests.post('http://localhost:5000/api/volume', json={'volume': current+5})
            time.sleep(10)
    except KeyboardInterrupt:
        print("Voice Service: Stopped.")

if __name__ == "__main__":
    listen()
