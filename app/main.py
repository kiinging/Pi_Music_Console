import os
import socket
import json
import subprocess
import time
import logging
import math
import sys
import threading
from pathlib import Path
from flask import Flask, render_template, jsonify, request

try:
    from mutagen import File
except ImportError:
    File = None

app = Flask(__name__)

# ── Suppress noisy /api/status poll from logs ─────────────────────────────
class _SuppressStatusFilter(logging.Filter):
    def filter(self, record):
        return '/api/status' not in record.getMessage()

logging.getLogger('werkzeug').addFilter(_SuppressStatusFilter())

# --- Metadata Caching ---
TECH_CACHE = {}
META_CACHE = {}

# Paths (Professional Structure)
# app/main.py is inside 'app/' folder, so project root is parent
BASE_DIR = Path(__file__).parent.parent
METADATA_FILE = BASE_DIR / "music_metadata.json"
MUSIC_DIR = os.path.expanduser("~/Music")
VIDEO_DIR = os.path.expanduser("~/video")
if not os.path.exists(VIDEO_DIR) and os.path.exists(os.path.expanduser("~/Videos")):
    VIDEO_DIR = os.path.expanduser("~/Videos")

IPC_SOCKET = "/tmp/mpvsocket"

def get_track_metadata(file_path):
    if file_path in META_CACHE: return META_CACHE[file_path]
    metadata = {"title": os.path.basename(file_path), "artist": "Unknown Artist", "album": "Unknown Album"}
    if File:
        try:
            audio = File(file_path)
            if audio:
                tags = audio.tags if hasattr(audio, 'tags') else audio
                if tags:
                    metadata["title"] = str(tags.get('title', [metadata["title"]])[0])
                    metadata["artist"] = str(tags.get('artist', ["Unknown Artist"])[0])
                    metadata["album"] = str(tags.get('album', ["Unknown Album"])[0])
        except Exception: pass
    META_CACHE[file_path] = metadata
    return metadata

class MpvPlayer:
    def __init__(self, socket_path):
        self.socket_path = socket_path
        self.proc = None
        self.lock = threading.Lock()

    def stop(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                try: self._send_command(["quit"]); time.sleep(0.1)
                except: pass
                if self.proc and self.proc.poll() is None:
                    self.proc.terminate()
                    try: self.proc.wait(timeout=1)
                    except: self.proc.kill()
            try: subprocess.run(["pkill", "-9", "mpv"], stderr=subprocess.DEVNULL)
            except: pass
            if os.path.exists(self.socket_path):
                try: os.remove(self.socket_path)
                except: pass
            self.proc = None

    def start(self, file_path, env_vars=None):
        self.stop()
        with self.lock:
            env = os.environ.copy()
            if env_vars: env.update(env_vars)
            cmd = ["mpv", "--fullscreen", "--force-window=yes", "--keep-open=no", "--idle=no", "--osc=no", "--no-border", "--no-terminal", "--really-quiet", "--gpu-context=wayland", "--vo=gpu-next", "--hwdec=auto-safe", "--video-sync=display-resample", "--audio-display=no", "--stop-screensaver=yes", "--input-ipc-server=" + self.socket_path, "--ao=alsa", file_path]
            self.proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(30):
                if os.path.exists(self.socket_path): return True
                time.sleep(0.1)
            return False

    def _send_command(self, command_list):
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(0.5); client.connect(self.socket_path)
            client.send((json.dumps({"command": command_list}) + "\n").encode())
            client.close()
            return True
        except: return False

    def query(self, command_list):
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(1.5); client.connect(self.socket_path)
            client.send((json.dumps({"command": command_list}) + "\n").encode())
            buf = b""
            while True:
                chunk = client.recv(4096)
                if not chunk: break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip(): continue
                    try:
                        msg = json.loads(line.decode("utf-8"))
                        if "event" in msg: continue
                        if "error" in msg:
                            client.close(); return msg.get("data")
                    except: continue
            client.close()
        except: pass
        return None

    def is_alive(self):
        return self.proc is not None and self.proc.poll() is None

player = MpvPlayer(IPC_SOCKET)

def load_metadata():
    if METADATA_FILE.exists():
        try:
            with open(METADATA_FILE, 'r', encoding='utf-8') as f: return json.load(f)
        except Exception: return {}
    return {}

def detect_mixer():
    for name in ["Digital", "Master", "Playback", "HDMI"]:
        try:
            subprocess.check_output(["amixer", "get", name], stderr=subprocess.DEVNULL)
            return name
        except: continue
    return "Master"

MIXER_NAME = detect_mixer()

def get_current_volume():
    try:
        out = subprocess.check_output(["amixer", "get", MIXER_NAME], stderr=subprocess.DEVNULL).decode()
        for line in out.splitlines():
            if "%" in line:
                start, end = line.index("[") + 1, line.index("%")
                hw_val = int(line[start:end])
                L = 0.5
                return max(0, min(100, round((math.log10((hw_val / 100) * (10**L - 1) + 1) / L) * 100)))
    except: pass
    return 50

def set_system_volume(slider_val):
    slider_val = max(0, min(100, int(slider_val)))
    L = 0.5
    hw_val = int(((10**(L * slider_val / 100) - 1) / (10**L - 1)) * 100)
    try: subprocess.run(["amixer", "set", MIXER_NAME, f"{hw_val}%"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); return slider_val
    except: return None

# ── API Routes ─────────────────────────────────────────────────────────────

@app.route("/api/ping")
def ping(): return jsonify({"status": "Pong!", "version": "3.0 (Professional)"})

@app.route("/")
def index(): return render_template("desktop.html")

@app.route("/csi")
def csi_console(): return render_template("touch.html")

@app.route("/api/songs")
def list_songs():
    dirs = [(MUSIC_DIR, 'music'), (VIDEO_DIR, 'video')]
    songs = []
    exts = ('.mp3', '.flac', '.wav', '.m4a', '.ogg', '.mp4', '.mkv', '.avi', '.mov', '.webm')
    p_meta = load_metadata()
    for b_dir, _ in dirs:
        if os.path.exists(b_dir):
            for root, _, files in os.walk(b_dir):
                for f in files:
                    if f.lower().endswith(exts):
                        f_path = os.path.join(root, f)
                        rel = os.path.relpath(f_path, b_dir)
                        typ = 'video' if f.lower().endswith(('.mkv', '.mp4', '.webm', '.avi', '.mov')) else 'music'
                        meta, tech = get_track_metadata(f_path), get_audio_details(f_path)
                        if rel in p_meta:
                            for field in ["title", "category", "artist", "year", "rating"]:
                                if field in p_meta[rel]: meta[field] = p_meta[rel][field]
                        songs.append({"path": rel, "type": typ, "filename": f, "title": meta.get("title", f), "artist": meta.get("artist", "Unknown Artist"), "category": meta.get("category", "All"), "year": meta.get("year", ""), "rating": meta.get("rating", 0), "tech": tech})
    songs.sort(key=lambda x: x['title'].lower())
    return jsonify(songs)

@app.route("/api/play", methods=["POST"])
def play_song():
    data = request.json
    p, t = data.get("path"), data.get("type", "music")
    f_path = os.path.join(VIDEO_DIR if t == 'video' else MUSIC_DIR, p)
    if not os.path.exists(f_path): f_path = os.path.join(MUSIC_DIR if t == 'video' else VIDEO_DIR, p)
    if not os.path.exists(f_path): return jsonify({"error": "File not found"}), 404
    player.start(f_path, {"WAYLAND_DISPLAY": "wayland-0", "XDG_RUNTIME_DIR": "/tmp/weston-runtime"})
    return jsonify({"status": "success"})

@app.route("/api/status")
def status():
    if not player.is_alive(): return jsonify({"status": "error"}), 200
    pos, dur, pz, path = player.query(["get_property", "time-pos"]), player.query(["get_property", "duration"]), player.query(["get_property", "pause"]), player.query(["get_property", "path"])
    meta = get_track_metadata(path) if path else {}
    vid = player.query(["get_property", "vid"])
    return jsonify({ "position": pos or 0, "duration": dur or 0, "paused": pz, "title": meta.get("title"), "artist": meta.get("artist"), "video_enabled": str(vid).lower() not in ("no", "false", "none", ""), "voice_enabled": VOICE_PROCESS is not None })

@app.route("/api/video/toggle", methods=["POST"])
def video_toggle():
    current_vid = player.query(["get_property", "vid"])
    is_enabled = (str(current_vid).lower() not in ("no", "false", "none"))
    new_state = "no" if is_enabled else "auto"
    player._send_command(["set_property", "vid", new_state])
    return jsonify({"video_enabled": new_state == "auto"})

@app.route("/api/volume", methods=["GET", "POST"])
def volume_api():
    if request.method == "POST":
        val = request.json.get("volume")
        new_val = set_system_volume(val)
        return jsonify({"volume": new_val})
    else: return jsonify({"volume": get_current_volume()})

# ── Voice Control (ReSpeaker XVF3800) ────────────────────────────────────────

VOICE_PROCESS = None

@app.route("/api/voice/toggle", methods=["POST"])
def voice_toggle():
    global VOICE_PROCESS
    enabled = request.json.get("enabled", False)
    if enabled:
        if VOICE_PROCESS is None:
            # Future: Start XVF3800 listener process here
            # Example: VOICE_PROCESS = subprocess.Popen(["python3", "../voice/listener.py"])
            VOICE_PROCESS = "SIMULATED_ACTIVE" # Placeholder
            return jsonify({"status": "Voice service started", "enabled": True})
    else:
        if VOICE_PROCESS:
            # VOICE_PROCESS.terminate()
            VOICE_PROCESS = None
            return jsonify({"status": "Voice service stopped", "enabled": False})
    return jsonify({"status": "No change", "enabled": VOICE_PROCESS is not None})

# ── System Control ──────────────────────────────────────────────────────────

@app.route("/api/system/screen_toggle", methods=["POST"])
def screen_toggle():
    paths = ["/sys/class/backlight/rpi_backlight/bl_power", "/sys/class/backlight/10-0045/bl_power"]
    for p in paths:
        if os.path.exists(p):
            with open(p, "r") as f: cur = f.read().strip()
            new = "1" if cur == "0" else "0"
            with open(p, "w") as f: f.write(new)
            return jsonify({"status": "success", "power": new == "0"})
    return jsonify({"status": "not_supported"})

def get_audio_details(f_path):
    if f_path in TECH_CACHE: return TECH_CACHE[f_path]
    try:
        res = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,sample_rate,bits_per_sample,channels:format=format_name,bit_rate,duration", "-of", "json", f_path], timeout=2).decode("utf-8")
        d = json.loads(res); s = next((x for x in d.get("streams", []) if x.get("codec_type") == "audio"), {}); f = d.get("format", {})
        TECH_CACHE[f_path] = {"sample_rate": s.get("sample_rate"), "bit_depth": s.get("bits_per_sample"), "format": f.get("format_name"), "bit_rate": f.get("bit_rate"), "duration": float(f.get("duration", 0) or 0)}
        return TECH_CACHE[f_path]
    except: return {}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
