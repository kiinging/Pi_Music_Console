from gpiozero import RotaryEncoder
from signal import pause
import sys

# =============================================================
#  Pi Music Console – Rotary Encoder Test (Corrected PINS)
# =============================================================
#  CLK = GPIO 17 (Physical Pin 11)
#  DT  = GPIO 27 (Physical Pin 13)
#  GND = Physical Pin 9 (or any GND)
# =============================================================

CLK_PIN = 17
DT_PIN  = 27

print(f"--- Rotary Encoder Hardware Test ---")
print(f"  Configuration: CLK={CLK_PIN} (Pin 11), DT={DT_PIN} (Pin 13)")
print(f"  Turn the knob to verify...")
print(f"  Press Ctrl+C to exit.")
print("-------------------------------------")

try:
    # lgpio is required for Pi 5 + gpiozero
    encoder = RotaryEncoder(CLK_PIN, DT_PIN, max_steps=100)

    def rotated_cw():
        print(">>> Rotated Clockwise (Volume ++)")

    def rotated_ccw():
        print("<<< Rotated Counter-Clockwise (Volume --)")

    encoder.when_rotated_clockwise = rotated_cw
    encoder.when_rotated_counter_clockwise = rotated_ccw

    pause()

except KeyboardInterrupt:
    print("\nTest stopped.")
except (ImportError, Exception) as e:
    print(f"\nERROR: {e}")
    print("Ensure 'python3-lgpio' and 'python3-gpiozero' are installed.")
    sys.exit(1)
