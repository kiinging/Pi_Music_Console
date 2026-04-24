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
import math
import json
import sys
from pathlib import Path
from flask import Flask, jsonify, render_template_string, request, Response

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
    """Read current ALSA volume and convert back to perceptual slider value (0-100)."""
    try:
        out = subprocess.check_output(["amixer", "get", MIXER],
                                      stderr=subprocess.DEVNULL).decode()
        for line in out.splitlines():
            if "%" in line:
                hw_val = int(line[line.index("[") + 1 : line.index("%")])
                # Inverse Log mapping: slider = log10(HW/100 * (10^L - 1) + 1) / L * 100
                # Using L=1.2 for better compatibility with Class A amps & low-sens speakers
                L = 1.2
                slider_val = round((math.log10((hw_val / 100) * (10**L - 1) + 1) / L) * 100)
                return max(0, min(100, slider_val))
    except Exception:
        pass
    return 50

def set_volume(slider_val: int) -> int:
    """Set ALSA volume using a logarithmic (audio) mapping."""
    slider_val = max(0, min(100, slider_val))
    # Log mapping: HW = (10^(L * slider/100) - 1) / (10^L - 1) * 100
    L = 1.2
    hw_val = int(((10**(L * slider_val / 100) - 1) / (10**L - 1)) * 100)
    
    try:
        subprocess.run(["amixer", "set", MIXER, f"{hw_val}%"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    return slider_val

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

class SmartVoiceManager:
    def __init__(self):
        self.proc = None
        self.script_path = Path(__file__).parent / "smart_voice_unit" / "voice_controller.py"

    def is_running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        if not self.is_running() and self.script_path.exists():
            try:
                self.proc = subprocess.Popen(
                    [sys.executable, str(self.script_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=str(self.script_path.parent)
                )
                return True
            except Exception as e:
                print(f"Failed to start voice controller: {e}")
        return False

    def stop(self):
        if self.is_running():
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
            return True
        return False

smart_manager = SmartVoiceManager()

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
<html lang="en" translate="no">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="google" content="notranslate">
<title>HiFi Music Console</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;600&family=Inter:wght@400;600&display=swap');

  :root {
    --bg: #07070a;
    --card: rgba(255, 255, 255, 0.05);
    --border: rgba(255, 255, 255, 0.08);
    --accent: #b388ff;
    --accent-glow: rgba(179, 136, 255, 0.4);
    --text-main: #e0e0f0;
    --text-dim: #8a8a9a;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }

  body {
    background-color: var(--bg);
    color: var(--text-main);
    font-family: 'Inter', sans-serif;
    display: flex;
    flex-direction: column;
    min-height: 100vh;
    overflow-x: hidden;
  }

  /* Dynamic Blur Background */
  #bg-blur {
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    z-index: -1;
    background-size: cover;
    background-position: center;
    transition: background 1s ease-in-out;
  }

  /* Now Playing Header */
  header {
    text-align: center;
    padding: 3rem 1.5rem 2rem;
    background: linear-gradient(180deg, rgba(0,0,0,0.6) 0%, transparent 100%);
    backdrop-filter: blur(10px);
    border-bottom: 1px solid var(--border);
  }

  #now-title {
    font-family: 'Outfit', sans-serif;
    font-size: 1.2rem;
    font-weight: 600;
    margin-bottom: 0.5rem;
  }

  .badges {
    display: flex; justify-content: center; gap: 8px; margin-top: 10px;
  }
  .badge {
    background: var(--card); border: 1px solid var(--border);
    padding: 6px 14px; border-radius: 12px; font-size: 0.75rem; color: var(--text-dim);
  }

  /* Controls */
  .controls-row {
    display: flex; justify-content: center; gap: 1rem; margin: 1.5rem 0;
  }
  
  .btn-circle {
    width: 55px; height: 55px; border-radius: 50%;
    background: var(--card); border: 1px solid var(--border);
    color: white; font-size: 1.2rem;
    display: flex; align-items: center; justify-content: center;
    cursor: pointer; transition: all 0.2s;
  }
  .btn-circle:hover { background: var(--accent); box-shadow: 0 0 20px var(--accent-glow); border-color: transparent; }
  .btn-circle:active { transform: scale(0.9); }
  
  .btn-play { background: white; color: black; }
  .btn-play:hover { background: #ddd; box-shadow: 0 0 20px rgba(255,255,255,0.4); }

  /* Volume Slider Styling */
  .vol-row {
    display: flex; align-items: center; gap: 10px; margin: 1rem auto;
    max-width: 300px; background: var(--card); padding: 8px 15px;
    border-radius: 20px; border: 1px solid var(--border);
  }
  #vol-slider {
    flex: 1; -webkit-appearance: none; height: 4px;
    background: rgba(255,255,255,0.1); border-radius: 2px;
    outline: none; cursor: pointer;
  }
  #vol-slider::-webkit-slider-thumb {
    -webkit-appearance: none; width: 14px; height: 14px;
    background: var(--accent); border-radius: 50%;
    cursor: pointer; box-shadow: 0 0 8px var(--accent-glow);
  }
  .time-label, .vol-label { font-size: 0.8rem; color: var(--text-dim); }
  
  /* Smart Toggle */
  .smart-toggle {
    display: flex; align-items: center; justify-content: center; gap: 8px; margin-bottom: 10px;
    font-size: 0.7rem; text-transform: uppercase; letter-spacing: 1px; color: var(--text-dim);
  }
  .switch {
    position: relative; display: inline-block; width: 34px; height: 18px;
  }
  .switch input { opacity: 0; width: 0; height: 0; }
  .slider {
    position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0;
    background-color: #333; transition: .4s; border-radius: 34px;
  }
  .slider:before {
    position: absolute; content: ""; height: 12px; width: 12px; left: 3px; bottom: 3px;
    background-color: white; transition: .4s; border-radius: 50%;
  }
  input:checked + .slider { background-color: var(--accent); }
  input:checked + .slider:before { transform: translateX(16px); }

  /* Library */
  .library { flex: 1; padding: 1.5rem; background: rgba(0,0,0,0.4); backdrop-filter: blur(20px); }
  .lib-title { font-family: 'Outfit', sans-serif; font-size: 1.2rem; margin-bottom: 1rem; color: var(--text-main); }
  
  .song-row {
    display: flex; align-items: center; padding: 0.8rem 1rem;
    background: var(--card); border-radius: 8px; margin-bottom: 8px;
    border: 1px solid transparent; cursor: pointer; transition: all 0.2s;
  }
  .song-row:hover { background: rgba(255,255,255,0.1); border-color: var(--border); }
  .song-row.active { border-color: var(--accent); background: rgba(179, 136, 255, 0.1); }
  
  .song-info { flex: 1; overflow: hidden; }
  .song-name { font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 0.95rem; }
  .song-meta { font-size: 0.75rem; color: var(--text-dim); margin-top: 3px; }

</style>
</head>
<body>

<div id="bg-blur"></div>

<header>
  <div class="smart-toggle">
    <span>SMART MODE</span>
    <label class="switch">
      <input type="checkbox" id="smart-toggle" onchange="toggleSmart()">
      <span class="slider"></span>
    </label>
  </div>
  <div id="now-title">Ready to Play</div>
  <div class="badges" id="now-badges">
    <span class="badge" id="badge-format">STANDBY</span>
  </div>

  <div class="slider-container" style="margin-top: 1.5rem;">
    <span class="time-label" id="seek-current">0:00</span>
    <input type="range" id="seek-slider" min="0" max="100" value="0"
           onmousedown="window.seekDragging=true" ontouchstart="window.seekDragging=true"
           onmouseup="onSeekRelease()" ontouchend="onSeekRelease()"
           oninput="document.getElementById('seek-current').textContent=formatTime((this.value/100)*currentDuration)">
    <span class="time-label" id="seek-total" style="text-align: right;">0:00</span>
  </div>

  <div class="controls-row">
    <div class="btn-circle btn-play" onclick="resumeMusic()">▶</div>
    <div class="btn-circle" onclick="pauseMusic()">⏸</div>
    <div class="btn-circle" onclick="stopMusic()">⏹</div>
    <div class="btn-circle" id="btn-video" onclick="toggleVideo()" style="background: var(--accent); font-size: 1.4rem;" title="Toggle Video">📺</div>
  </div>

  <div class="vol-row">
    <span class="vol-label">🔊</span>
    <input type="range" id="vol-slider" min="0" max="100" value="50" oninput="sendVolume(this.value)">
    <span class="vol-label" id="vol-display" style="min-width: 40px; text-align: right;">50%</span>
  </div>
</header>

<div class="library">
  <div class="lib-title">My Collection</div>
  <div id="song-list">
    {% if songs %}
      {% for song in songs %}
        <div class="song-row" id="row-{{ loop.index }}" data-filename="{{ song.name | e }}" onclick="playSong(this.getAttribute('data-filename'), this.id)">
          <div class="song-info">
            <div class="song-name">{{ song.stem }}</div>
            <div class="song-meta">
              {{ (song.tech.format or 'UNKNOWN') | upper }}
              {% if song.tech.sample_rate %} • {{ (song.tech.sample_rate|int / 1000)|round(1) }}kHz{% endif %}
              {% if song.tech.bit_rate %} • {{ (song.tech.bit_rate|int / 1000)|round }}kbps{% endif %}
            </div>
          </div>
        </div>
      {% endfor %}
    {% else %}
      <div style="text-align:center; color: var(--text-dim); padding: 2rem;">No music found</div>
    {% endif %}
  </div>
</div>

<script>
let currentFile = null;
window.seekDragging = false;
let currentDuration = 0;
let videoEnabled = true;

function toggleVideo() {
  videoEnabled = !videoEnabled;
  fetch('/video_set', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({enabled: videoEnabled}) });
  updateVideoButton();
}

function updateVideoButton() {
  let btn = document.getElementById('btn-video');
  if(videoEnabled) { btn.style.background = 'var(--accent)'; btn.style.opacity = '1'; }
  else { btn.style.background = 'transparent'; btn.style.opacity = '0.5'; }
}

function formatTime(s) {
  if (!s || isNaN(s)) return '0:00';
  let m = Math.floor(s/60);
  let sec = Math.floor(s%60).toString().padStart(2,'0');
  return m+':'+sec;
}

async function playSong(filename, rowId) {
  await fetch('/play', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({filename}) });
  updateUI(filename);
}
async function stopMusic() { await fetch('/stop', {method:'POST'}); updateUI(null); }
async function pauseMusic() { await fetch('/pause', {method:'POST'}); }
async function resumeMusic() { await fetch('/resume', {method:'POST'}); }
async function onSeekRelease() {
  window.seekDragging = false;
  let pos = (document.getElementById('seek-slider').value / 100) * currentDuration;
  await fetch('/seek', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({position: pos}) });
}

let currentVolume = 50;

function setVolumeUI(v) { 
  currentVolume = v;
  document.getElementById('vol-slider').value = v;
  document.getElementById('vol-display').textContent = Math.round(v) + '%';
}

async function sendVolume(v) {
  document.getElementById('vol-display').textContent = v + '%';
  await fetch('/volume_set', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({volume: v}) });
}

function updateUI(filename) {
  document.querySelectorAll('.song-row').forEach(e => e.classList.remove('active'));
  
  if(filename) {
    document.getElementById('now-title').textContent = filename;
    document.getElementById('badge-format').textContent = 'PLAYING';
    
    document.getElementById('bg-blur').style.background = 'radial-gradient(circle at 50% 50%, rgba(179,136,255,0.15) 0%, transparent 100%)';
    
    // Highlight library and update dynamic tech badge
    document.querySelectorAll('.song-row').forEach(e => {
      if(e.getAttribute('data-filename') === filename) {
          e.classList.add('active');
          let meta = e.querySelector('.song-meta');
          if(meta) {
              document.getElementById('badge-format').innerHTML = '<span style="color:var(--accent)">▶ PLAYING</span> • ' + meta.innerHTML;
          }
      }
    });
  } else {
    document.getElementById('now-title').textContent = "Ready to Play";
    document.getElementById('badge-format').textContent = 'STANDBY';
    document.getElementById('bg-blur').style.background = "none";
  }
}

async function toggleSmart() {
  await fetch('/api/smart/toggle', { method:'POST' });
}

async function poll() {
  try {
    let r = await fetch('/status');
    let d = await r.json();
    setVolumeUI(d.volume);
    
    // Also poll smart status
    let sr = await fetch('/api/smart/status');
    let sd = await sr.json();
    document.getElementById('smart-toggle').checked = sd.running;
    
    if(d.playing !== currentFile) {
      currentFile = d.playing;
      updateUI(d.playing);
    }
    
    if(d.playing) {
      let badge = document.getElementById('badge-format');
      if (d.paused) {
          badge.innerHTML = badge.innerHTML.replace('▶ PLAYING', '⏸ PAUSED').replace('var(--accent)', '#8a8a9a');
      } else {
          badge.innerHTML = badge.innerHTML.replace('⏸ PAUSED', '▶ PLAYING').replace('#8a8a9a', 'var(--accent)');
      }
    }
    
    if(d.video_enabled !== undefined && d.video_enabled !== videoEnabled) {
      videoEnabled = d.video_enabled;
      updateVideoButton();
    }
    
    currentDuration = d.duration || 0;
    if(!window.seekDragging && currentDuration > 0) {
      document.getElementById('seek-total').textContent = formatTime(currentDuration);
      document.getElementById('seek-current').textContent = formatTime(d.position);
      document.getElementById('seek-slider').value = (d.position / currentDuration) * 100;
    }
  } catch(e) {}
  setTimeout(poll, 1500);
}
poll();
</script>
</body>
</html>
"""

@app.route("/api/cover/<path:filename>")
def cover(filename):
    path = MUSIC_FOLDER / filename
    if not path.exists():
        return jsonify(error="File not found"), 404
    try:
        cmd = ["ffmpeg"]
        if path.suffix.lower() in ['.mkv', '.mp4', '.avi', '.mov', '.webm']:
            cmd.extend(["-ss", "00:00:05"]) # Skip 5 seconds into the video to avoid black fade-in screens
        cmd.extend(["-i", str(path), "-an", "-vframes", "1", "-c:v", "mjpeg", "-f", "image2", "pipe:1"])
        
        pic_bytes = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=2)
        if pic_bytes:
            return Response(pic_bytes, mimetype="image/jpeg", headers={"Cache-Control": "max-age=86400"})
    except Exception:
        pass
    transparent_gif = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
    return Response(transparent_gif, mimetype="image/gif", headers={"Cache-Control": "max-age=86400"})

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
    paused = player.get_property("pause") if current else False
    return jsonify(
        playing=current.name if current else None,
        volume=volume,
        duration=round(float(duration), 2) if duration else 0,
        position=round(float(position), 2) if position else 0,
        video_enabled=(str(vid).lower() not in ("no", "false")),
        paused=bool(paused)
    )

@app.route("/api/smart/status")
def smart_status():
    return jsonify(running=smart_manager.is_running())

@app.route("/api/smart/toggle", methods=["POST"])
def smart_toggle():
    if smart_manager.is_running():
        smart_manager.stop()
    else:
        smart_manager.start()
    return jsonify(running=smart_manager.is_running())

# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    _setup_encoder()
    threading.Thread(target=_poll_loop, daemon=True).start()
    print(f"Pi Music Console running → http://0.0.0.0:{WEB_PORT}")
    app.run(host="0.0.0.0", port=WEB_PORT, debug=False, use_reloader=False)
