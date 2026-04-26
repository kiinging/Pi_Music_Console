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

class SmartVoiceManager:
    def __init__(self):
        self.proc = None
        # Look in current dir, then parent
        base = Path(__file__).parent
        self.script_path = base / "smart_voice_unit" / "voice_controller.py"
        if not self.script_path.exists():
            self.script_path = base.parent / "smart_voice_unit" / "voice_controller.py"

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
        except subprocess.CalledProcessError:
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

def start_mpv():
    """Start mpv in the background if it's not already running."""
    if os.path.exists(IPC_SOCKET):
        return

    print("Starting mpv in background...")
    subprocess.Popen([
        "mpv",
        "--idle",
        "--input-ipc-server=" + IPC_SOCKET,
        "--ao=alsa",        # Use ALSA directly — skips PipeWire (avoids pw.conf warnings)
        "--no-terminal"
    ])
    time.sleep(1)

def get_audio_details(file_path):
    """Use ffprobe to get technical details (sample rate, bit depth)."""
    try:
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "stream=codec_type,sample_rate,bits_per_sample,channels:format=format_name,bit_rate,duration",
            "-of", "json", file_path
        ]
        # use a 3-second timeout so it doesn't hang forever on bad files
        result = subprocess.check_output(cmd, timeout=3).decode("utf-8")
        data = json.loads(result)
        
        streams = data.get("streams", [])
        # Find the first audio stream to show audio tech specs
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
    except Exception as e:
        print(f"ffprobe error: {e}")
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
    """List all supported media files with their metadata."""
    media_type = request.args.get('type', 'music')
    base_dir = VIDEO_DIR if media_type == 'video' else MUSIC_DIR
    
    songs = []
    extensions = ('.mp3', '.flac', '.wav', '.m4a', '.ogg', '.mp4', '.mkv', '.avi', '.mov', '.webm')
    
    if os.path.exists(base_dir):
        for root, _, files in os.walk(base_dir):
            for file in files:
                if file.lower().endswith(extensions):
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, base_dir)
                    
                    meta = get_track_metadata(full_path)
                    tech = get_audio_details(full_path)
                    
                    songs.append({
                        "path": rel_path,
                        "type": media_type,
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
    media_type = data.get("type", "music")
    
    base_dir = VIDEO_DIR if media_type == 'video' else MUSIC_DIR
    
    if not song_path:
        return jsonify({"error": "No song path provided"}), 400
    
    full_path = os.path.join(base_dir, song_path)
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
    vid      = send_mpv_query(["get_property", "vid"])
    return jsonify({
        "position": round(position, 2) if isinstance(position, (int, float)) else 0,
        "duration": round(duration, 2) if isinstance(duration, (int, float)) else 0,
        "paused":   paused if isinstance(paused, bool) else True,
        "video_enabled": (str(vid).lower() not in ("no", "false", "none")),
    })

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

@app.route("/api/volume", methods=["GET", "POST"])
def volume_api():
    if request.method == "POST":
        val = request.json.get("volume")
        new_val = set_system_volume(val)
        return jsonify({"volume": new_val})
    else:
        return jsonify({"volume": get_current_volume()})

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

if __name__ == "__main__":
    start_mpv()
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
