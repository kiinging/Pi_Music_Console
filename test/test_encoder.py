from gpiozero import RotaryEncoder, Device
from gpiozero.pins.lgpio import LGPIOFactory
from signal import pause
import sys

# Force lgpio backend for Raspberry Pi 5
Device.pin_factory = LGPIOFactory()

# =============================================================
# Pi Music Console – Rotary Encoder Test
# =============================================================

CLK_PIN = 17
DT_PIN  = 27

print("--- Rotary Encoder Hardware Test ---")
print(f"Configuration: CLK={CLK_PIN} (Pin 11), DT={DT_PIN} (Pin 13)")
print("Turn the knob to verify...")
print("Press Ctrl+C to exit.")
print("-------------------------------------")

try:
    encoder = RotaryEncoder(
        CLK_PIN,
        DT_PIN,
        max_steps=100,
        wrap=True
    )

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
    print("Ensure python3-lgpio and python3-gpiozero are installed.")
    sys.exit(1)