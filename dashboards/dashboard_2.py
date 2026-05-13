import os
import socket
import json
import subprocess
import time
import logging
import math
import sys
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


METADATA_FILE = Path(__file__).parent.parent / "music_metadata.json"

def load_metadata():
    if METADATA_FILE.exists():
        try:
            with open(METADATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_metadata(metadata):
    try:
        with open(METADATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=4)
        return True
    except Exception as e:
        print(f"Error saving metadata: {e}")
        return False

# Configuration
IPC_SOCKET = "/tmp/mpvsocket"
MUSIC_DIR = os.path.expanduser("~/Music")
VIDEO_DIR = os.path.expanduser("~/video")
if not os.path.exists(VIDEO_DIR) and os.path.exists(os.path.expanduser("~/Videos")):
    VIDEO_DIR = os.path.expanduser("~/Videos")

def detect_mixer():
    """Attempt to find a working ALSA mixer name (Digital, Master, or Playback)."""
    for name in ["Digital", "Master", "Playback", "HDMI"]:
        try:
            subprocess.check_output(["amixer", "get", name], stderr=subprocess.DEVNULL)
            return name
        except Exception:
            continue
    return "Master"

MIXER_NAME = detect_mixer()

def get_current_volume():
    """Read current ALSA volume and convert back to perceptual slider value (0-100)."""
    try:
        out = subprocess.check_output(
            ["amixer", "get", MIXER_NAME], stderr=subprocess.DEVNULL
        ).decode()
        for line in out.splitlines():
            if "%" in line:
                start = line.index("[") + 1
                end = line.index("%")
                hw_val = int(line[start:end])
                # Inverse Log mapping: slider = log10(HW/100 * (10^L - 1) + 1) / L * 100
                # L=0.5 gives a gentle curve so the full slider range is audible on the IQaudIO DAC
                L = 0.5
                slider_val = round((math.log10((hw_val / 100) * (10**L - 1) + 1) / L) * 100)
                return max(0, min(100, slider_val))
    except Exception:
        pass
    return 50

def set_system_volume(slider_val):
    """Set ALSA volume using a logarithmic (audio) mapping."""
    slider_val = max(0, min(100, int(slider_val)))
    # Log mapping: HW = (10^(L * slider/100) - 1) / (10^L - 1) * 100
    # L=0.5 gives a gentle curve so the full slider range is audible on the IQaudIO DAC
    L = 0.5
    hw_val = int(((10**(L * slider_val / 100) - 1) / (10**L - 1)) * 100)
    
    try:
        subprocess.run(
            ["amixer", "set", MIXER_NAME, f"{hw_val}%"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return slider_val
    except Exception:
        return None

def send_mpv_command(command_list):
    """Send a JSON IPC command to the running mpv process (fire and forget)."""
    if not os.path.exists(IPC_SOCKET):
        return {"error": "mpv socket not found. Is mpv running?"}
    
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(IPC_SOCKET)
        payload = json.dumps({"command": command_list}) + "\n"
        client.send(payload.encode("utf-8"))
        client.close()
        return {"status": "success"}
    except Exception as e:
        return {"error": str(e)}

def send_mpv_query(command_list):
    """Send a JSON IPC command and read back mpv's response (for get_property).
    mpv may emit async event lines before the actual command response, so we
    read line-by-line and skip anything with an 'event' key.
    Command responses always carry an 'error' key (value 'success' when OK).
    """
    if not os.path.exists(IPC_SOCKET):
        return None
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(1.0)
        client.connect(IPC_SOCKET)
        payload = json.dumps({"command": command_list}) + "\n"
        client.send(payload.encode("utf-8"))

        buf = b""
        while True:
            try:
                chunk = client.recv(4096)
                if not chunk:
                    break
                buf += chunk
                # Process every complete line in the buffer
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line.decode("utf-8"))
                    except json.JSONDecodeError:
                        continue
                    # Skip async event notifications from mpv
                    if "event" in msg:
                        continue
                    # This is our command response
                    if "error" in msg:
                        client.close()
                        return msg.get("data")
            except socket.timeout:
                break
        client.close()
        return None
    except Exception:
        return None

def terminate_mpv():
    """Kill any running mpv process."""
    try:
        # Try a graceful stop via IPC first if possible, but usually we just kill the proc
        send_mpv_command(["quit"])
        time.sleep(0.2)
    except:
        pass
    
    # Force kill any remaining mpv processes
    try:
        subprocess.run(["pkill", "-9", "mpv"], stderr=subprocess.DEVNULL)
    except:
        pass
        
    # CRITICAL: Remove the stale socket file so we don't try to connect to a dead process
    if os.path.exists(IPC_SOCKET):
        try:
            os.remove(IPC_SOCKET)
        except:
            pass

def start_mpv_for_file(file_path):
    """Start mpv as a Wayland overlay window."""
    
    terminate_mpv()

    env = os.environ.copy()

    # IMPORTANT
    env["WAYLAND_DISPLAY"] = "wayland-0"
    env["XDG_RUNTIME_DIR"] = "/tmp/weston-runtime"

    cmd = [
        "mpv",

        "--fullscreen",
        "--force-window=no",

        "--keep-open=no",
        "--idle=no",

        "--osc=no",

        "--no-border",
        "--no-terminal",
        "--really-quiet",

        "--gpu-context=wayland",
        "--vo=gpu-next",

        "--hwdec=auto-safe",

        "--video-sync=display-resample",

        "--interpolation",

        "--audio-display=no",

        "--stop-screensaver=no",

        "--cursor-autohide=100",

        "--input-ipc-server=" + IPC_SOCKET,

        "--ao=alsa",

    file_path
]


    print("Launching mpv...")
    print(" ".join(cmd))

    subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    # Wait for IPC socket
    for _ in range(20):
        if os.path.exists(IPC_SOCKET):
            print("mpv socket ready")
            return
        time.sleep(0.1)

    print("WARNING: mpv socket not created")

TECH_CACHE = {}

def get_audio_details(file_path):
    """Use ffprobe to get technical details (sample rate, bit depth)."""
    # Quick memory cache to avoid slow ffprobe calls
    if file_path in TECH_CACHE:
        return TECH_CACHE[file_path]

    try:
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "stream=codec_type,sample_rate,bits_per_sample,channels:format=format_name,bit_rate,duration",
            "-of", "json", file_path
        ]
        # use a 2-second timeout 
        result = subprocess.check_output(cmd, timeout=2).decode("utf-8")
        data = json.loads(result)
        
        streams = data.get("streams", [])
        audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})
        fmt = data.get("format", {})
        
        details = {
            "sample_rate": audio_stream.get("sample_rate"),
            "bit_depth": audio_stream.get("bits_per_sample"),
            "channels": audio_stream.get("channels"),
            "format": fmt.get("format_name"),
            "bit_rate": fmt.get("bit_rate"),
            "duration": float(fmt.get("duration", 0) if fmt.get("duration") else 0)
        }
        TECH_CACHE[file_path] = details
        return details
    except Exception as e:
        return {}

def get_track_metadata(file_path):
    """Use mutagen to get tags (Artist, Album, Title)."""
    metadata = {
        "title": os.path.basename(file_path),
        "artist": "Unknown Artist",
        "album": "Unknown Album"
    }
    
    if File:
        try:
            audio = File(file_path)
            if audio:
                # Handle different tag formats (ID3 vs Vorbis/FLAC)
                tags = audio.tags if hasattr(audio, 'tags') else audio
                if tags:
                    metadata["title"] = str(tags.get('title', [metadata["title"]])[0])
                    metadata["artist"] = str(tags.get('artist', ["Unknown Artist"])[0])
                    metadata["album"] = str(tags.get('album', ["Unknown Album"])[0])
        except Exception:
            pass
            
    return metadata

@app.route("/api/ping")
def ping():
    return jsonify({"status": "Pong!", "version": "2.0"})

@app.route("/api/map")
def route_map():
    links = []
    for rule in app.url_map.iter_rules():
        links.append(str(rule))
    return jsonify(links)

@app.route("/")
def index():
    return render_template("dashboard_2.html")

@app.route("/api/songs")
def list_songs():
    """List all supported media files from both Music and Video folders."""
    media_type = request.args.get('type', 'music')
    
    # Scan BOTH directories to be sure we find the user's files
    dirs_to_scan = [
        (MUSIC_DIR, 'music'),
        (VIDEO_DIR, 'video')
    ]
    
    songs = []
    extensions = ('.mp3', '.flac', '.wav', '.m4a', '.ogg', '.mp4', '.mkv', '.avi', '.mov', '.webm')
    
    # Load metadata ONCE before scanning, not inside the loop!
    persistent_meta = load_metadata()
    
    for base_dir, d_type in dirs_to_scan:
        if os.path.exists(base_dir):
            for root, _, files in os.walk(base_dir):
                for file in files:
                    ext = file.lower()
                    if ext.endswith(extensions):
                        full_path = os.path.join(root, file)
                        rel_path = os.path.relpath(full_path, base_dir)
                        
                        # Determine actual type based on extension
                        actual_type = 'video' if ext.endswith(('.mkv', '.mp4', '.webm', '.avi', '.mov')) else 'music'
                    
                        meta = get_track_metadata(full_path)
                        tech = get_audio_details(full_path)
                        
                        # Merge with persistent JSON metadata
                        if rel_path in persistent_meta:
                            for field in ["title", "category", "artist", "year", "rating"]:
                                if field in persistent_meta[rel_path]:
                                    meta[field] = persistent_meta[rel_path][field]
                        
                        songs.append({
                            "path": rel_path,
                            "type": actual_type, 
                            "filename": file,
                            "title": meta.get("title", file),
                            "artist": meta.get("artist", "Unknown Artist"),
                            "album": meta.get("album", "Unknown Album"),
                            "category": meta.get("category", "All"),
                            "year": meta.get("year", ""),
                            "rating": meta.get("rating", 0),
                            "tech": tech
                        })
    
    # Sort alphabetically by title
    songs.sort(key=lambda x: x['title'].lower())
    
    return jsonify(songs)

@app.route("/api/play", methods=["POST"])
def play_song():
    data = request.json
    song_path = data.get("path")
    media_type = data.get("type", "music")
    
    # Try the expected directory first
    base_dir = VIDEO_DIR if media_type == 'video' else MUSIC_DIR
    full_path = os.path.join(base_dir, song_path)
    
    # If not found, try the OTHER directory as a backup
    if not os.path.exists(full_path):
        alt_dir = MUSIC_DIR if media_type == 'video' else VIDEO_DIR
        full_path = os.path.join(alt_dir, song_path)

    if not os.path.exists(full_path):
        msg = f"File not found. Checked: {os.path.join(base_dir, song_path)} and {os.path.join(alt_dir, song_path)}"
        print(msg) # Print to terminal too
        return jsonify({"error": msg}), 404
    
    # Send technical info back to UI for the 'Now Playing' display
    tech = get_audio_details(full_path)
    meta = get_track_metadata(full_path)
    
    # Merge with persistent metadata
    persistent_meta = load_metadata()
    if song_path in persistent_meta:
        meta.update(persistent_meta[song_path])
    
    # Start fresh mpv for this file (Video ON by default)
    start_mpv_for_file(full_path)
    
    return jsonify({
        "status": "success",
        "track": {
            "title": meta["title"], 
            "artist": meta.get("artist", "Unknown Artist"), 
            "category": meta.get("category", "All"),
            "year": meta.get("year", ""),
            "rating": meta.get("rating", 0),
            "tech": tech
        }
    })

@app.route("/api/songs/update", methods=["POST"])
def update_song_metadata():
    data = request.json
    song_path = data.get("path")
    category = data.get("category")
    artist = data.get("artist")
    year = data.get("year")
    title = data.get("title")
    rating = data.get("rating")
    
    if not song_path:
        return jsonify({"error": "No song path provided"}), 400
    
    metadata = load_metadata()
    if song_path not in metadata:
        metadata[song_path] = {}
    
    if category is not None:
        metadata[song_path]["category"] = category
    if artist is not None:
        metadata[song_path]["artist"] = artist
    if year is not None:
        metadata[song_path]["year"] = year
    if title is not None:
        metadata[song_path]["title"] = title
    if rating is not None:
        metadata[song_path]["rating"] = rating
        
    if save_metadata(metadata):
        return jsonify({"status": "success"})
    else:
        return jsonify({"error": "Failed to save metadata"}), 500

@app.route("/api/songs/rename", methods=["POST"])
def rename_song_file():
    data = request.json
    old_rel_path = data.get("path")
    new_filename = data.get("new_filename")
    media_type = data.get("type", "music")
    
    if not old_rel_path or not new_filename:
        return jsonify({"error": "Missing path or new filename"}), 400
        
    base_dir = VIDEO_DIR if media_type == 'video' else MUSIC_DIR
    old_full_path = os.path.join(base_dir, old_rel_path)
    
    # Fallback check for the other directory
    if not os.path.exists(old_full_path):
        alt_dir = MUSIC_DIR if media_type == 'video' else VIDEO_DIR
        old_full_path = os.path.join(alt_dir, old_rel_path)

    if not os.path.exists(old_full_path):
        return jsonify({"error": "Source file not found"}), 404

    # Ensure new filename has an extension if user forgot it
    old_ext = os.path.splitext(old_rel_path)[1]
    if not new_filename.lower().endswith(old_ext.lower()):
        new_filename += old_ext
        
    # Security: prevent directory traversal
    new_filename = os.path.basename(new_filename)
    new_full_path = os.path.join(os.path.dirname(old_full_path), new_filename)
    if os.path.exists(new_full_path):
        return jsonify({"error": "A file with that name already exists"}), 400
        
    try:
        os.rename(old_full_path, new_full_path)
        
        # Cleanup metadata for the old filename as requested
        metadata = load_metadata()
        if old_rel_path in metadata:
            del metadata[old_rel_path]
            save_metadata(metadata)
            
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/songs/delete", methods=["POST"])
def delete_song():
    data = request.json
    song_path = data.get("path")
    media_type = data.get("type", "music")
    
    if not song_path:
        return jsonify({"error": "No song path provided"}), 400
        
    base_dir = VIDEO_DIR if media_type == 'video' else MUSIC_DIR
    full_path = os.path.join(base_dir, song_path)
    
    # Fallback check for the other directory
    if not os.path.exists(full_path):
        alt_dir = MUSIC_DIR if media_type == 'video' else VIDEO_DIR
        full_path = os.path.join(alt_dir, song_path)

    if not os.path.exists(full_path):
        return jsonify({"error": "File not found"}), 404
        
    try:
        # 1. Remove file
        os.remove(full_path)
        
        # 2. Cleanup metadata
        metadata = load_metadata()
        if song_path in metadata:
            del metadata[song_path]
            save_metadata(metadata)
            
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": f"Failed to delete file: {str(e)}"}), 500

@app.route("/api/stop", methods=["POST"])
def stop():
    terminate_mpv()
    return jsonify({"status": "Stopped"})

@app.route("/api/status")
def status():
    """Return current playback position, total duration, and track info."""
    # Quick check: is mpv even alive?
    if not os.path.exists(IPC_SOCKET):
        return jsonify({"status": "error", "message": "mpv not running"}), 200

    try:
        # Get basic status
        position = send_mpv_query(["get_property", "time-pos"])
        duration = send_mpv_query(["get_property", "duration"])
        paused   = send_mpv_query(["get_property", "pause"])
        path     = send_mpv_query(["get_property", "path"])
        
        title = "Not Playing"
        artist = ""
        tech = {}
        
        if path:
            meta = get_track_metadata(path)
            title = meta.get("title", os.path.basename(path))
            artist = meta.get("artist", "")
            tech = get_audio_details(path)

        # Check if video is enabled
        current_vid = send_mpv_query(["get_property", "vid"])
        video_enabled = (str(current_vid).lower() not in ("no", "false", "none", ""))

        return jsonify({
            "position": round(position, 2) if isinstance(position, (int, float)) else 0,
            "duration": round(duration, 2) if isinstance(duration, (int, float)) else 0,
            "paused":   paused if isinstance(paused, bool) else True,
            "title": title,
            "artist": artist,
            "tech": tech,
            "video_enabled": video_enabled
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 200

@app.route("/api/video/toggle", methods=["POST"])
def video_toggle():
    current_vid = send_mpv_query(["get_property", "vid"])
    is_enabled = (str(current_vid).lower() not in ("no", "false", "none"))
    new_state = "no" if is_enabled else "auto"
    send_mpv_command(["set_property", "vid", new_state])
    return jsonify({"video_enabled": new_state == "auto"})

@app.route("/api/seek", methods=["POST"])
def seek():
    """Seek to an absolute position in seconds."""
    data = request.json
    position = data.get("position", 0)
    try:
        position = float(position)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid position"}), 400
    result = send_mpv_command(["seek", position, "absolute"])
    return jsonify(result)

@app.route("/api/pause", methods=["POST"])
def pause():
    send_mpv_command(["set", "pause", "yes"])
    return jsonify({"status": "Paused"})

@app.route("/api/resume", methods=["POST"])
def resume():
    send_mpv_command(["set", "pause", "no"])
    return jsonify({"status": "Resumed"})

@app.route("/api/next", methods=["POST"])
def next_track():
    send_mpv_command(["playlist-next"])
    return jsonify({"status": "Next"})

@app.route("/api/prev", methods=["POST"])
def prev_track():
    send_mpv_command(["playlist-prev"])
    return jsonify({"status": "Previous"})

@app.route("/api/volume", methods=["GET", "POST"])
def volume_api():
    if request.method == "POST":
        val = request.json.get("volume")
        new_val = set_system_volume(val)
        return jsonify({"volume": new_val})
    else:
        return jsonify({"volume": get_current_volume()})

# ========== ADD THESE ROUTES ==========
import subprocess

def run_nmcli(args):
    try:
        return subprocess.check_output(["nmcli"] + args, stderr=subprocess.DEVNULL).decode().strip()
    except:
        return None

@app.route("/api/network/wifi/scan")
def wifi_scan():
    out = run_nmcli(["-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list"])
    if not out:
        return jsonify({"error": "No Wi-Fi adapter or scan failed"}), 500
    networks = []
    seen = set()
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 2:
            ssid = parts[0]
            signal = int(parts[1]) if parts[1].isdigit() else 0
            security = parts[2] if len(parts) > 2 else ""
            if ssid and ssid not in seen:
                seen.add(ssid)
                networks.append({"ssid": ssid, "signal": signal, "secure": security != "--"})
    networks.sort(key=lambda x: x["signal"], reverse=True)
    return jsonify(networks)

@app.route("/api/network/wifi/connect", methods=["POST"])
def wifi_connect():
    data = request.json
    ssid = data.get("ssid")
    password = data.get("password", "")
    if not ssid:
        return jsonify({"error": "Missing SSID"}), 400
    try:
        if password:
            subprocess.run(["nmcli", "device", "wifi", "connect", ssid, "password", password], check=True)
        else:
            subprocess.run(["nmcli", "device", "wifi", "connect", ssid], check=True)
        return jsonify({"status": "connected"})
    except subprocess.CalledProcessError as e:
        return jsonify({"error": f"Connection failed: {e}"}), 500

@app.route("/api/network/status")
def network_status():
    active = run_nmcli(["-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"])
    result = {"wifi": None, "ethernet": None}
    if active:
        for line in active.splitlines():
            parts = line.split(":")
            if len(parts) >= 2:
                name, typ = parts[0], parts[1]
                if typ == "wifi":
                    result["wifi"] = {"name": name, "device": parts[2] if len(parts) > 2 else "wlan0"}
                elif typ == "ethernet":
                    result["ethernet"] = {"name": name, "device": parts[2] if len(parts) > 2 else "eth0"}
    return jsonify(result)

@app.route("/api/network/ethernet/connect", methods=["POST"])
def ethernet_connect():
    try:
        subprocess.run(["nmcli", "device", "disconnect", "wlan0"], stderr=subprocess.DEVNULL)
        subprocess.run(["nmcli", "device", "connect", "eth0"], stderr=subprocess.DEVNULL)
        return jsonify({"status": "Ethernet preferred"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/youtube/play", methods=["POST"])
def youtube_play():
    data = request.json
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL or search term"}), 400
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "ytsearch:" + url
    terminate_mpv()
    env = os.environ.copy()
    env["WAYLAND_DISPLAY"] = "wayland-0"
    env["XDG_RUNTIME_DIR"] = "/tmp/weston-runtime"
    cmd = [
        "mpv", "--gpu-context=wayland", "--vo=gpu", "--fullscreen",
        "--force-window=yes", "--ontop", "--input-ipc-server=" + IPC_SOCKET,
        "--ao=alsa", "--border=no", "--no-terminal", "--really-quiet", url
    ]
    subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(20):
        if os.path.exists(IPC_SOCKET):
            return jsonify({"status": "playing", "title": url})
        time.sleep(0.1)
    return jsonify({"error": "mpv failed to start"}), 500



if __name__ == "__main__":
    # Do not start mpv here; wait until Play is clicked
    app.run(host="[IP_ADDRESS]", port=5000, debug=False, threaded=True)

