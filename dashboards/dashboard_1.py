import os
import socket
import json
import subprocess
import time
from flask import Flask, render_template, jsonify

app = Flask(__name__)

# Configuration
IPC_SOCKET = "/tmp/mpvsocket"
MUSIC_DIR = os.path.expanduser("~/Music")

def send_mpv_command(command_list):
    """Send a JSON IPC command to the running mpv process."""
    if not os.path.exists(IPC_SOCKET):
        return {"error": "mpv socket not found. Is mpv running?"}
    
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(IPC_SOCKET)
        payload = json.dumps({"command": command_list}) + "\n"
        client.send(payload.encode("utf-8"))
        # We don't necessarily need to wait for a response for simple commands
        client.close()
        return {"status": "success"}
    except Exception as e:
        return {"error": str(e)}

def start_mpv():
    """Start mpv in the background if it's not already running."""
    # Check if mpv is already running with the socket
    if os.path.exists(IPC_SOCKET):
        return

    print("Starting mpv in background...")
    subprocess.Popen([
        "mpv",
        "--idle",
        "--input-ipc-server=" + IPC_SOCKET,
        "--no-terminal"
    ])
    # Give it a second to start the socket
    time.sleep(1)

@app.route("/")
def index():
    return render_template("dashboard_1.html")

@app.route("/play")
def play():
    # For Dashboard 1, we just find the first music file in ~/Music
    files = [f for f in os.listdir(MUSIC_DIR) if f.lower().endswith(('.mp3', '.flac', '.wav', '.m4a'))]
    if not files:
        return jsonify({"error": "No music files found in ~/Music"})
    
    test_file = os.path.join(MUSIC_DIR, files[0])
    # Load and play the file
    send_mpv_command(["loadfile", test_file])
    return jsonify({"status": f"Playing {files[0]}"})

@app.route("/stop")
def stop():
    send_mpv_command(["stop"])
    return jsonify({"status": "Stopped"})

if __name__ == "__main__":
    start_mpv()
    # Host 0.0.0.0 makes it accessible to your smartphone on the same WiFi
    app.run(host="0.0.0.0", port=5000, debug=True)
