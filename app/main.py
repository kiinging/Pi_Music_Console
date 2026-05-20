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
from flask import Flask, render_template, jsonify, request, send_file

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
PERMANENT_CACHE = {} # Loaded from disk

# Paths (Professional Structure)
# app/main.py is inside 'app/' folder, so project root is parent
BASE_DIR = Path(__file__).parent.parent
METADATA_FILE = BASE_DIR / "music_metadata.json"
STATE_FILE = BASE_DIR / "system_state.json"
# Media Sources (Organized Structure)
MEDIA_SOURCES = [
    {"path": os.path.expanduser("~/Music"), "type": "music"},  # Primary Music (FLAC/MP3)
    {"path": os.path.expanduser("~/Video"), "type": "video"},  # Primary Video
    {"path": os.path.expanduser("~/video"), "type": "video"},  # Fallback
    {"path": os.path.expanduser("~/Videos"), "type": "video"}, # Fallback
]

# Legacy constants for compatibility where needed (using first valid path)
MUSIC_DIR = next((s["path"] for s in MEDIA_SOURCES if s["type"] == "music" and os.path.exists(s["path"])), os.path.expanduser("~/Music"))
VIDEO_DIR = next((s["path"] for s in MEDIA_SOURCES if s["type"] == "video" and os.path.exists(s["path"])), os.path.expanduser("~/Videos"))

IPC_SOCKET = "/tmp/mpvsocket"

def get_track_metadata(file_path):
    if file_path in META_CACHE: return META_CACHE[file_path]
    metadata = {"title": os.path.basename(file_path), "artist": "Unknown Artist", "album": "Unknown Album", "track_number": 0}
    if File:
        try:
            audio = File(file_path)
            if audio:
                tags = audio.tags if hasattr(audio, 'tags') else audio
                if tags:
                    metadata["title"] = str(tags.get('title', [metadata["title"]])[0])
                    metadata["artist"] = str(tags.get('artist', ["Unknown Artist"])[0])
                    metadata["album"] = str(tags.get('album', ["Unknown Album"])[0])
                    # Track number for ordering within album
                    tn_raw = tags.get('tracknumber', tags.get('track', ["0"]))
                    tn_str = str(tn_raw[0]) if tn_raw else "0"
                    metadata["track_number"] = int(tn_str.split('/')[0]) if tn_str.split('/')[0].isdigit() else 0
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
        # If already running, just load the new file via IPC (much faster/smoother)
        if self.is_alive():
            if self._send_command(["loadfile", file_path]):
                return True

        self.stop()
        with self.lock:
            env = os.environ.copy()
            if env_vars: env.update(env_vars)
            # Use flags for better performance on Pi 5
            cmd = [
                "mpv", 
                "--fullscreen", 
                "--force-window=yes", 
                "--keep-open=no", 
                "--idle=yes", # Keep alive even when nothing playing
                "--osc=no", 
                "--no-border", 
                "--no-terminal", 
                "--really-quiet", 
                "--gpu-context=wayland", 
                "--vo=gpu", 
                "--hwdec=auto-safe",
                "--audio-display=no", 
                "--stop-screensaver=yes", 
                "--input-ipc-server=" + self.socket_path,
                "--ao=alsa", 
                file_path
            ]
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

    def get_properties(self, props):
        """Fetch multiple properties in a single connection to reduce overhead."""
        results = {p: None for p in props}
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(1.0)
            client.connect(self.socket_path)
            
            # Send all requests at once
            for p in props:
                req = {"command": ["get_property", p]}
                client.send((json.dumps(req) + "\n").encode())
            
            # Read responses
            found = 0
            buf = b""
            while found < len(props):
                chunk = client.recv(4096)
                if not chunk: break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip(): continue
                    try:
                        msg = json.loads(line.decode("utf-8"))
                        if "event" in msg: continue
                        # Match response to property based on order (mpv returns them in order)
                        results[props[found]] = msg.get("data")
                        found += 1
                        if found >= len(props): break
                    except: continue
            client.close()
        except: pass
        return results

    def query(self, command_list):
        try:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(1.0); client.connect(self.socket_path)
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
    # Priority 1: Look for PCM5122 / HiFi DAC specific mixers first ("Digital" or "Analogue")
    for card in range(3):
        for name in ["Digital", "Analogue"]:
            try:
                subprocess.check_output(["amixer", "-c", str(card), "get", name], stderr=subprocess.DEVNULL)
                print(f"[*] Audio: Found DAC mixer '{name}' on card {card}")
                return f"-c {card} sset {name}"
            except: continue
            
    # Priority 2: General mixers (HDMI, Master, etc.)
    for card in range(3):
        for name in ["Master", "Playback", "HDMI", "Speaker"]:
            try:
                subprocess.check_output(["amixer", "-c", str(card), "get", name], stderr=subprocess.DEVNULL)
                print(f"[*] Audio: Found general mixer '{name}' on card {card}")
                return f"-c {card} sset {name}"
            except: continue
            
    return "sset Master"

MIXER_CMD = detect_mixer()

def load_system_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as f:
                data = json.load(f)
                if "cache" not in data: data["cache"] = {}
                return data
        except: pass
    return {"volume": 85, "cache": {}}

def save_system_state(state):
    try:
        with open(STATE_FILE, 'w') as f: json.dump(state, f)
    except: pass

def get_current_volume():
    try:
        # Parse MIXER_CMD (e.g. "-c 1 sset Playback" or "sset Master")
        parts = MIXER_CMD.split()
        if "-c" in parts:
            card = parts[parts.index("-c") + 1]
            name = parts[parts.index("sset") + 1]
            out = subprocess.check_output(["amixer", "-c", card, "get", name], stderr=subprocess.DEVNULL).decode()
        else:
            name = parts[parts.index("sset") + 1]
            out = subprocess.check_output(["amixer", "get", name], stderr=subprocess.DEVNULL).decode()
            
        for line in out.splitlines():
            if "%" in line:
                start, end = line.index("[") + 1, line.index("%")
                return int(line[start:end])
    except: pass
    return load_system_state().get("volume", 85)

def set_system_volume(slider_val):
    slider_val = max(0, min(100, int(slider_val)))
    try:
        # e.g. amixer -c 1 sset Playback 80%
        cmd = ["amixer"] + MIXER_CMD.split() + [f"{slider_val}%"]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        save_system_state({"volume": slider_val})
        return slider_val
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
    """List all songs across all media sources with high-performance caching."""
    requested_type = request.args.get('type')
    songs = []
    exts = ('.mp3', '.flac', '.wav', '.m4a', '.ogg', '.mp4', '.mkv', '.avi', '.mov', '.webm')
    p_meta = load_metadata()
    
    state = load_system_state()
    cache = state.get("cache", {})

    for source in MEDIA_SOURCES:
        b_dir = source["path"]
        if os.path.exists(b_dir):
            for root, _, files in os.walk(b_dir):
                for f in files:
                    if f.lower().endswith(exts):
                        f_path = os.path.join(root, f)
                        rel = os.path.relpath(f_path, b_dir)
                        
                        # Determine actual type based on extension
                        is_video_ext = f.lower().endswith(('.mkv', '.mp4', '.webm', '.avi', '.mov'))
                        typ = 'video' if is_video_ext else 'music'
                        
                        # Filter by requested type
                        if requested_type and requested_type != typ:
                            continue

                        # High-performance metadata resolution
                        meta = {"title": f, "artist": "Unknown Artist", "album": "Unknown Album", "track_number": 0}
                        tech = {"format": os.path.splitext(f)[1][1:].upper()}
                        
                        # 1. Try persistent cache from disk
                        if f_path in cache:
                            meta_cached = cache[f_path].get("meta", {})
                            meta.update(meta_cached)
                            tech = cache[f_path].get("tech", tech)
                        # 2. Try in-memory memory cache (recently scanned)
                        elif f_path in META_CACHE:
                            m = META_CACHE[f_path]
                            meta = {
                                "title": m.get("title", f), 
                                "artist": m.get("artist", "Unknown Artist"),
                                "album": m.get("album", "Unknown Album"),
                                "track_number": m.get("track_number", 0)
                            }
                            tech = TECH_CACHE.get(f_path, tech)
                        # 3. Fast scan if absolutely missing
                        else:
                            m = get_track_metadata(f_path)
                            meta = {
                                "title": m["title"], 
                                "artist": m["artist"],
                                "album": m.get("album", "Unknown Album"),
                                "track_number": m.get("track_number", 0)
                            }
                                
                        if rel in p_meta:
                            for field in ["title", "category", "artist", "year", "rating", "album"]:
                                if field in p_meta[rel]: meta[field] = p_meta[rel][field]
                                
                        songs.append({
                            "path": rel, 
                            "type": typ, 
                            "filename": f, 
                            "title": meta.get("title", f), 
                            "artist": meta.get("artist", "Unknown Artist"),
                            "album": meta.get("album", "Unknown Album"),
                            "track_number": meta.get("track_number", 0),
                            "category": meta.get("category", "All"), 
                            "year": meta.get("year", ""), 
                            "rating": meta.get("rating", 0), 
                            "tech": tech,
                            "base_dir": b_dir
                        })
    
    songs.sort(key=lambda x: x['title'].lower())
    return jsonify(songs)

@app.route("/api/play", methods=["POST"])
def play_song():
    data = request.json
    p, t = data.get("path"), data.get("type", "music")
    
    # Auto-wake the screen when playing a video
    if t == "video":
        paths = ["/sys/class/backlight/rpi_backlight/bl_power", "/sys/class/backlight/10-0045/bl_power"]
        for sp in paths:
            if os.path.exists(sp):
                try: subprocess.run(["sudo", "sh", "-c", f"echo 0 > {sp}"], check=True)
                except: pass
                break

    # Search for the file in all media sources
    f_path = None
    for source in MEDIA_SOURCES:
        trial_path = os.path.join(source["path"], p)
        if os.path.exists(trial_path):
            f_path = trial_path
            break
            
    if not f_path: return jsonify({"error": "File not found"}), 404
    
    player.start(f_path, {"WAYLAND_DISPLAY": "wayland-0", "XDG_RUNTIME_DIR": "/tmp/weston-runtime"})
    return jsonify({"status": "success"})

@app.route("/api/stop", methods=["POST"])
def stop():
    player.stop()
    return jsonify({"status": "Stopped"})

@app.route("/api/pause", methods=["POST"])
def pause():
    player._send_command(["set", "pause", "yes"])
    return jsonify({"status": "Paused"})

@app.route("/api/resume", methods=["POST"])
def resume():
    player._send_command(["set", "pause", "no"])
    return jsonify({"status": "Resumed"})

@app.route("/api/seek", methods=["POST"])
def seek():
    pos = request.json.get("position", 0)
    player._send_command(["seek", pos, "absolute"])
    return jsonify({"status": "success"})

@app.route("/api/songs/update", methods=["POST"])
def update_song_metadata():
    data = request.json
    song_path = data.get("path")
    if not song_path: return jsonify({"error": "No path"}), 400
    metadata = load_metadata()
    if song_path not in metadata: metadata[song_path] = {}
    for field in ["title", "artist", "category", "year", "rating"]:
        if field in data: metadata[song_path][field] = data[field]
    save_metadata(metadata)
    return jsonify({"status": "success"})

@app.route("/api/songs/rename", methods=["POST"])
def rename_song_file():
    data = request.json
    old_rel = data.get("path")
    new_name = data.get("new_filename")
    
    # Search for the file in all media sources
    old_full = None
    for source in MEDIA_SOURCES:
        trial_path = os.path.join(source["path"], old_rel)
        if os.path.exists(trial_path):
            old_full = trial_path
            break
            
    if not old_full: return jsonify({"error": "Not found"}), 404
    
    new_full = os.path.join(os.path.dirname(old_full), os.path.basename(new_name))
    try:
        os.rename(old_full, new_full)
        return jsonify({"status": "success"})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route("/api/songs/delete", methods=["POST"])
def delete_song():
    data = request.json
    song_path = data.get("path")
    
    # Search for the file in all media sources
    full_path = None
    for source in MEDIA_SOURCES:
        trial_path = os.path.join(source["path"], song_path)
        if os.path.exists(trial_path):
            full_path = trial_path
            break
            
    if full_path and os.path.exists(full_path):
        os.remove(full_path)
        return jsonify({"status": "success"})
    return jsonify({"error": "Not found"}), 404

def save_metadata(metadata):
    try:
        with open(METADATA_FILE, 'w', encoding='utf-8') as f: json.dump(metadata, f, indent=4)
        return True
    except: return False

@app.route("/api/status")
def status():
    if not player.is_alive(): return jsonify({"status": "error"}), 200
    
    # Batch query for all properties at once (Faster, smoother)
    props = ["time-pos", "duration", "pause", "path", "vid"]
    data = player.get_properties(props)
    
    pos = data.get("time-pos")
    dur = data.get("duration")
    pz = data.get("pause")
    full_path = data.get("path")
    vid = data.get("vid")
    path = full_path
    if full_path:
        for source in MEDIA_SOURCES:
            if full_path.startswith(source["path"]):
                path = os.path.relpath(full_path, source["path"])
                break
    meta = get_track_metadata(full_path) if full_path else {}
    
    # Robust video enabled check: Only say False if we explicitly get 'no' or 'false'
    # If the query fails (None), we assume it's still what it was (True by default for videos)
    video_enabled = True
    if vid is not None:
        video_enabled = str(vid).lower() not in ("no", "false", "none", "")
    elif path and path.lower().endswith(('.mp4', '.mkv', '.webm', '.avi', '.mov')):
        video_enabled = True # Fallback for videos if IPC is slow
        
    return jsonify({ 
        "position": pos or 0, 
        "duration": dur or 0, 
        "paused": pz if pz is not None else True, 
        "title": meta.get("title", "Unknown"), 
        "artist": meta.get("artist", "Unknown"), 
        "path": path,
        "video_enabled": video_enabled, 
        "voice_enabled": VOICE_PROCESS is not None, 
        "voice_messages": VOICE_MESSAGES 
    })

@app.route("/api/video/toggle", methods=["POST"])
def video_toggle():
    player._send_command(["cycle", "video"])
    # Return current state after cycle for UI feedback
    time.sleep(0.1) 
    current_vid = player.query(["get_property", "vid"])
    is_enabled = (str(current_vid).lower() not in ("no", "false", "none", ""))
    return jsonify({"video_enabled": is_enabled})

@app.route("/api/cover")
def get_cover():
    song_path = request.args.get("path")
    if not song_path: return jsonify({"error": "No path"}), 400
    
    # Locate full path
    full_path = None
    for source in MEDIA_SOURCES:
        trial = os.path.join(source["path"], song_path)
        if os.path.exists(trial):
            full_path = trial
            break
            
    if full_path:
        d = os.path.dirname(full_path)
        
        # Check current dir, then parent dir (useful for multi-disc albums with subfolders like CD1, CD2)
        dirs_to_check = [d]
        parent_dir = os.path.dirname(d)
        if parent_dir and parent_dir != d:
            dirs_to_check.append(parent_dir)
            
        cover_names = ["cover.jpg", "cover.png", "folder.jpg", "folder.png", "front.jpg", "Front.jpg", "Cover.jpg"]
        
        for search_dir in dirs_to_check:
            for name in cover_names:
                p = os.path.join(search_dir, name)
                if os.path.exists(p):
                    return send_file(p)
                
    return jsonify({"error": "Not found"}), 404

@app.route("/api/volume", methods=["GET", "POST"])
def volume_api():
    if request.method == "POST":
        val = request.json.get("volume")
        new_val = set_system_volume(val)
        return jsonify({"volume": new_val})
    else: return jsonify({"volume": get_current_volume()})

# ── Voice Control (ReSpeaker XVF3800) ────────────────────────────────────────

VOICE_PROCESS = None
VOICE_MESSAGES = {"sarawak": "", "me": "", "awake": False}

@app.route("/api/voice/toggle", methods=["POST"])
def voice_toggle():
    global VOICE_PROCESS, VOICE_MESSAGES
    enabled = request.json.get("enabled", False)
    
    script_path = BASE_DIR / "smart_voice_unit" / "voice_controller.py"
    
    if enabled:
        if VOICE_PROCESS is None:
            # Start the actual voice controller in background
            try:
                VOICE_PROCESS = subprocess.Popen([sys.executable, str(script_path)], 
                                               cwd=str(BASE_DIR / "smart_voice_unit"))
                VOICE_MESSAGES = {"sarawak": "", "me": "", "awake": False}
                return jsonify({"status": "Voice service started", "enabled": True})
            except Exception as e:
                return jsonify({"status": f"Error: {str(e)}", "enabled": False}), 500
    else:
        if VOICE_PROCESS:
            VOICE_PROCESS.terminate()
            VOICE_PROCESS = None
            VOICE_MESSAGES = {"sarawak": "", "me": "", "awake": False}
            return jsonify({"status": "Voice service stopped", "enabled": False})
            
    return jsonify({"status": "No change", "enabled": VOICE_PROCESS is not None})

@app.route("/api/voice/message", methods=["POST"])
def voice_message():
    global VOICE_MESSAGES
    data = request.json
    if "sarawak" in data: VOICE_MESSAGES["sarawak"] = data["sarawak"]
    if "me" in data: VOICE_MESSAGES["me"] = data["me"]
    if "awake" in data: 
        VOICE_MESSAGES["awake"] = data["awake"]
        # If waking up and video is playing, toggle it off
        if data["awake"]:
            current_vid = player.query(["get_property", "vid"])
            if current_vid and str(current_vid).lower() not in ("no", "false", "none", ""):
                player._send_command(["set", "video", "no"])
    
    return jsonify({"status": "success"})

# ── System Control ──────────────────────────────────────────────────────────

CONTROL_MODE = "AUTO" # "AUTO" or "PC_MASTER"

@app.route("/api/system/mode", methods=["GET", "POST"])
def system_mode():
    global CONTROL_MODE
    if request.method == "POST":
        CONTROL_MODE = request.json.get("mode", "AUTO")
    return jsonify({"mode": CONTROL_MODE})

@app.route("/api/system/screen_toggle", methods=["POST"])
def screen_toggle():
    paths = ["/sys/class/backlight/rpi_backlight/bl_power", "/sys/class/backlight/10-0045/bl_power"]
    for p in paths:
        if os.path.exists(p):
            with open(p, "r") as f: cur = f.read().strip()
            new = "1" if cur == "0" else "0"
            try:
                subprocess.run(["sudo", "sh", "-c", f"echo {new} > {p}"], check=True)
                return jsonify({"status": "success", "power": new == "0"})
            except: pass
    return jsonify({"status": "not_supported"})

@app.route("/api/system/shutdown", methods=["POST"])
def system_shutdown():
    try:
        subprocess.run(["sudo", "shutdown", "-h", "now"], stderr=subprocess.DEVNULL)
        return jsonify({"status": "Shutting down"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

def get_audio_details(f_path):
    if f_path in TECH_CACHE: return TECH_CACHE[f_path]
    try:
        # Run ffprobe at lowest CPU priority (nice 19) to avoid pegging the CPU
        res = subprocess.check_output(
            ["nice", "-n", "19", "ffprobe", "-v", "error",
             "-show_entries", "stream=codec_type,sample_rate,bits_per_sample,channels:format=format_name,bit_rate,duration",
             "-of", "json", f_path],
            timeout=5
        ).decode("utf-8")
        d = json.loads(res)
        s = next((x for x in d.get("streams", []) if x.get("codec_type") == "audio"), {})
        f = d.get("format", {})
        TECH_CACHE[f_path] = {
            "sample_rate": s.get("sample_rate"),
            "bit_depth":   s.get("bits_per_sample"),
            "format":      f.get("format_name"),
            "bit_rate":    f.get("bit_rate"),
            "duration":    float(f.get("duration", 0) or 0)
        }
        return TECH_CACHE[f_path]
    except: return {}

# Video extensions that are too slow/large for deep ffprobe scanning at startup
_VIDEO_EXTS = ('.mp4', '.mkv', '.avi', '.mov', '.webm')

def background_scanner():
    """
    Crawls all media sources in the background to build a rich technical
    metadata cache. Runs at low CPU priority with throttling between files
    so the Pi stays responsive during normal use.
    """
    # Wait for boot to settle before hammering the disk/CPU
    print("[*] Metadata Scanner: Waiting 30 seconds for system to settle...")
    time.sleep(30)
    print("[*] Metadata Scanner: Starting background scan (throttled)...")
    
    state = load_system_state()
    cache = state.get("cache", {})
    # Audio-only extensions for deep scanning (videos are too slow and not needed)
    audio_exts = ('.mp3', '.flac', '.wav', '.m4a', '.ogg')
    all_exts   = audio_exts + _VIDEO_EXTS
    
    count = 0
    for source in MEDIA_SOURCES:
        b_dir = source["path"]
        if not os.path.exists(b_dir): continue
        
        for root, _, files in os.walk(b_dir):
            for f in files:
                if not f.lower().endswith(all_exts):
                    continue
                    
                f_path = os.path.join(root, f)
                is_video = f.lower().endswith(_VIDEO_EXTS)
                
                # Only deep-scan AUDIO files — video files skip ffprobe
                existing_tech = cache.get(f_path, {}).get("tech", {})
                needs_scan = (f_path not in cache or not existing_tech.get("sample_rate")) and not is_video
                
                try:
                    # 1. Fast tag scan (always)
                    m = get_track_metadata(f_path)
                    t = {}
                    
                    if needs_scan:
                        # 2. Deep technical scan via ffprobe (audio files only)
                        t = get_audio_details(f_path)
                        count += 1
                        # Throttle: pause between each file scan to keep CPU sane
                        time.sleep(0.3)
                        
                    # Only update cache if we have new data
                    if f_path not in cache or needs_scan:
                        cache[f_path] = {
                            "meta": {
                                "title":        m["title"],
                                "artist":       m["artist"],
                                "album":        m.get("album", "Unknown Album"),
                                "track_number": m.get("track_number", 0)
                            },
                            "tech": t
                        }

                    # Save every 20 deep-scanned files to persist progress
                    if count > 0 and count % 20 == 0:
                        state["cache"] = cache
                        save_system_state(state)
                        print(f"[*] Metadata Scanner: Progress saved ({count} audio files)...")
                        
                except Exception as e:
                    print(f"[!] Metadata Scanner Error on {f}: {e}")
                            
    state["cache"] = cache
    save_system_state(state)
    
    # 3. Smart Pruner: Remove metadata/cache for files that no longer exist
    print("[*] Metadata Scanner: Pruning obsolete entries...")
    metadata = load_metadata()
    meta_changed = False
    
    # Build a set of all currently existing relative paths
    existing_rels = set()
    for source in MEDIA_SOURCES:
        if os.path.exists(source["path"]):
            for root, _, files in os.walk(source["path"]):
                for f in files:
                    rel = os.path.relpath(os.path.join(root, f), source["path"])
                    existing_rels.add(rel)
    
    # Prune metadata.json
    for rel_path in list(metadata.keys()):
        if rel_path not in existing_rels:
            del metadata[rel_path]
            meta_changed = True
            
    if meta_changed:
        save_metadata(metadata)
        print("[*] Metadata Scanner: Obsolete metadata pruned.")
        
    print(f"[*] Metadata Scanner: Scan complete. Total {count} files updated.")

@app.route("/api/quit_browser", methods=["POST"])
def quit_browser():
    try:
        # Kill both common chromium names
        subprocess.run(["pkill", "-9", "chromium"], stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-9", "chromium-browser"], stderr=subprocess.DEVNULL)
        return jsonify({"status": "Browser closed"})
    except: return jsonify({"status": "error"}), 500

if __name__ == "__main__":
    # Restore volume on startup
    state = load_system_state()
    set_system_volume(state.get("volume", 85))
    
    # Start background metadata scanner
    threading.Thread(target=background_scanner, daemon=True).start()
    
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
