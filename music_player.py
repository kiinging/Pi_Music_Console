#!/usr/bin/env python3
"""
Pi Music Console — Flask Web Controller
========================================
- Scans ~/Music for audio/video files
- mpv plays directly to HDMI (no X server needed)
- Control from any phone/browser at http://<pi-ip>:5000
- Rotary encoder: volume (while playing) / track select (while stopped)
- GPIO pins: CLK=17, DT=27, SW=22  (BCM numbering)
"""

import os
import subprocess
import threading
import time
import socket
import json
from pathlib import Path
from flask import Flask, jsonify, render_template_string, request

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────
MUSIC_FOLDER  = Path.home() / "Music"
VOLUME_STEP   = 5          # % per encoder click
SUPPORTED_EXT = (".mp4", ".mp3", ".flac", ".wav", ".ogg", ".m4a", ".aac", ".mkv", ".avi", ".webm", ".mov")

def get_audio_details(file_path):
    """Use ffprobe to get technical details (sample rate, bit depth)."""
    try:
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "stream=codec_type,sample_rate,bits_per_sample,channels:format=format_name,bit_rate,duration",
            "-of", "json", file_path
        ]
        result = subprocess.check_output(cmd, timeout=3).decode("utf-8")
        data = json.loads(result)
        
        streams = data.get("streams", [])
        audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})
        fmt = data.get("format", {})
        
        return {
            "sample_rate": audio_stream.get("sample_rate"),
            "bit_depth": audio_stream.get("bits_per_sample"),
            "channels": audio_stream.get("channels"),
            "format": fmt.get("format_name"),
            "bit_rate": fmt.get("bit_rate"),
            "duration": float(fmt.get("duration", 0) if fmt.get("duration") else 0)
        }
    except Exception:
        return {}

ALSA_MIXER    = "Digital"  # PCM5122 default; falls back to Master
WEB_PORT      = 5000

CLK_PIN = 17
DT_PIN  = 27
SW_PIN  = 22

# ─────────────────────────────────────────────────────────────
# ALSA volume helpers
# ─────────────────────────────────────────────────────────────
def _detect_mixer() -> str:
    for name in [ALSA_MIXER, "Master", "Playback", "PCM"]:
        try:
            subprocess.check_output(["amixer", "get", name], stderr=subprocess.DEVNULL)
            return name
        except subprocess.CalledProcessError:
            continue
    return "Master"

MIXER = _detect_mixer()

def get_volume() -> int:
    try:
        out = subprocess.check_output(["amixer", "get", MIXER],
                                      stderr=subprocess.DEVNULL).decode()
        for line in out.splitlines():
            if "%" in line:
                return int(line[line.index("[") + 1 : line.index("%")])
    except Exception:
        pass
    return 50

def set_volume(value: int) -> int:
    value = max(0, min(100, value))
    try:
        subprocess.run(["amixer", "set", MIXER, f"{value}%"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    return value

# ─────────────────────────────────────────────────────────────
# mpv Player (no display server — uses KMS/DRM directly)
# ─────────────────────────────────────────────────────────────
class Player:
    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._current: Path | None = None
        self._lock = threading.Lock()

    @property
    def current(self) -> Path | None:
        return self._current

    def play(self, path: Path):
        with self._lock:
            self._stop_internal()
            self._current = path
            self._proc = subprocess.Popen(
                [
                    "mpv",
                    "--vo=drm",          # Direct framebuffer — no X needed
                    "--ao=alsa",         # ALSA audio output
                    "--really-quiet",
                    "--no-terminal",
                    "--input-ipc-server=/tmp/mpv-music_player",
                    str(path),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def pause(self):
        with self._lock:
            self._send_ipc(["set_property", "pause", True])

    def resume(self):
        with self._lock:
            self._send_ipc(["set_property", "pause", False])

    def set_video(self, enabled: bool):
        with self._lock:
            self._send_ipc(["set_property", "vid", "auto" if enabled else "no"])

    def seek(self, position: float):
        with self._lock:
            self._send_ipc(["seek", position, "absolute"])

    def get_property(self, prop_name: str):
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(1.0)
            client.connect("/tmp/mpv-music_player")
            client.send((json.dumps({"command": ["get_property", prop_name]}) + "\n").encode())
            
            buf = b""
            while True:
                chunk = client.recv(4096)
                if not chunk: break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line: continue
                    try:
                        msg = json.loads(line.decode("utf-8"))
                        if "error" in msg and "event" not in msg:
                            client.close()
                            return msg.get("data")
                    except Exception:
                        pass
            client.close()
        except Exception:
            pass
        return None

    def _send_ipc(self, command: list):
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.connect("/tmp/mpv-music_player")
            client.send((json.dumps({"command": command}) + "\n").encode())
            client.close()
        except Exception:
            pass

    def stop(self):
        with self._lock:
            self._stop_internal()
            self._current = None

    def _stop_internal(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    def is_playing(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def poll(self):
        """Call periodically — clears state when mpv finishes naturally."""
        with self._lock:
            if self._proc and self._proc.poll() is not None:
                self._proc = None
                self._current = None

# ─────────────────────────────────────────────────────────────
# App State
# ─────────────────────────────────────────────────────────────
player       = Player()
volume       = get_volume()
selected_idx = 0   # cursor for rotary encoder navigation

def scan_music() -> list[dict]:
    if not MUSIC_FOLDER.exists():
        return []
        
    songs = []
    for f in sorted(MUSIC_FOLDER.iterdir()):
        if f.suffix.lower() in SUPPORTED_EXT:
            tech = get_audio_details(str(f))
            songs.append({
                "path": f,
                "name": f.name,
                "stem": f.stem,
                "suffix": f.suffix,
                "tech": tech
            })
    return songs

# ─────────────────────────────────────────────────────────────
# Rotary Encoder (optional — silently skipped on dev PC)
# ─────────────────────────────────────────────────────────────
def _setup_encoder():
    global volume, selected_idx
    try:
        from gpiozero import RotaryEncoder, Button
    except Exception:
        return  # Not on Pi or gpiozero not installed

    encoder = RotaryEncoder(CLK_PIN, DT_PIN, max_steps=0)
    sw      = Button(SW_PIN, pull_up=True)
    _last_press = [0.0]
    _press_count = [0]

    def on_cw():
        global volume, selected_idx
        if player.is_playing():
            volume = set_volume(volume + VOLUME_STEP)
        else:
            songs = scan_music()
            if songs:
                selected_idx = (selected_idx + 1) % len(songs)

    def on_ccw():
        global volume, selected_idx
        if player.is_playing():
            volume = set_volume(volume - VOLUME_STEP)
        else:
            songs = scan_music()
            if songs:
                selected_idx = (selected_idx - 1) % len(songs)

    def on_press():
        now = time.time()
        if now - _last_press[0] < 3.0:
            _press_count[0] += 1
        else:
            _press_count[0] = 1
        _last_press[0] = now

        if _press_count[0] >= 2:
            _press_count[0] = 0
            # Double-click: stop
            player.stop()
        else:
            # Single-click: play selected / toggle stop
            if player.is_playing():
                player.stop()
            else:
                songs = scan_music()
                if songs and selected_idx < len(songs):
                    player.play(songs[selected_idx]["path"])

    encoder.when_rotated_clockwise         = on_cw
    encoder.when_rotated_counter_clockwise = on_ccw
    sw.when_pressed = on_press

def _poll_loop():
    """Background thread — keeps player state fresh."""
    while True:
        player.poll()
        time.sleep(1)

# ─────────────────────────────────────────────────────────────
# Flask Web UI
# ─────────────────────────────────────────────────────────────
app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🎵 Pi Music Console</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap');

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:      #0d0d1a;
    --surface: #161628;
    --card:    #1e1e38;
    --accent:  #7c3aed;
    --accent2: #a855f7;
    --green:   #22c55e;
    --red:     #ef4444;
    --text:    #e2e8f0;
    --muted:   #7c7c9a;
    --border:  #2d2d52;
  }

  body {
    font-family: 'Inter', sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    padding-bottom: 2rem;
  }

  /* ── Header ── */
  header {
    background: linear-gradient(135deg, #1a0533 0%, #0d0d1a 100%);
    border-bottom: 1px solid var(--border);
    padding: 1rem 1.5rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 100;
    backdrop-filter: blur(12px);
  }

  .logo { font-size: 1.25rem; font-weight: 700; color: var(--accent2); }
  .logo span { color: var(--text); }

  .stats {
    display: flex;
    gap: 1rem;
    font-size: 0.8rem;
    color: var(--muted);
  }
  .stats .pill {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 0.25rem 0.75rem;
    display: flex;
    align-items: center;
    gap: 0.4rem;
  }

  /* ── Now playing bar ── */
  #now-playing-bar {
    background: linear-gradient(90deg, #2e1065, #1e1e38);
    border-bottom: 1px solid var(--border);
    padding: 0.75rem 1.5rem;
    display: flex;
    align-items: center;
    gap: 1rem;
    min-height: 60px;
    transition: background 0.4s;
  }

  #now-playing-bar.idle { background: var(--surface); }

  .now-icon {
    width: 36px; height: 36px;
    background: var(--accent);
    border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 1rem;
    flex-shrink: 0;
    animation: spin 3s linear infinite;
  }
  .now-icon.paused { animation-play-state: paused; background: var(--muted); }

  @keyframes spin {
    from { transform: rotate(0deg); }
    to   { transform: rotate(360deg); }
  }

  #now-title {
    flex: 1;
    font-weight: 600;
    font-size: 0.95rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  /* ── Controls ── */
  .controls {
    padding: 1rem 1.5rem;
    display: flex;
    gap: 0.75rem;
    align-items: center;
    flex-wrap: wrap;
  }

  .btn {
    border: none;
    border-radius: 0.6rem;
    padding: 0.6rem 1.2rem;
    font-family: inherit;
    font-size: 0.9rem;
    font-weight: 600;
    cursor: pointer;
    transition: transform 0.1s, opacity 0.2s;
  }
  .btn:active { transform: scale(0.96); }

  .btn-stop  { background: var(--red);    color: #fff; }
  .btn-action { background: var(--accent); color: #fff; }
  .btn-action:hover { background: var(--accent2); }

  .vol-display {
    margin-left: auto;
    font-size: 1rem;
    font-weight: 700;
    color: var(--accent2);
    min-width: 50px;
    text-align: right;
  }

  input[type=range] {
    flex: 1;
    -webkit-appearance: none;
    height: 6px;
    background: var(--border);
    border-radius: 3px;
    outline: none;
  }
  input[type=range]::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    background: var(--accent2);
    cursor: pointer;
    box-shadow: 0 0 10px rgba(168, 85, 247, 0.5);
  }
  .volume-controls {
    display: flex;
    align-items: center;
    gap: 1rem;
    padding: 0.5rem 1.5rem;
    width: 100%;
    max-width: 500px;
  }

  /* ── Song list ── */
  .section-title {
    padding: 0.75rem 1.5rem 0.4rem;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--muted);
  }

  #song-list { padding: 0 1rem; }

  .song-item {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 0.75rem;
    padding: 0.8rem 1rem;
    margin-bottom: 0.5rem;
    cursor: pointer;
    transition: border-color 0.2s, background 0.2s, transform 0.15s;
    -webkit-tap-highlight-color: transparent;
  }
  .song-item:active { transform: scale(0.98); }
  .song-item:hover  { border-color: var(--accent); background: #23234a; }
  .song-item.playing {
    border-color: var(--accent2);
    background: linear-gradient(90deg, #2e1065 0%, #1e1e38 100%);
  }
  .song-item.playing .song-icon { color: var(--accent2); }

  .song-icon { font-size: 1.2rem; flex-shrink: 0; }
  .song-name { font-size: 0.95rem; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .song-ext  { font-size: 0.7rem; color: var(--muted); background: var(--surface);
               border: 1px solid var(--border); border-radius: 4px; padding: 0.1rem 0.4rem; flex-shrink: 0; }

  .empty { text-align: center; color: var(--muted); padding: 3rem 1rem; font-size: 0.95rem; }

  /* ── Toast ── */
  #toast {
    position: fixed; bottom: 1.5rem; left: 50%; transform: translateX(-50%);
    background: var(--accent); color: #fff;
    padding: 0.6rem 1.4rem; border-radius: 999px;
    font-size: 0.85rem; font-weight: 600;
    opacity: 0; pointer-events: none;
    transition: opacity 0.3s;
    z-index: 999;
  }
  #toast.show { opacity: 1; }
</style>
</head>
<body>

<header>
  <div class="logo">🎵 <span>Pi Music Console</span></div>
</header>

<div id="now-playing-bar" class="idle">
  <div class="now-icon paused" id="disc-icon">💿</div>
  <div id="now-title" style="color:var(--muted)">Nothing playing</div>
</div>

<div class="controls">
  <button class="btn btn-action" onclick="resumeMusic()" title="Play">▶ Play</button>
  <button class="btn btn-action" onclick="pauseMusic()" title="Pause">⏸ Pause</button>
  <button class="btn btn-stop" onclick="stopMusic()">⏹ Stop</button>
  <button class="btn btn-action" id="btn-video" onclick="toggleVideo()" title="Toggle Video" style="background: var(--accent2);">📺 Video On</button>
</div>

<!-- Seek Bar -->
<div class="seek-container" style="display:flex; align-items:center; gap:12px; padding: 0 1.5rem; max-width: 500px; margin-bottom: 0.5rem; margin-top: 1rem;">
  <span id="seek-current" style="font-size:0.85rem; font-weight:600; color:var(--muted); min-width:40px;">0:00</span>
  <input type="range" id="seek-slider" min="0" max="100" value="0"
         onmousedown="window.seekDragging=true"
         ontouchstart="window.seekDragging=true"
         onmouseup="onSeekRelease()"
         ontouchend="onSeekRelease()"
         oninput="updateSeekDisplay(this.value)">
  <span id="seek-total" style="font-size:0.85rem; font-weight:600; color:var(--muted); min-width:40px;">0:00</span>
</div>
<div class="controls volume-controls">
  <span style="font-size:1.2rem">🔉</span>
  <input type="range" id="volume-slider" min="0" max="100" value="50" oninput="setVolumeUI(this.value)" onchange="sendVolume(this.value)">
  <div class="vol-display" id="vol-display">50%</div>
</div>

<div class="section-title">Library — {{ count }} file{{ 's' if count != 1 else '' }}</div>
<div id="song-list">
  {% if songs %}
    {% for song in songs %}
    <div class="song-item" id="song-{{ loop.index0 }}" onclick="playSong('{{ song.name | e }}')">
      <span class="song-icon">{% if song.suffix in ['.mp4', '.m4a', '.mkv', '.avi', '.mov', '.webm'] %}🎬{% else %}🎵{% endif %}</span>
      <span class="song-name">
        {{ song.stem }}
        {% set techStr = "" %}
        {% if song.tech.sample_rate %}{% set techStr = techStr ~ (song.tech.sample_rate|int / 1000)|round(1) ~ "kHz" %}{% endif %}
        {% if song.tech.bit_rate %}{% set techStr = techStr ~ (" • " if techStr else "") ~ (song.tech.bit_rate|int / 1000)|round ~ "kbps" %}{% endif %}
        {% if techStr %}<br><span style="font-size:0.75rem; color:var(--green)">{{ (song.tech.format or 'UNK') | upper }} • {{ techStr }}</span>{% else %}<br><span style="font-size:0.75rem; color:var(--muted)">{{ (song.tech.format or 'UNK') | upper }}</span>{% endif %}
      </span>
    </div>
    {% endfor %}
  {% else %}
    <div class="empty">
      <p>📂 No music files found in <code>~/Music</code></p>
      <p style="margin-top:0.5rem; font-size:0.8rem;">Copy .mp3 / .flac / .mp4 / .wav files there, then refresh.</p>
    </div>
  {% endif %}
</div>

<div id="toast"></div>

<script>
let currentFile = null;
window.seekDragging = false;
let currentDuration = 0;
let videoEnabled = true;

function toggleVideo() {
  videoEnabled = !videoEnabled;
  fetch('/video_set', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({enabled: videoEnabled})
  });
  updateVideoButton();
  showToast(videoEnabled ? '📺 Video On' : '📺 Video Off');
}

function updateVideoButton() {
  const btn = document.getElementById('btn-video');
  if (videoEnabled) {
    btn.textContent = '📺 Video On';
    btn.style.background = 'var(--accent2)';
  } else {
    btn.textContent = '📺 Video Off';
    btn.style.background = 'var(--surface)';
    btn.style.color = 'var(--text)';
  }
}

function formatTime(secs) {
    if (!secs || isNaN(secs)) return '0:00';
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
}

function updateSeekDisplay(sliderVal) {
    const pos = (sliderVal / 100) * currentDuration;
    document.getElementById('seek-current').textContent = formatTime(pos);
}

async function onSeekRelease() {
    window.seekDragging = false;
    const slider = document.getElementById('seek-slider');
    const position = (slider.value / 100) * currentDuration;
    await fetch('/seek', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ position: position })
    });
}

function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2000);
}

async function playSong(filename) {
  const r = await fetch('/play', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({filename})
  });
  const d = await r.json();
  if (d.ok) {
    currentFile = filename;
    updateUI(filename);
    showToast('▶ ' + filename);
  }
}

async function stopMusic() {
  await fetch('/stop', {method: 'POST'});
  currentFile = null;
  updateUI(null);
  showToast('⏹ Stopped');
}

async function pauseMusic() {
  await fetch('/pause', {method: 'POST'});
  showToast('⏸ Paused');
}

async function resumeMusic() {
  await fetch('/resume', {method: 'POST'});
  showToast('▶ Resumed');
}

function setVolumeUI(val) {
  document.getElementById('vol-display').textContent = val + '%';
}

async function sendVolume(val) {
  const r = await fetch('/volume_set', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({volume: val})
  });
  const d = await r.json();
  document.getElementById('vol-display').textContent = d.volume + '%';
  showToast('Volume: ' + d.volume + '%');
}

function updateUI(filename) {
  const bar   = document.getElementById('now-playing-bar');
  const title = document.getElementById('now-title');
  const disc  = document.getElementById('disc-icon');

  // Clear all highlights
  document.querySelectorAll('.song-item').forEach(el => el.classList.remove('playing'));

  if (filename) {
    bar.classList.remove('idle');
    title.textContent = filename;
    title.style.color = '';
    disc.classList.remove('paused');

    // Highlight matching row
    document.querySelectorAll('.song-item').forEach(el => {
      if (el.onclick.toString().includes(filename.replace(/'/g, "\\'"))) {
        el.classList.add('playing');
      }
    });
  } else {
    bar.classList.add('idle');
    title.textContent = 'Nothing playing';
    title.style.color = 'var(--muted)';
    disc.classList.add('paused');
  }
}

// Poll status every 2 seconds
async function pollStatus() {
  try {
    const r = await fetch('/status');
    const d = await r.json();
    document.getElementById('vol-display').textContent = d.volume + '%';
    
    // Only update slider if not dragging it actively (to prevent jumping)
    if (!document.getElementById('volume-slider').matches(':active')) {
        document.getElementById('volume-slider').value = d.volume;
    }

    if (d.playing !== currentFile) {
      currentFile = d.playing;
      updateUI(d.playing);
    }
    
    // Sync video toggle state
    if (d.video_enabled !== undefined && d.video_enabled !== videoEnabled) {
      videoEnabled = d.video_enabled;
      updateVideoButton();
    }
    
    currentDuration = d.duration || 0;
    if (!window.seekDragging) {
        document.getElementById('seek-total').textContent = formatTime(d.duration);
        document.getElementById('seek-current').textContent = formatTime(d.position);
        if (d.duration > 0) {
            document.getElementById('seek-slider').value = (d.position / d.duration) * 100;
        } else {
            document.getElementById('seek-slider').value = 0;
        }
    }
  } catch(e) {}
  setTimeout(pollStatus, 2000);
}

pollStatus();
</script>
</body>
</html>
"""

@app.route("/")
def index():
    songs = scan_music()
    return render_template_string(HTML, songs=songs, count=len(songs))

@app.route("/play", methods=["POST"])
def play():
    filename = request.json.get("filename", "")
    path = MUSIC_FOLDER / filename
    if path.exists() and path.suffix.lower() in SUPPORTED_EXT:
        player.play(path)
        return jsonify(ok=True, filename=filename)
    return jsonify(ok=False, error="File not found"), 404

@app.route("/stop", methods=["POST"])
def stop():
    player.stop()
    return jsonify(ok=True)

@app.route("/pause", methods=["POST"])
def pause_route():
    player.pause()
    return jsonify(ok=True)

@app.route("/resume", methods=["POST"])
def resume_route():
    player.resume()
    return jsonify(ok=True)

@app.route("/video_set", methods=["POST"])
def video_set_route():
    enabled = request.json.get("enabled", True)
    player.set_video(enabled)
    return jsonify(ok=True)

@app.route("/volume_set", methods=["POST"])
def volume_set_route():
    global volume
    val = int(request.json.get("volume", 50))
    volume = set_volume(val)
    return jsonify(volume=volume)

@app.route("/seek", methods=["POST"])
def seek_route():
    position = request.json.get("position", 0)
    try:
        position = float(position)
    except (TypeError, ValueError):
        return jsonify(error="Invalid position"), 400
    player.seek(position)
    return jsonify(ok=True)

@app.route("/status")
def status():
    current = player.current
    duration = player.get_property("duration") if current else 0
    position = player.get_property("time-pos") if current else 0
    vid = player.get_property("vid") if current else "auto"
    return jsonify(
        playing=current.name if current else None,
        volume=volume,
        duration=round(float(duration), 2) if duration else 0,
        position=round(float(position), 2) if position else 0,
        video_enabled=(vid != "no"),
    )

# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    _setup_encoder()
    threading.Thread(target=_poll_loop, daemon=True).start()
    print(f"Pi Music Console running → http://0.0.0.0:{WEB_PORT}")
    app.run(host="0.0.0.0", port=WEB_PORT, debug=False, use_reloader=False)
