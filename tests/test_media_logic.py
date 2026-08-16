import importlib.util
import sqlite3
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_main_module():
    spec = importlib.util.spec_from_file_location('music_console_main', ROOT / 'app' / 'main.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_schema_includes_bit_rate_column():
    import scripts.migrate_to_sqlite as migrate

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / 'media.db'
        conn = sqlite3.connect(db_path)
        migrate.init_db(conn)
        columns = [row[1] for row in conn.execute('PRAGMA table_info(media_items)').fetchall()]
        assert 'bit_rate' in columns


def test_prune_missing_media_items_exists():
    module = load_main_module()
    assert hasattr(module, 'prune_missing_media_items')


def test_music_track_rating_not_overwritten_by_album_rating():
    module = load_main_module()
    track = {'artist': 'Original Artist', 'category': 'Rock', 'rating': 3}
    album = {'artist': 'Album Artist', 'category': 'Pop', 'rating': 1}

    result = module.apply_music_album_overrides(track, album)

    assert result['artist'] == 'Album Artist'
    assert result['category'] == 'Pop'
    assert result['rating'] == 3
