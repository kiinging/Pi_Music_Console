import os
import json
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
METADATA_FILE = BASE_DIR / "music_metadata.json"
MEDIA_SOURCES = [
    {"path": os.path.expanduser("~/Music"), "type": "music"},
    {"path": os.path.expanduser("~/Video"), "type": "video"},
    {"path": os.path.expanduser("~/video"), "type": "video"},
    {"path": os.path.expanduser("~/Videos"), "type": "video"},
]
EXTS = ('.mp3', '.flac', '.wav', '.m4a', '.ogg', '.mp4', '.mkv', '.avi', '.mov', '.webm')

def sync_metadata():
    print("[*] Syncing music_metadata.json with filesystem...")
    if METADATA_FILE.exists():
        try:
            with open(METADATA_FILE, 'r', encoding='utf-8') as f:
                p_meta = json.load(f)
        except Exception:
            p_meta = {}
    else:
        p_meta = {}

    current_files = set()

    for source in MEDIA_SOURCES:
        b_dir = source["path"]
        if os.path.exists(b_dir):
            for root, _, files in os.walk(b_dir):
                for f in files:
                    if f.lower().endswith(EXTS):
                        f_path = os.path.join(root, f)
                        rel = os.path.relpath(f_path, b_dir)
                        current_files.add(rel)
                        
                        if rel not in p_meta:
                            p_meta[rel] = {}
                        
                        if "title" not in p_meta[rel]:
                            p_meta[rel]["title"] = os.path.splitext(f)[0]
                        if "album" not in p_meta[rel]:
                            parent_dir = os.path.basename(root)
                            if parent_dir in ["Music", "Video", "Videos", "video", ""]:
                                p_meta[rel]["album"] = "Singles"
                            else:
                                p_meta[rel]["album"] = parent_dir

    keys_to_delete = [k for k in p_meta.keys() if k not in current_files]
    for k in keys_to_delete:
        del p_meta[k]

    with open(METADATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(p_meta, f, indent=4, ensure_ascii=False)
    
    print(f"[*] Sync complete. {len(keys_to_delete)} removed, {len(current_files)} total tracks.")

if __name__ == "__main__":
    sync_metadata()
