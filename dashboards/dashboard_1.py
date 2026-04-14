import os
import socket
import json
import subprocess
import time
from flask import Flask, render_template, jsonify, request
from pathlib import Path

try:
    from mutagen import File
except ImportError:
    File = None

app = Flask(__name__)

# Configuration
IPC_SOCKET = "/tmp/mpvsocket"
MUSIC_DIR = os.path.expanduser("~/Music")

# Ensure Music directory exists for testing
if not os.path.exists(MUSIC_DIR):
    os.makedirs(MUSIC_DIR, exist_ok=True)

def send_mpv_command(command_list):
    """Send a JSON IPC command to the running mpv process."""
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
    extensions = ('.mp3', '.flac', '.wav', '.m4a', '.ogg')
    
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

if __name__ == "__main__":
    start_mpv()
    app.run(host="0.0.0.0", port=5000, debug=True)
