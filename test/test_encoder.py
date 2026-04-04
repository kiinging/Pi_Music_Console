from gpiozero import RotaryEncoder, Button, Device
from gpiozero.pins.lgpio import LGPIOFactory
from signal import pause

# Force LGPIO backend (Pi 5)
Device.pin_factory = LGPIOFactory()

# =============================================================
# Pi Music Console – Rotary Encoder Test
# =============================================================

CLK_PIN = 17
DT_PIN  = 27
SW_PIN  = 22


print("--- Rotary Encoder Hardware Test ---")
print(f"Configuration: CLK={CLK_PIN} (Pin 11), DT={DT_PIN} (Pin 13)")
print("Turn the knob to verify...")
print("Press Ctrl+C to exit.")
print("-------------------------------------")

# Rotary encoder
encoder = RotaryEncoder(
    CLK_PIN,
    DT_PIN,
    max_steps=20,
    wrap=False
)

encoder.when_rotated_clockwise = lambda: print("Clockwise", encoder.steps)
encoder.when_rotated_counter_clockwise = lambda: print("Counter-clockwise", encoder.steps)

# Push button
button = Button(SW_PIN, pull_up=True)
button.when_pressed = lambda: print("=== Button Pressed ===")

pause()

