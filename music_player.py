#!/usr/bin/env python3
"""
#  Touchscreen music player for Raspberry Pi 5 (RPi OS Bookworm)
#  - Scans ~/music for audio files
#  - Touch-to-play with large buttons (800x480)
#  - Rotary encoder via gpiozero (CLK=GPIO17, DT=GPIO27)
#  - Audio output through PCM5122 DAC (hifiberry-dac overlay)
"""

import os
import sys
import subprocess
import threading
import tkinter as tk
from tkinter import font as tkfont
from pathlib import Path

# music_player.py

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────
MUSIC_FOLDER = Path.home() / "Music"
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 480
VOLUME_STEP = 5          # % per encoder click
SUPPORTED_EXT = (".mp4", ".mp3", ".flac", ".wav", ".ogg", ".m4a", ".aac")

# ALSA mixer name – PCM5122 often uses 'Digital' or 'Playback'
# We will attempt to auto-detect this in __init__
ALSA_MIXER = "Digital"

# GPIO pins for rotary encoder (BCM numbering)
CLK_PIN = 17
DT_PIN  = 27
SW_PIN  = 22

# ──────────────────────────────────────────────
# Rotary encoder – import gpiozero only on Pi
# ──────────────────────────────────────────────
ENCODER_AVAILABLE = False
try:
    from gpiozero import RotaryEncoder, Button
    ENCODER_AVAILABLE = True
except (ImportError, Exception):
    pass   # Running on dev PC – encoder silently disabled


def get_volume(mixer_name: str) -> int:
    """Read current ALSA volume (0-100)."""
    try:
        out = subprocess.check_output(
            ["amixer", "get", mixer_name], stderr=subprocess.DEVNULL
        ).decode()
        for line in out.splitlines():
            if "%" in line:
                start = line.index("[") + 1
                end   = line.index("%")
                return int(line[start:end])
    except Exception:
        pass
    return 50


def set_volume(mixer_name: str, value: int) -> int:
    """Clamp and set ALSA volume, return actual value."""
    value = max(0, min(100, value))
    try:
        subprocess.run(
            ["amixer", "set", mixer_name, f"{value}%"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass
    return value


# ──────────────────────────────────────────────
# Music Player (mpv subprocess)
# ──────────────────────────────────────────────
class Player:
    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._current: str | None = None
        self._lock = threading.Lock()

    @property
    def current(self) -> str | None:
        return self._current

    def play(self, path: str):
        with self._lock:
            self._stop_internal()
            self._current = path
            self._proc = subprocess.Popen(
                [
                    "mpv",
                    "--fs",             # Fullscreen for videos
                    "--ontop",          # Stay on top of GUI
                    "--audio-device=alsa",
                    "--really-quiet",
                    path,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def stop(self):
        with self._lock:
            self._stop_internal()
            self._current = None

    def _stop_internal(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    def is_playing(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None


# ──────────────────────────────────────────────
# GUI
# ──────────────────────────────────────────────
class PiMusicConsole(tk.Tk):
    def __init__(self):
        super().__init__()

        # ── Hardware / App State ────────────────
        self.player = Player()
        self.selected_idx = 0
        self.last_sw_time = 0
        self.click_count = 0

        # ── Volume / Mixer setup ────────────────
        self.mixer = self._detect_mixer()
        self.volume = get_volume(self.mixer)

        # ── Window setup ────────────────────────
        self.title("Pi Music Console")
        self.geometry(f"{SCREEN_WIDTH}x{SCREEN_HEIGHT}")
        self.resizable(False, False)
        self.configure(bg="#0f0f1a")
        # Remove window decorations for fullscreen kiosk feel
        self.attributes("-fullscreen", True)

        # ── Fonts ───────────────────────────────
        title_font  = tkfont.Font(family="DejaVu Sans", size=18, weight="bold")
        song_font   = tkfont.Font(family="DejaVu Sans", size=14)
        btn_font    = tkfont.Font(family="DejaVu Sans", size=16, weight="bold")
        status_font = tkfont.Font(family="DejaVu Sans", size=12)
        vol_font    = tkfont.Font(family="DejaVu Sans", size=13, weight="bold")

        # ── Header ──────────────────────────────
        header_frame = tk.Frame(self, bg="#1a1a2e", height=55)
        header_frame.pack(fill="x")
        header_frame.pack_propagate(False)

        tk.Label(
            header_frame,
            text="🎵  Pi Music Console",
            font=title_font,
            fg="#e0aaff",
            bg="#1a1a2e",
        ).pack(side="left", padx=18, pady=10)

        # Volume display (top-right)
        self.vol_label = tk.Label(
            header_frame,
            text=f"🔊 {self.volume}%",
            font=vol_font,
            fg="#c77dff",
            bg="#1a1a2e",
        )
        self.vol_label.pack(side="right", padx=18, pady=10)

        # System Status (Dashboard)
        self.sys_label = tk.Label(
            header_frame,
            text="🌡️ --°C  |  🧠 --%",
            font=status_font,
            fg="#9d9db5",
            bg="#1a1a2e",
        )
        self.sys_label.pack(side="right", padx=30, pady=10)

        # ── Song list (scrollable) ───────────────
        list_frame = tk.Frame(self, bg="#0f0f1a")
        list_frame.pack(fill="both", expand=True, padx=8, pady=(6, 0))

        canvas = tk.Canvas(list_frame, bg="#0f0f1a", highlightthickness=0)
        scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        self.song_frame = tk.Frame(canvas, bg="#0f0f1a")

        self.song_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self.song_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        # Touch scroll support
        canvas.bind("<ButtonPress-1>", self._on_touch_start)
        canvas.bind("<B1-Motion>", self._on_touch_drag)
        self._touch_y = 0
        self._canvas = canvas

        # ── Status bar ──────────────────────────
        status_frame = tk.Frame(self, bg="#1a1a2e", height=50)
        status_frame.pack(fill="x", side="bottom")
        status_frame.pack_propagate(False)

        self.status_label = tk.Label(
            status_frame,
            text="Select a song to play",
            font=status_font,
            fg="#9d9db5",
            bg="#1a1a2e",
        )
        self.status_label.pack(side="left", padx=14, pady=6)

        self.stop_btn = tk.Button(
            status_frame,
            text="⏹ Stop",
            font=btn_font,
            fg="#ffffff",
            bg="#c1121f",
            activebackground="#9d0208",
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            padx=18,
            pady=4,
            cursor="hand2",
            command=self.stop,
        )
        self.stop_btn.pack(side="right", padx=10, pady=6)

        quit_btn = tk.Button(
            status_frame,
            text="🚪 Quit",
            font=btn_font,
            fg="#ffffff",
            bg="#2a2a40",
            activebackground="#444466",
            activeforeground="#ffffff",
            relief="flat",
            bd=0,
            padx=18,
            pady=4,
            cursor="hand2",
            command=self.quit_app,
        )
        quit_btn.pack(side="right", padx=10, pady=6)

        # ── Load songs ──────────────────────────
        self.songs: list[Path] = []
        self.song_buttons: list[tk.Button] = []
        self._active_btn_idx: int | None = None
        self._load_songs()

        # ── Rotary encoder ──────────────────────
        if ENCODER_AVAILABLE:
            self._encoder = RotaryEncoder(CLK_PIN, DT_PIN)
            self._encoder.when_rotated_clockwise        = self._on_rotated_cw
            self._encoder.when_rotated_counter_clockwise = self._on_rotated_ccw

            self._sw = Button(SW_PIN, pull_up=True)
            self._sw.when_pressed = self._on_sw_pressed

        # ── Poll player status every second ─────
        self._poll_player()

        # ── Dashboard update ────────────────────
        self._update_dashboard()

    def _detect_mixer(self) -> str:
        """Attempt to find a working ALSA mixer name (Digital, Master, or Playback)."""
        for name in [ALSA_MIXER, "Master", "Playback", "HDMI"]:
            try:
                subprocess.check_output(["amixer", "get", name], stderr=subprocess.DEVNULL)
                return name
            except subprocess.CalledProcessError:
                continue
        return "Master"  # Fallback

    # ── Song loading ────────────────────────────
    def _load_songs(self):
        for w in self.song_frame.winfo_children():
            w.destroy()
        self.songs.clear()
        self.song_buttons.clear()
        self._active_btn_idx = None

        if not MUSIC_FOLDER.exists():
            tk.Label(
                self.song_frame,
                text=f"⚠ Folder not found:\n{MUSIC_FOLDER}",
                fg="#ffba08",
                bg="#0f0f1a",
                font=("DejaVu Sans", 13),
                justify="left",
            ).pack(padx=20, pady=30)
            return

        files = sorted(
            [f for f in MUSIC_FOLDER.iterdir() if f.suffix.lower() in SUPPORTED_EXT]
        )

        if not files:
            tk.Label(
                self.song_frame,
                text="No music files found in ~/music",
                fg="#9d9db5",
                bg="#0f0f1a",
                font=("DejaVu Sans", 13),
            ).pack(padx=20, pady=30)
            return

        for idx, path in enumerate(files):
            display = path.stem  # filename without extension
            btn = tk.Button(
                self.song_frame,
                text=f"  🎵  {display}",
                font=("DejaVu Sans", 14),
                fg="#e0e0f0",
                bg="#16213e",
                activebackground="#3d2c8d",
                activeforeground="#ffffff",
                relief="flat",
                bd=0,
                anchor="w",
                height=2,
                cursor="hand2",
                command=lambda i=idx, p=path: self._play_song(i, p),
            )
            btn.pack(fill="x", pady=2, padx=4)
            self.songs.append(path)
            self.song_buttons.append(btn)
        
        self._update_selection_ui()

    def _play_song(self, idx: int, path: Path):
        # Reset previous active button
        if self._active_btn_idx is not None:
            prev = self.song_buttons[self._active_btn_idx]
            prev.configure(bg="#16213e", fg="#e0e0f0")

        self._active_btn_idx = idx
        self.song_buttons[idx].configure(bg="#7b2d8b", fg="#ffffff")

        self.player.play(str(path))
        short = (path.stem[:50] + "…") if len(path.stem) > 50 else path.stem
        self.status_label.configure(text=f"▶  {short}", fg="#c77dff")

    def stop(self):
        self.player.stop()
        if self._active_btn_idx is not None:
             # Just reset the active colors - handled by _update_selection_ui
             pass
        self._active_btn_idx = None
        self.status_label.configure(text="Stopped", fg="#9d9db5")
        self.stop_btn.configure(text="▶ Start", bg="#38b000") # Changed to Start

    def _on_sw_pressed(self):
        """Handle physical SW button press logic."""
        import time
        now = time.time()
        
        # Double click detection (3 second window as requested)
        if (now - self.last_sw_time) < 3.0:
            self.click_count += 1
        else:
            self.click_count = 1
        
        self.last_sw_time = now

        if self.click_count == 2:
            print(">>> Double Click: Toggling Video View")
            self._handle_double_click()
            self.click_count = 0 # Reset
        else:
            # Plan for a single click after a short delay to see if a second follows?
            # Or just act immediately if that feels better. 
            # Given the 3s window, we act immediately but the 2nd click overrides/toggles.
            print(">>> Single Click: Toggling Play/Stop")
            self._handle_single_click()

    def _handle_single_click(self):
        """Toggle Play/Stop based on current selection."""
        if self.player.is_playing():
            self.stop()
        else:
            if self.selected_idx < len(self.songs):
                self._play_song(self.selected_idx, self.songs[self.selected_idx])
                self.stop_btn.configure(text="⏹ Stop", bg="#c1121f")

    def _handle_double_click(self):
        """Toggle video screen (using mpv command to minimize/hide)."""
        # For simplicity, if playing, we toggle the --fs flag via a restart or similar
        # In a real environment, we'd use mpv socket IPC. 
        # Here we will just print to console as the visual toggle.
        self.attributes("-fullscreen", not self.attributes("-fullscreen"))

    def _on_rotated_cw(self):
        if self.player.is_playing():
            self._volume_up()
        else:
            self._selection_down() # Navigate down in list

    def _on_rotated_ccw(self):
        if self.player.is_playing():
            self._volume_down()
        else:
            self._selection_up() # Navigate up in list

    def _selection_up(self):
        if not self.songs: return
        self.selected_idx = (self.selected_idx - 1) % len(self.songs)
        self._update_selection_ui()

    def _selection_down(self):
        if not self.songs: return
        self.selected_idx = (self.selected_idx + 1) % len(self.songs)
        self._update_selection_ui()

    def _update_selection_ui(self):
        """Update the list highlighting to show current selection."""
        for i, btn in enumerate(self.song_buttons):
            if i == self._active_btn_idx:
                btn.configure(bg="#7b2d8b", fg="#ffffff") # Playing (Purple)
            elif i == self.selected_idx:
                btn.configure(bg="#4361ee", fg="#ffffff") # Highlighted (Blue)
            else:
                btn.configure(bg="#16213e", fg="#e0e0f0") # Default

    def quit_app(self):
        """Stop music and exit the application."""
        self.player.stop()
        self.destroy()
        sys.exit(0)

    # ── Volume ──────────────────────────────────
    def _volume_up(self):
        self.volume = set_volume(self.mixer, self.volume + VOLUME_STEP)
        self._refresh_volume()

    def _volume_down(self):
        self.volume = set_volume(self.mixer, self.volume - VOLUME_STEP)
        self._refresh_volume()

    def _refresh_volume(self):
        self.vol_label.configure(text=f"🔊 {self.volume}%")

    # ── Touch scroll ────────────────────────────
    def _on_touch_start(self, event):
        self._touch_y = event.y

    def _on_touch_drag(self, event):
        delta = self._touch_y - event.y
        self._canvas.yview_scroll(int(delta / 5), "units")
        self._touch_y = event.y

    # ── Player polling ──────────────────────────
    def _poll_player(self):
        """Detect when mpv finishes so the button resets."""
        if self._active_btn_idx is not None and not self.player.is_playing():
            # Song ended naturally
            self.song_buttons[self._active_btn_idx].configure(
                bg="#16213e", fg="#e0e0f0"
            )
            self._active_btn_idx = None
            self.status_label.configure(text="Select a song to play", fg="#9d9db5")
        # Reschedule
        self.after(1000, self._poll_player)

    # ── Dashboard Update ────────────────────────
    def _update_dashboard(self):
        """Fetch system stats (temp and load) and update label."""
        try:
            # CPU Temp
            temp_c = 0.0
            if os.path.exists("/sys/class/thermal/thermal_zone0/temp"):
                with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                    temp_milli = int(f.read().strip())
                    temp_c = temp_milli / 1000.0
            
            # CPU Load (1 min avg)
            load1, _, _ = os.getloadavg()
            # Normalize to cores (Pi 5 has 4 cores)
            load_pct = (load1 / 4.0) * 100
            
            self.sys_label.configure(text=f"🌡️ {temp_c:.1f}°C  |  🧠 {load_pct:.0f}%")
        except Exception:
             self.sys_label.configure(text="🌡️ ??°C  |  🧠 ??%")
        
        self.after(5000, self._update_dashboard)


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────
if __name__ == "__main__":
    app = PiMusicConsole()
    app.mainloop()
