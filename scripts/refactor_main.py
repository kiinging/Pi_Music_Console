import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
MAIN_FILE = BASE_DIR / "app" / "main.py"
MAIN_NEW = BASE_DIR / "app" / "main_new.py"

with open(MAIN_FILE, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Imports
content = re.sub(
    r"import json",
    "import json\nimport sqlite3",
    content,
    count=1
)

# 2. Global variables & Caches
content = re.sub(
    r"# --- Metadata Caching ---.*?IPC_SOCKET = \"/tmp/mpvsocket\"",
    """# --- Metadata Caching ---
# Caches replaced by SQLite database
DB_PATH = BASE_DIR / "media.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# Media Sources (Organized Structure)
MEDIA_SOURCES = [
    {"path": os.path.expanduser("~/Music"), "type": "music"},  # Primary Music (FLAC/MP3)
    {"path": os.path.expanduser("~/Video"), "type": "video"},  # Primary Video
    {"path": os.path.expanduser("~/video"), "type": "video"},  # Fallback
    {"path": os.path.expanduser("~/Videos"), "type": "video"}, # Fallback
]

MUSIC_DIR = next((s["path"] for s in MEDIA_SOURCES if s["type"] == "music" and os.path.exists(s["path"])), os.path.expanduser("~/Music"))
VIDEO_DIR = next((s["path"] for s in MEDIA_SOURCES if s["type"] == "video" and os.path.exists(s["path"])), os.path.expanduser("~/Videos"))

IPC_SOCKET = "/tmp/mpvsocket\"""",
    content,
    flags=re.DOTALL
)

# 3. get_track_metadata: remove META_CACHE usage
content = re.sub(
    r"def get_track_metadata\(file_path\):.*?META_CACHE\[file_path\] = metadata\n    return metadata",
    """def get_track_metadata(file_path):
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
    return metadata""",
    content,
    flags=re.DOTALL
)

# 4. load_metadata & load_album_metadata removal
content = re.sub(
    r"def load_metadata\(\):.*?return {}\n\n",
    "",
    content,
    flags=re.DOTALL
)
content = re.sub(
    r"def load_album_metadata\(\):.*?return {}\n\n",
    "",
    content,
    flags=re.DOTALL
)

# 5. System State functions
content = re.sub(
    r"def load_system_state\(\):.*?return \{\"volume\": 85, \"cache\": \{\}\}",
    """def load_system_state():
    try:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT key, value FROM settings")
            rows = c.fetchall()
            if rows:
                state = {row['key']: json.loads(row['value']) for row in rows}
                return state
    except: pass
    return {"volume": 85, "audio_output": "pcm5122"}""",
    content,
    flags=re.DOTALL
)
content = re.sub(
    r"def save_system_state\(state\):.*?except: pass",
    """def save_system_state(state):
    try:
        with get_db() as conn:
            c = conn.cursor()
            for k, v in state.items():
                c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, json.dumps(v)))
            conn.commit()
    except: pass""",
    content,
    flags=re.DOTALL
)

# 6. /api/songs
content = re.sub(
    r"@app\.route\(\"/api/songs\"\)\ndef list_songs\(\):.*?return jsonify\(songs\)",
    """@app.route("/api/songs")
def list_songs():
    requested_type = request.args.get('type')
    songs = []
    try:
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
                song = dict(row)
                album_name = song.get('album')
                if song.get('type') == 'music' and album_name in albums_map:
                    a_override = albums_map[album_name]
                    if a_override.get('artist'): song['artist'] = a_override['artist']
                    if a_override.get('category'): song['category'] = a_override['category']
                    if a_override.get('rating') is not None: song['rating'] = a_override['rating']
                
                song['tech'] = {
                    'duration': song.get('duration'),
                    'sample_rate': song.get('sample_rate'),
                    'bit_depth': song.get('bit_depth'),
                    'format': song.get('format')
                }
                song['base_dir'] = VIDEO_DIR if song['type'] == 'video' else MUSIC_DIR
                songs.append(song)
    except Exception as e:
        print("Error fetching songs:", e)
        
    songs.sort(key=lambda x: (int(x.get('disc_number', 1) or 1), int(x.get('track_number', 0) or 0), x['filename'].lower()))
    return jsonify(songs)""",
    content,
    flags=re.DOTALL
)

# 7. /api/songs/update
content = re.sub(
    r"@app\.route\(\"/api/songs/update\", methods=\[\"POST\"\]\)\ndef update_song_metadata\(\):.*?return jsonify\(\{\"status\": \"success\"\}\)",
    """@app.route("/api/songs/update", methods=["POST"])
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
        return jsonify({"error": str(e)}), 500""",
    content,
    flags=re.DOTALL
)

# 8. /api/songs/rename
content = re.sub(
    r"@app\.route\(\"/api/songs/rename\", methods=\[\"POST\"\]\)\ndef rename_song_file\(\):.*?except Exception as e: return jsonify\(\{\"error\": str\(e\)\}\), 500",
    """@app.route("/api/songs/rename", methods=["POST"])
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
    except Exception as e: return jsonify({"error": str(e)}), 500""",
    content,
    flags=re.DOTALL
)

# 9. /api/songs/delete
content = re.sub(
    r"@app\.route\(\"/api/songs/delete\", methods=\[\"POST\"\]\)\ndef delete_song\(\):.*?return jsonify\(\{\"error\": \"Not found\"\}\), 404",
    """@app.route("/api/songs/delete", methods=["POST"])
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
    return jsonify({"error": "Not found"}), 404""",
    content,
    flags=re.DOTALL
)

# 10. remove save_metadata & save_album_metadata
content = re.sub(
    r"def save_metadata\(metadata\):.*?except: return False\n",
    "",
    content,
    flags=re.DOTALL
)
content = re.sub(
    r"def save_album_metadata\(album_metadata\):.*?except:\n        return False\n",
    "",
    content,
    flags=re.DOTALL
)

# 11. /api/albums/update
content = re.sub(
    r"@app\.route\(\"/api/albums/update\", methods=\[\"POST\"\]\)\ndef update_album_metadata\(\):.*?return jsonify\(\{\"status\": \"success\"\}\)",
    """@app.route("/api/albums/update", methods=["POST"])
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
                if field in data: album[field] = data[field]
                
            c.execute("INSERT OR REPLACE INTO albums (name, artist, category, rating) VALUES (?, ?, ?, ?)", 
                      (album["name"], album["artist"], album["category"], album["rating"]))
            conn.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500""",
    content,
    flags=re.DOTALL
)

# 12. /api/status
content = re.sub(
    r"    if full_path:\n        meta = get_track_metadata\(full_path\).*?if field in p_meta\[path\]: meta\[field\] = p_meta\[path\]\[field\]",
    """    if full_path:
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
        except: pass""",
    content,
    flags=re.DOTALL
)

# 13. get_audio_details: remove TECH_CACHE
content = re.sub(
    r"def get_audio_details\(f_path\):.*?if f_path in TECH_CACHE: return TECH_CACHE\[f_path\]\n    try:",
    """def get_audio_details(f_path):
    try:""",
    content,
    flags=re.DOTALL
)
content = re.sub(
    r"        TECH_CACHE\[f_path\] = \{\n            \"sample_rate\": s\.get\(\"sample_rate\"\),\n            \"bit_depth\":   s\.get\(\"bits_per_sample\"\),\n            \"format\":      f\.get\(\"format_name\"\),\n            \"bit_rate\":    f\.get\(\"bit_rate\"\),\n            \"duration\":    float\(f\.get\(\"duration\", 0\) or 0\)\n        \}\n        return TECH_CACHE\[f_path\]",
    """        return {
            "sample_rate": s.get("sample_rate"),
            "bit_depth":   s.get("bits_per_sample"),
            "format":      f.get("format_name"),
            "bit_rate":    f.get("bit_rate"),
            "duration":    float(f.get("duration", 0) or 0)
        }""",
    content,
    flags=re.DOTALL
)

# 14. background_scanner
content = re.sub(
    r"def background_scanner\(\):.*?print\(f\"\[\*\] Metadata Scanner: Scan complete\. Total \{count\} files updated\.\"\)",
    """def background_scanner():
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
                        c.execute("SELECT sample_rate FROM media_items WHERE path=?", (rel_path,))
                        row = c.fetchone()
                        if not row or not row['sample_rate']:
                            needs_scan = True
                except: needs_scan = True
                
                if needs_scan:
                    try:
                        m = get_track_metadata(f_path)
                        t = get_audio_details(f_path) if not is_video else {}
                        
                        with get_db() as conn:
                            c = conn.cursor()
                            c.execute('''
                                INSERT INTO media_items 
                                (path, type, filename, title, artist, album, track_number, disc_number, duration, sample_rate, bit_depth, format)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                ON CONFLICT(path) DO UPDATE SET
                                duration=excluded.duration,
                                sample_rate=excluded.sample_rate,
                                bit_depth=excluded.bit_depth,
                                format=excluded.format
                            ''', (
                                rel_path, typ, f, m["title"], m["artist"], m.get("album", "Unknown Album"),
                                m.get("track_number", 0), m.get("disc_number", 1),
                                t.get("duration", 0), t.get("sample_rate", ""), t.get("bit_depth", ""), t.get("format", "")
                            ))
                            conn.commit()
                        count += 1
                        time.sleep(0.3)
                    except Exception as e:
                        print(f"[!] Metadata Scanner Error on {f}: {e}")
                        
    print(f"[*] Metadata Scanner: Scan complete. Total {count} files updated.")""",
    content,
    flags=re.DOTALL
)

with open(MAIN_NEW, "w", encoding="utf-8") as f:
    f.write(content)
