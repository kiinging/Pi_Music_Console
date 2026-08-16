import os
import socket
import json
import sqlite3
import subprocess
import time
import logging
import math
import sys
import threading
import glob
from pathlib import Path
from flask import Flask, render_template, jsonify, request, send_file

# ── Audio Output Selection ────────────────────────────────────────────────────
# Supported values: 'pcm5122' (internal DAC) | 'usb' (external USB DAC)
# Loaded from system_state.json at startup; changed via /api/system/set_audio
AUDIO_OUTPUT = 'pcm5122'  # safe default – overwritten after state loads

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
# Caches replaced by SQLite database
BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "media.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_db_schema():
    try:
        with get_db() as conn:
            c = conn.cursor()
            cols = [row[1] for row in c.execute("PRAGMA table_info(media_items)").fetchall()]
            if 'bit_rate' not in cols:
                c.execute("ALTER TABLE media_items ADD COLUMN bit_rate TEXT")
            conn.commit()
    except Exception as e:
        print(f"[!] DB schema repair failed: {e}")


def prune_missing_media_items():
    try:
        with get_db() as conn:
            c = conn.cursor()
            rows = c.execute("SELECT path FROM media_items WHERE path IS NOT NULL").fetchall()
            missing = []
            for row in rows:
                rel_path = row['path']
                if not resolve_media_path(rel_path):
                    missing.append((rel_path,))
            if missing:
                c.executemany("DELETE FROM media_items WHERE path = ?", missing)
                conn.commit()
    except Exception as e:
        print(f"[!] Prune missing media failed: {e}")


def resolve_media_path(rel_path):
    if not rel_path:
        return None
    if os.path.isabs(rel_path) and os.path.exists(rel_path):
        return rel_path
    for source in MEDIA_SOURCES:
        candidate = os.path.abspath(os.path.join(source["path"], rel_path))
        if os.path.exists(candidate):
            return candidate
    return None


def expected_media_type_for_path(file_path):
    if not file_path:
        return None
    ext = os.path.splitext(file_path)[1].lower()
    if ext in ('.mp4', '.mkv', '.avi', '.mov', '.webm'):
        return 'video'
    if ext in ('.mp3', '.flac', '.wav', '.m4a', '.ogg'):
        return 'music'
    return None


def repair_media_db_types():
    ensure_db_schema()
    prune_missing_media_items()
    try:
        with get_db() as conn:
            c = conn.cursor()
            rows = c.execute("SELECT path, type FROM media_items WHERE path IS NOT NULL").fetchall()
            for row in rows:
                rel_path = row[0]
                current_type = row[1]
                real_path = resolve_media_path(rel_path)
                real_type = expected_media_type_for_path(real_path) if real_path else None
                if real_type and current_type != real_type:
                    c.execute("UPDATE media_items SET type=? WHERE path=?", (real_type, rel_path))
            conn.commit()
    except Exception as e:
        print(f"[!] DB repair failed: {e}")


def normalize_category(value):
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.lower() == 'all':
        return 'All'
    aliases = {
        'pop': 'Pop',
        'rock': 'Rock',
        'classical': 'Classical',
        'spanish': 'Spanish',
        'chinese': 'Chinese'
    }
    return aliases.get(s.lower(), s)


def apply_music_album_overrides(song, album_override):
    if not album_override:
        return song

    if album_override.get('artist'):
        song['artist'] = album_override['artist']

    category_val = normalize_category(album_override.get('category'))
    if category_val:
        song['category'] = category_val

    album_rating = album_override.get('rating')
    if album_rating not in (None, ''):
        try:
            album_rating = int(album_rating)
        except (TypeError, ValueError):
            album_rating = None

        current_rating = song.get('rating')
        if album_rating is not None and (current_rating in (None, '', 0)):
            song['rating'] = album_rating

    return song

# Media Sources (Organized Structure)
# Music: ~/Music (albums only)
# Video: ~/Video (videos only)
MEDIA_SOURCES = [
    {"path": os.path.expanduser("~/Music"), "type": "music"},
    {"path": os.path.expanduser("~/Video"), "type": "video"},
]

MUSIC_DIR = os.path.expanduser("~/Music")
VIDEO_DIR = os.path.expanduser("~/Video")

IPC_SOCKET = "/tmp/mpvsocket"

def get_track_metadata(file_path):
    metadata = {"title": os.path.basename(file_path), "artist": "Unknown Artist", "album": "Unknown Album", "track_number": 0,  "disc_number": 1}
    if File:
        try:
            audio = File(file_path)
            if audio:
                tags = audio.tags if hasattr(audio, 'tags') else audio
                if tags:
                    metadata["title"] = str(tags.get('title', [metadata["title"]])[0])
                    metadata["artist"] = str(tags.get('artist', ["Unknown Artist"])[0])
                    metadata["album"] = str(tags.get('album', ["Unknown Album"])[0])
                    tn_raw = tags.get('tracknumber', tags.get('track', ["0"]))
                    tn_str = str(tn_raw[0]) if tn_raw else "0"
                    metadata["track_number"] = int(tn_str.split('/')[0]) if tn_str.split('/')[0].isdigit() else 0
                    
                    parts = os.path.normpath(file_path).split(os.sep)
                    for part in parts:
                        if part.lower().startswith("disc "):
                            num = part[5:].strip()
                            if num.isdigit():
                                metadata["disc_number"] = int(num)
                            break
        except Exception: pass
    
    # Fallback: Extract track number from filename if tags had none (e.g., "05 - Title.flac" -> 5)
    if metadata["track_number"] == 0:
        basename = os.path.basename(file_path)
        # Match pattern: "01 " or "01-" at start of filename
        import re
        match = re.match(r'^(\d+)\s*[-\s]', basename)
        if match:
            try:
                metadata["track_number"] = int(match.group(1))
            except: pass
    
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
            # get_audio_device() reads the global AUDIO_OUTPUT – no subprocess call
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
                "--audio-device=" + get_audio_device(),
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

def get_audio_device():
    """Return the mpv --audio-device string based on the user-selected AUDIO_OUTPUT.
    No subprocess calls – fast, reliable, and hot-plug-independent."""
    if AUDIO_OUTPUT == 'usb':
        print("[*] Audio Device: USB DAC (alsa/plughw:CARD=Audio,DEV=0)")
        return "alsa/plughw:CARD=Audio,DEV=0"
    else:
        # Use a more explicit target for the PCM5122 instead of "auto" which might route to HDMI
        print("[*] Audio Device: PCM5122 internal DAC")
        return "alsa/sysdefault:CARD=IQaudIODAC"

def detect_mixer():
    """Detect the correct amixer control for the currently selected audio output.
    When AUDIO_OUTPUT=='usb' we skip PCM5122-specific mixers and prefer Master/Playback
    on the USB card so that volume control targets the right hardware."""
    if AUDIO_OUTPUT == 'usb':
        # For USB DAC: look for a Master or PCM control on card 1 or 2
        for card in range(3):
            for name in ["Master", "PCM", "Playback", "Speaker"]:
                try:
                    subprocess.check_output(["amixer", "-c", str(card), "get", name], stderr=subprocess.DEVNULL)
                    print(f"[*] Mixer (USB mode): Found '{name}' on card {card}")
                    return f"-c {card} sset {name}"
                except: continue
    else:
        # For PCM5122 internal DAC: prefer 'Digital' or 'Analogue' mixer
        for card in range(3):
            for name in ["Digital", "Analogue"]:
                try:
                    subprocess.check_output(["amixer", "-c", str(card), "get", name], stderr=subprocess.DEVNULL)
                    print(f"[*] Mixer (PCM5122 mode): Found '{name}' on card {card}")
                    return f"-c {card} sset {name}"
                except: continue
        # Fallback: general mixers
        for card in range(3):
            for name in ["Master", "Playback", "HDMI", "Speaker"]:
                try:
                    subprocess.check_output(["amixer", "-c", str(card), "get", name], stderr=subprocess.DEVNULL)
                    print(f"[*] Mixer (PCM5122 fallback): Found '{name}' on card {card}")
                    return f"-c {card} sset {name}"
                except: continue

    return "sset Master"

# NOTE: MIXER_CMD is initialised at the bottom of __main__ after system state
# (and therefore AUDIO_OUTPUT) has been loaded, so it always targets the correct card.
MIXER_CMD = "sset Master"  # temporary placeholder – replaced on startup

def load_system_state():
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT key, value FROM settings")
            rows = c.fetchall()
            if rows:
                state = {row['key']: json.loads(row['value']) for row in rows}
                return state
    except: pass
    return {"volume": 85, "audio_output": "pcm5122"}

def save_system_state(state):
    try:
        with get_db() as conn:
            c = conn.cursor()
            for k, v in state.items():
                c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, json.dumps(v)))
            conn.commit()
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
    requested_type = request.args.get('type')
    songs = []
    try:
        repair_media_db_types()
        prune_missing_media_items()
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM albums")
            albums_map = {row['name']: dict(row) for row in c.fetchall()}

            if requested_type == 'music':
                c.execute("SELECT * FROM media_items WHERE type='music'")
            elif requested_type == 'video':
                c.execute("SELECT * FROM media_items WHERE type='video'")
            else:
                c.execute("SELECT * FROM media_items")

            for row in c.fetchall():
                resolved_path = resolve_media_path(row['path'])
                real_type = expected_media_type_for_path(resolved_path) if resolved_path else row['type']
                if real_type is not None and row['type'] != real_type:
                    row = dict(row)
                    row['type'] = real_type
                song = dict(row)
                if song.get('type') == 'music':
                    override_keys = []
                    album_name = song.get('album')
                    if album_name:
                        override_keys.append(album_name)
                    rel_path = song.get('path') or ''
                    if rel_path:
                        top_folder = rel_path.split('/')[0].split('\\')[0].strip()
                        if top_folder and top_folder not in override_keys:
                            override_keys.append(top_folder)
                    for key in override_keys:
                        if key in albums_map:
                            a_override = albums_map[key]
                            song = apply_music_album_overrides(song, a_override)
                            break

                if resolved_path and real_type is not None:
                    song['type'] = real_type
                song['tech'] = {
                    'duration': song.get('duration'),
                    'sample_rate': song.get('sample_rate'),
                    'bit_depth': song.get('bit_depth'),
                    'format': song.get('format'),
                    'bit_rate': song.get('bit_rate')
                }
                song['base_dir'] = VIDEO_DIR if song['type'] == 'video' else MUSIC_DIR
                songs.append(song)
    except Exception as e:
        print("Error fetching songs:", e)

    songs.sort(key=lambda x: (int(x.get('disc_number', 1) or 1), int(x.get('track_number', 0) or 0), x['filename'].lower()))
    return jsonify(songs)

MANUAL_STOP = False

@app.route("/api/play", methods=["POST"])
def play_song():
    global MANUAL_STOP
    MANUAL_STOP = False
    data = request.json
    p, t = data.get("path"), data.get("type", "music")
    
    # Auto-wake the screen when playing a video
    if t == "video":
        paths = glob.glob("/sys/class/backlight/*/bl_power")
        if not paths: paths = ["/sys/class/backlight/rpi_backlight/bl_power", "/sys/class/backlight/10-0045/bl_power"]
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
    global MANUAL_STOP
    MANUAL_STOP = True
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
    
    try:
        with get_db() as conn:
            c = conn.cursor()
            fields = []
            values = []
            for field in ["title", "artist", "category", "rating"]:
                if field in data:
                    fields.append(f"{field}=?")
                    values.append(data[field])
            if fields:
                values.append(song_path)
                query = f"UPDATE media_items SET {', '.join(fields)} WHERE path=?"
                c.execute(query, tuple(values))
            conn.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/songs/rename", methods=["POST"])
def rename_song_file():
    data = request.json
    old_rel = data.get("path")
    new_name = data.get("new_filename")
    
    old_full = None
    for source in MEDIA_SOURCES:
        trial_path = os.path.join(source["path"], old_rel)
        if os.path.exists(trial_path):
            old_full = trial_path
            break
            
    if not old_full: return jsonify({"error": "Not found"}), 404
    
    new_full = os.path.join(os.path.dirname(old_full), os.path.basename(new_name))
    new_rel = os.path.join(os.path.dirname(old_rel), os.path.basename(new_name))
    try:
        os.rename(old_full, new_full)
        with get_db() as conn:
            c = conn.cursor()
            c.execute("UPDATE media_items SET path=?, filename=? WHERE path=?", (new_rel, os.path.basename(new_name), old_rel))
            conn.commit()
        return jsonify({"status": "success"})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route("/api/songs/delete", methods=["POST"])
def delete_song():
    data = request.json
    song_path = data.get("path")
    
    full_path = None
    for source in MEDIA_SOURCES:
        trial_path = os.path.join(source["path"], song_path)
        if os.path.exists(trial_path):
            full_path = trial_path
            break
            
    if full_path and os.path.exists(full_path):
        os.remove(full_path)
        try:
            with get_db() as conn:
                c = conn.cursor()
                c.execute("DELETE FROM media_items WHERE path=?", (song_path,))
                conn.commit()
        except: pass
        return jsonify({"status": "success"})
    return jsonify({"error": "Not found"}), 404


# New endpoint to update album‑level metadata
@app.route("/api/albums/update", methods=["POST"])
def update_album_metadata():
    data = request.json
    if not data: return jsonify({"error": "No data"}), 400
    album_name = data.get("album")
    if not album_name: return jsonify({"error": "Album name required"}), 400
    
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM albums WHERE name=?", (album_name,))
            row = c.fetchone()
            album = dict(row) if row else {"name": album_name, "artist": "", "category": "", "rating": 0}
            
            for field in ["artist", "category", "rating"]:
                if field in data:
                    if field == "category":
                        album[field] = normalize_category(data[field])
                    else:
                        album[field] = data[field]
                
            c.execute("INSERT OR REPLACE INTO albums (name, artist, category, rating) VALUES (?, ?, ?, ?)", 
                      (album["name"], album["artist"], album["category"], album["rating"]))
            conn.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route("/api/status")
def status():
    if not player.is_alive(): return jsonify({"status": "error", "manual_stop": MANUAL_STOP}), 200
    
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
    tech = {}
    if full_path:
        meta = get_track_metadata(full_path)
        tech = {}
        try:
            with get_db() as conn:
                c = conn.cursor()
                c.execute("SELECT * FROM media_items WHERE path=?", (path,))
                row = c.fetchone()
                if row:
                    r = dict(row)
                    for field in ["title", "category", "artist", "rating", "album"]:
                        if r.get(field): meta[field] = r[field]
                    tech = {
                        'duration': r.get('duration'),
                        'sample_rate': r.get('sample_rate'),
                        'bit_depth': r.get('bit_depth'),
                        'format': r.get('format')
                    }
        except: pass
    else:
        meta = {}
    
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
        "tech": tech,
        "video_enabled": video_enabled
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

# ── Voice control functionality removed ──────────────────────────────────────

# ── System Control ──────────────────────────────────────────────────────────

EQ_STATE = {"bass": 0, "mid": 0, "treble": 0}
FAN_STATE = False

def build_eq(eq):
    return (
        f"equalizer=f=80:width_type=o:width=2:g={eq['bass']},"
        f"equalizer=f=1000:width_type=o:width=2:g={eq['mid']},"
        f"equalizer=f=9000:width_type=o:width=2:g={eq['treble']}"
    )

@app.route("/api/system/eq", methods=["POST"])
def system_eq():
    global EQ_STATE
    data = request.json
    if data:
        if "bass" in data: EQ_STATE["bass"] = float(data["bass"])
        if "mid" in data: EQ_STATE["mid"] = float(data["mid"])
        if "treble" in data: EQ_STATE["treble"] = float(data["treble"])
        
    if EQ_STATE["bass"] == 0 and EQ_STATE["mid"] == 0 and EQ_STATE["treble"] == 0:
        player._send_command(["af", "clr"])
    else:
        player._send_command(["af", "set", build_eq(EQ_STATE)])
        
    return jsonify({"status": "success", "eq": EQ_STATE})

@app.route("/api/system/fan", methods=["POST"])
def system_fan():
    global FAN_STATE
    data = request.json
    if data and "enabled" in data:
        FAN_STATE = data["enabled"]
    else:
        FAN_STATE = not FAN_STATE
        
    try:
        if FAN_STATE:
            # Set GPIO 8 (CE0) HIGH (ON)
            subprocess.run(["pinctrl", "set", "8", "op", "dh"], check=True)
        else:
            # Set GPIO 8 (CE0) LOW (OFF)
            subprocess.run(["pinctrl", "set", "8", "op", "dl"], check=True)
        return jsonify({"status": "success", "fan_enabled": FAN_STATE})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/system/screen_toggle", methods=["POST"])
def screen_toggle():
    # Dynamically discover backlight control paths
    paths = glob.glob("/sys/class/backlight/*/bl_power")
    if not paths:
        # Fallbacks just in case
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
    try:
        # Run ffprobe without nice to ensure it doesn't fail on Windows or timeout unexpectedly
        res = subprocess.check_output(
            ["ffprobe", "-v", "error",
             "-show_entries", "stream=codec_type,sample_rate,bits_per_sample,channels:format=format_name,bit_rate,duration",
             "-of", "json", f_path],
            timeout=5
        ).decode("utf-8")
        d = json.loads(res)
        s = next((x for x in d.get("streams", []) if x.get("codec_type") == "audio"), {})
        f = d.get("format", {})
        bit_rate = f.get("bit_rate")
        try:
            if bit_rate is not None and str(bit_rate).strip() != '':
                bit_rate = int(float(bit_rate))
        except Exception:
            pass
        
        # ── NEW: estimate bitrate for FLAC when ffprobe gives 0/None ──
        if (not bit_rate or bit_rate == 0) and f.get("duration"):
            try:
                file_size = os.path.getsize(f_path)
                duration = float(f.get("duration"))
                if duration > 0:
                    bit_rate = int((file_size * 8) / duration)
            except:
                pass
        # ───────────────────────────────────────────────────────────────
        return {
            "sample_rate": s.get("sample_rate"),
            "bit_depth":   s.get("bits_per_sample"),
            "format":      f.get("format_name"),
            "bit_rate":    bit_rate,
            "duration":    float(f.get("duration", 0) or 0)
        }
    except: return {}

# Video extensions that are too slow/large for deep ffprobe scanning at startup
_VIDEO_EXTS = ('.mp4', '.mkv', '.avi', '.mov', '.webm')

def background_scanner():
    print("[*] Metadata Scanner: Waiting 30 seconds for system to settle...")
    time.sleep(30)
    print("[*] Metadata Scanner: Starting background scan (throttled)...")
    
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
                rel_path = os.path.relpath(f_path, b_dir)
                is_video = f.lower().endswith(_VIDEO_EXTS)
                typ = 'video' if is_video else 'music'
                
                needs_scan = False
                try:
                    with get_db() as conn:
                        c = conn.cursor()
                        c.execute("SELECT sample_rate, bit_rate FROM media_items WHERE path=?", (rel_path,))
                        row = c.fetchone()
                        if not row or not row['sample_rate'] or not row['bit_rate']:
                            needs_scan = True
                except: needs_scan = True
                
                if needs_scan:
                    try:
                        m = get_track_metadata(f_path)
                        t = get_audio_details(f_path)

                        with get_db() as conn:
                            c = conn.cursor()
                            c.execute('''
                                INSERT INTO media_items 
                                (path, type, filename, title, artist, album, track_number, disc_number, duration, sample_rate, bit_depth, format, bit_rate)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                ON CONFLICT(path) DO UPDATE SET
                                duration=excluded.duration,
                                sample_rate=excluded.sample_rate,
                                bit_depth=excluded.bit_depth,
                                format=excluded.format,
                                bit_rate=excluded.bit_rate
                            ''', (
                                rel_path, typ, f, m["title"], m["artist"], m.get("album", "Unknown Album"),
                                m.get("track_number", 0), m.get("disc_number", 1),
                                t.get("duration", 0), t.get("sample_rate", ""), t.get("bit_depth", ""), t.get("format", ""), t.get("bit_rate", "")
                            ))
                            conn.commit()
                        count += 1
                        time.sleep(0.3)
                    except Exception as e:
                        print(f"[!] Metadata Scanner Error on {f}: {e}")
                        
    print(f"[*] Metadata Scanner: Scan complete. Total {count} files updated.")

@app.route("/api/quit_browser", methods=["POST"])
def quit_browser():
    try:
        # Kill both common chromium names
        subprocess.run(["pkill", "-9", "chromium"], stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-9", "chromium-browser"], stderr=subprocess.DEVNULL)
        return jsonify({"status": "Browser closed"})
    except: return jsonify({"status": "error"}), 500

# ── Audio Output Selection ────────────────────────────────────────────────────

@app.route("/api/system/audio_output", methods=["GET"])
def get_audio_output():
    """Return the currently selected audio output."""
    return jsonify({"audio_output": AUDIO_OUTPUT})

@app.route("/api/system/set_audio", methods=["POST"])
def set_audio_output():
    """Switch the audio output between 'pcm5122' and 'usb'.
    Persists the choice to system_state.json so it survives reboots.
    Restarts mpv (if playing) so the new device takes effect immediately."""
    global AUDIO_OUTPUT, MIXER_CMD
    data = request.json
    new_output = data.get("audio_output", "").strip().lower()
    if new_output not in ("pcm5122", "usb"):
        return jsonify({"error": "Invalid audio_output. Use 'pcm5122' or 'usb'"}), 400

    AUDIO_OUTPUT = new_output

    # Persist to state file
    state = load_system_state()
    state["audio_output"] = AUDIO_OUTPUT
    save_system_state(state)

    # Re-detect mixer so volume control follows the new device
    MIXER_CMD = detect_mixer()
    print(f"[*] Audio output switched to: {AUDIO_OUTPUT} | MIXER_CMD: {MIXER_CMD}")

    # If mpv is playing, stop it so the next playTrack uses the new device
    was_alive = player.is_alive()
    if was_alive:
        player.stop()

    return jsonify({
        "status": "success",
        "audio_output": AUDIO_OUTPUT,
        "mixer": MIXER_CMD,
        "player_restarted": was_alive
    })

if __name__ == "__main__":
    # ── Load system state first (needed for AUDIO_OUTPUT + MIXER_CMD) ──────────
    state = load_system_state()

    # Restore audio output preference (default: 'pcm5122')
    AUDIO_OUTPUT = state.get("audio_output", "pcm5122")
    print(f"[*] Startup: Audio output = {AUDIO_OUTPUT}")

    # Now initialise MIXER_CMD with the correct device knowledge
    MIXER_CMD = detect_mixer()
    print(f"[*] Startup: MIXER_CMD = {MIXER_CMD}")

    # Restore volume
    set_system_volume(state.get("volume", 85))

    # Ensure Fan is OFF on startup (GPIO 8 LOW)
    try:
        subprocess.run(["pinctrl", "set", "8", "op", "dl"], check=True)
    except Exception:
        pass

    # Repair stale metadata that was created by older JSON-based imports or partial migrations.
    repair_media_db_types()

    # Start background metadata scanner
    threading.Thread(target=background_scanner, daemon=True).start()

    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
