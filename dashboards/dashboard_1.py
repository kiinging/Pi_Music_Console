import os
import socket
import json
import subprocess
import time
import logging
from flask import Flask, render_template, jsonify, request
from pathlib import Path

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

# Configuration
IPC_SOCKET = "/tmp/mpvsocket"
MUSIC_DIR = os.path.expanduser("~/Music")

def detect_mixer():
    """Attempt to find a working ALSA mixer name (Digital, Master, or Playback)."""
    for name in ["Digital", "Master", "Playback", "HDMI"]:
        try:
            subprocess.check_output(["amixer", "get", name], stderr=subprocess.DEVNULL)
            return name
        except subprocess.CalledProcessError:
            continue
    return "Master"

MIXER_NAME = detect_mixer()

def get_current_volume():
    """Read current ALSA volume (0-100)."""
    try:
        out = subprocess.check_output(
            ["amixer", "get", MIXER_NAME], stderr=subprocess.DEVNULL
        ).decode()
        for line in out.splitlines():
            if "%" in line:
                start = line.index("[") + 1
                end = line.index("%")
                return int(line[start:end])
    except Exception:
        pass
    return 50

def set_system_volume(value):
    """Set ALSA volume."""
    value = max(0, min(100, int(value)))
    try:
        subprocess.run(
            ["amixer", "set", MIXER_NAME, f"{value}%"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return value
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
    """Send a JSON IPC command and read back mpv's response (for get_property)."""
    if not os.path.exists(IPC_SOCKET):
        return None
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(1.0)
        client.connect(IPC_SOCKET)
        payload = json.dumps({"command": command_list}) + "\n"
        client.send(payload.encode("utf-8"))
        response = b""
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            response += chunk
            if b"\n" in response:
                break
        client.close()
        data = json.loads(response.decode("utf-8").strip())
        return data.get("data")
    except Exception:
        return None

def start_mpv():
    """Start mpv in the background if it's not already running."""
    if os.path.exists(IPC_SOCKET):
        return

    print("Starting mpv in background...")
    subprocess.Popen([
        "mpv",
        "--idle",
        "--input-ipc-server=" + IPC_SOCKET,
        "--no-terminal"
    ])
    time.sleep(1)

def get_audio_details(file_path):
    """Use ffprobe to get technical details (sample rate, bit depth)."""
    try:
        cmd = [
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=sample_rate,bits_per_sample,channels:format=format_name,bit_rate,duration",
            "-of", "json", file_path
        ]
        result = subprocess.check_output(cmd).decode("utf-8")
        data = json.loads(result)
        
        stream = data.get("streams", [{}])[0]
        fmt = data.get("format", {})
        
        return {
            "sample_rate": stream.get("sample_rate"),
            "bit_depth": stream.get("bits_per_sample"),
            "channels": stream.get("channels"),
            "format": fmt.get("format_name"),
            "bit_rate": fmt.get("bit_rate"),
            "duration": float(fmt.get("duration", 0))
        }
    except Exception:
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

@app.route("/")
def index():
    return render_template("dashboard_1.html")

@app.route("/api/songs")
def list_songs():
    """List all supported music files with their metadata."""
    songs = []
    extensions = ('.mp3', '.flac', '.wav', '.m4a', '.ogg', '.mp4', '.mkv')
    
    for root, _, files in os.walk(MUSIC_DIR):
        for file in files:
            if file.lower().endswith(extensions):
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, MUSIC_DIR)
                
                meta = get_track_metadata(full_path)
                tech = get_audio_details(full_path)
                
                songs.append({
                    "path": rel_path,
                    "filename": file,
                    "title": meta["title"],
                    "artist": meta["artist"],
                    "album": meta["album"],
                    "tech": tech
                })
    
    return jsonify(songs)

@app.route("/api/play", methods=["POST"])
def play_song():
    data = request.json
    song_path = data.get("path")
    if not song_path:
        return jsonify({"error": "No song path provided"}), 400
    
    full_path = os.path.join(MUSIC_DIR, song_path)
    if not os.path.exists(full_path):
        return jsonify({"error": "File not found"}), 404
    
    # Send technical info back to UI for the 'Now Playing' display
    tech = get_audio_details(full_path)
    meta = get_track_metadata(full_path)
    
    send_mpv_command(["loadfile", full_path])
    return jsonify({
        "status": "success",
        "track": {"title": meta["title"], "artist": meta["artist"], "tech": tech}
    })

@app.route("/api/stop", methods=["POST"])
def stop():
    send_mpv_command(["stop"])
    return jsonify({"status": "Stopped"})

@app.route("/api/status")
def status():
    """Return current playback position and total duration for the seek slider."""
    position = send_mpv_query(["get_property", "time-pos"])
    duration = send_mpv_query(["get_property", "duration"])
    paused   = send_mpv_query(["get_property", "pause"])
    return jsonify({
        "position": round(position, 2) if isinstance(position, (int, float)) else 0,
        "duration": round(duration, 2) if isinstance(duration, (int, float)) else 0,
        "paused":   paused if isinstance(paused, bool) else True,
    })

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

@app.route("/api/volume", methods=["GET", "POST"])
def volume_api():
    if request.method == "POST":
        val = request.json.get("volume")
        new_val = set_system_volume(val)
        return jsonify({"volume": new_val})
    else:
        return jsonify({"volume": get_current_volume()})

if __name__ == "__main__":
    start_mpv()
    app.run(host="0.0.0.0", port=5000, debug=False)
