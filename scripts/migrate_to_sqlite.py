import os
import json
import sqlite3
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "media.db"

VIDEO_METADATA_FILE = BASE_DIR / "video_metadata.json"
ALBUM_METADATA_FILE = BASE_DIR / "album_metadata.json"
STATE_FILE = BASE_DIR / "system_state.json"

def init_db(conn):
    c = conn.cursor()
    # Table for media items (songs/videos)
    c.execute('''
        CREATE TABLE IF NOT EXISTS media_items (
            path TEXT PRIMARY KEY,
            type TEXT,
            filename TEXT,
            title TEXT,
            artist TEXT,
            album TEXT,
            track_number INTEGER,
            disc_number INTEGER,
            category TEXT,
            rating INTEGER,
            duration REAL,
            sample_rate TEXT,
            bit_depth TEXT,
            format TEXT,
            bit_rate TEXT,
            last_scanned TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Table for albums (overrides)
    c.execute('''
        CREATE TABLE IF NOT EXISTS albums (
            name TEXT PRIMARY KEY,
            artist TEXT,
            category TEXT,
            rating INTEGER
        )
    ''')

    # Table for settings
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    conn.commit()

def migrate_settings(conn):
    if not STATE_FILE.exists():
        return
    with open(STATE_FILE, 'r') as f:
        try:
            state = json.load(f)
        except Exception:
            return

    c = conn.cursor()
    settings = {
        'volume': state.get('volume', 85),
        'audio_output': state.get('audio_output', 'pcm5122')
    }
    for k, v in settings.items():
        c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, json.dumps(v)))
    
    # Migrate Cache
    cache = state.get('cache', {})
    for path, data in cache.items():
        meta = data.get('meta', {})
        tech = data.get('tech', {})
        title = meta.get('title', os.path.basename(path))
        artist = meta.get('artist', 'Unknown Artist')
        album = meta.get('album', 'Unknown Album')
        track_number = meta.get('track_number', 0)
        disc_number = meta.get('disc_number', 1)
        
        duration = tech.get('duration', 0)
        sample_rate = tech.get('sample_rate', '')
        bit_depth = tech.get('bit_depth', '')
        fmt = tech.get('format', '')
        
        is_video = path.lower().endswith(('.mp4', '.mkv', '.avi', '.mov', '.webm'))
        typ = 'video' if is_video else 'music'

        c.execute('''
            INSERT OR REPLACE INTO media_items 
            (path, type, filename, title, artist, album, track_number, disc_number, duration, sample_rate, bit_depth, format)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (path, typ, os.path.basename(path), title, artist, album, track_number, disc_number, duration, sample_rate, bit_depth, fmt))

    conn.commit()

def migrate_video_metadata(conn):
    if not VIDEO_METADATA_FILE.exists():
        return
    with open(VIDEO_METADATA_FILE, 'r') as f:
        try:
            v_meta = json.load(f)
        except Exception:
            return

    c = conn.cursor()
    for path, meta in v_meta.items():
        title = meta.get('title', os.path.basename(path))
        artist = meta.get('artist', 'Unknown Artist')
        album = meta.get('album', 'Unknown Album')
        category = meta.get('category', 'All')
        rating = meta.get('rating', 0)
        
        c.execute('''
            INSERT INTO media_items (path, type, filename, title, artist, album, category, rating)
            VALUES (?, 'video', ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
            title=excluded.title,
            artist=excluded.artist,
            album=excluded.album,
            category=excluded.category,
            rating=excluded.rating
        ''', (path, os.path.basename(path), title, artist, album, category, rating))

    conn.commit()

def migrate_album_metadata(conn):
    if not ALBUM_METADATA_FILE.exists():
        return
    with open(ALBUM_METADATA_FILE, 'r') as f:
        try:
            a_meta = json.load(f)
        except Exception:
            return

    c = conn.cursor()
    for album_name, meta in a_meta.items():
        artist = meta.get('artist', '')
        category = meta.get('category', '')
        rating = meta.get('rating', 0)
        real_album_name = meta.get('album', album_name)

        c.execute('''
            INSERT OR REPLACE INTO albums (name, artist, category, rating)
            VALUES (?, ?, ?, ?)
        ''', (real_album_name, artist, category, rating))

    conn.commit()

if __name__ == '__main__':
    conn = sqlite3.connect(DB_PATH)
    print(f"Initializing database at {DB_PATH}")
    init_db(conn)
    
    print("Migrating system state and cache...")
    migrate_settings(conn)
    
    print("Migrating video metadata...")
    migrate_video_metadata(conn)
    
    print("Migrating album metadata...")
    migrate_album_metadata(conn)
    
    conn.close()
    print("Migration complete!")
