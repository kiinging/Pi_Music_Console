# Pi Music Console - Architecture & Logic Documentation

This document describes the core architecture, data flow, and design decisions of the Pi Music Console application. This is the authoritative reference to prevent breaking changes during future improvements.

---

## 1. Folder Structure & Media Discovery

### Media Source Configuration

The application scans media from two predefined sources defined in `MEDIA_SOURCES`:

```python
MEDIA_SOURCES = [
    {"path": os.path.expanduser("~/Music"), "type": "music"},
    {"path": os.path.expanduser("~/Video"), "type": "video"},
]

MUSIC_DIR = os.path.expanduser("~/Music")
VIDEO_DIR = os.path.expanduser("~/Video")
```

**Key Points:**
- **Music source:** `~/Music` folder (albums organized by folder name)
- **Video source:** `~/Video` folder (flexible structure, no album grouping)
- **Simplified config:** Single path per type — no fallback paths needed
- **Distinction:** Type is declared *in code*, not inferred from folder name alone
- **File extension validation:** Each file is validated against expected extensions during scanning

### File Extension Classification

File types are determined by extension alone, regardless of folder location:

| Type | Extensions |
|------|------------|
| **Audio/Music** | `.mp3`, `.flac`, `.wav`, `.m4a`, `.ogg` |
| **Video** | `.mp4`, `.mkv`, `.avi`, `.mov`, `.webm` |

If a music file is found in the Video folder (or vice versa), it will be correctly labeled by file extension during the `background_scanner()` run.

---

## 2. Folder Organization & Album Concept

### Music Folder Structure

Music in `~/Music` is organized by **album folder names**:

```
~/Music/
├── 1432 - Katy Perry/
│   ├── 01 - Katy Perry - WOMAN'S WORLD.flac
│   ├── 02 - Katy Perry - GIMME GIMME.flac
│   └── ...
├── Beethoven - 9 Symphonies - Berliner Philharmoniker/
│   ├── Disc 1/
│   │   ├── 01 - Movement I.flac
│   │   └── ...
│   └── Disc 2/
│       └── ...
└── [Album Name]/
    └── [Audio Files]
```

**Album Key Definition:**
- The **top-level folder name** is used as the album identifier
- Example: `"1432 - Katy Perry"` is the album key for all tracks within that folder
- Multi-disc albums can have subfolders like `Disc 1/`, `Disc 2/` — the album key is still the parent folder
- The `album` field in the database stores a *short or tagged identifier* (e.g., `"1432"` or extracted from metadata tags)

### Video Folder Structure

Video files can be organized flexibly within `~/Video`:

```
~/Video/
├── Concert_2024.mp4
├── Documentary/
│   ├── episode_1.mkv
│   └── episode_2.mkv
└── [Any structure]
```

**Video Key Definition:**
- No strict folder-based album concept for videos
- Videos are treated as individual items (not grouped by folder)
- The `path` field stores the relative path from `~/Video`
- No multi-disc parsing for videos

---

## 3. Database Schema & Storage Model

### Single SQLite File: `media.db`

**Why one file instead of separate files?**
1. **Simpler deployment:** Single database file to backup and restore
2. **Atomic transactions:** Updates affect both music and video metadata in one place
3. **Unified settings table:** Volume, audio output, etc. are shared
4. **Query efficiency:** Filtering across type is straightforward with a single schema
5. **Shared category/rating system:** Both music and video use the same normalization logic

### Database Tables

#### `media_items` (Core media records)

| Column | Type | Purpose |
|--------|------|---------|
| `path` | TEXT (PRIMARY KEY) | Relative path from media source (e.g., `"1432 - Katy Perry/01 - Track.flac"`) |
| `type` | TEXT | Either `'music'` or `'video'` |
| `filename` | TEXT | Just the filename component |
| `title` | TEXT | Display title (from tags or filename) |
| `artist` | TEXT | Artist name (from tags) |
| `album` | TEXT | Album identifier (from tags or folder parsing) |
| `track_number` | INTEGER | Track position within album (for music only) |
| `disc_number` | INTEGER | Disc number for multi-disc albums (defaults to 1) |
| `category` | TEXT | User-assigned category (e.g., `"Pop"`, `"Classical"`) |
| `rating` | INTEGER | User rating (0–3 stars) |
| `duration` | REAL | Duration in seconds (video may have 0) |
| `sample_rate` | TEXT | Audio sample rate (e.g., `"44100"`) |
| `bit_depth` | TEXT | Bit depth (e.g., `"16"`, `"24"`) |
| `format` | TEXT | Format string (e.g., `"flac"`, `"mp4"`) |
| `last_scanned` | TIMESTAMP | When metadata was last updated |

#### `albums` (Metadata overrides for music albums only)

| Column | Type | Purpose |
|--------|------|---------|
| `name` | TEXT (PRIMARY KEY) | Album folder name (e.g., `"1432 - Katy Perry"`) |
| `artist` | TEXT | Override artist name (applies to all tracks in album) |
| `category` | TEXT | Override category (applies to all tracks in album) |
| `rating` | INTEGER | Override rating (applies to all tracks in album) |

**Why separate `albums` table?**
- Album-level metadata (artist, category, rating) should override track-level data from tags
- Editing an album's category should update all tracks at once
- The frontend renders albums as groups, so album-level metadata is needed

#### `settings` (System state)

| Column | Type | Purpose |
|--------|------|---------|
| `key` | TEXT (PRIMARY KEY) | Setting name (e.g., `"volume"`, `"audio_output"`) |
| `value` | TEXT | JSON-encoded value |

---

## 4. Album Metadata Override Logic

### How Album Overrides Work

When the `/api/songs` endpoint is called (for music type), the application:

1. **Fetches all music items from `media_items` table**
2. **Loads the `albums` table** into a lookup map by album name
3. **For each music track**, attempts to match it to an album override:
   - First tries: album field from `media_items` 
   - Second tries: top-level folder name extracted from path
   - On match, applies overrides from `albums` table:
     - `artist` → replaces track artist
     - `category` → replaces track category
     - `rating` → replaces track rating

### Category Matching Logic

**Album folder name to override matching:**

```
Path: "1432 - Katy Perry/01 - Track.flac"
├─ Extract top folder: "1432 - Katy Perry"
└─ Lookup in albums table WHERE name = "1432 - Katy Perry"
   └─ Found! Apply overrides (artist, category, rating)
```

**Path format handling:**
- Absolute paths: `/home/pizza/Music/1432 - Katy Perry/01 - Track.flac`
- Relative paths: `1432 - Katy Perry/01 - Track.flac`
- Both are normalized to extract top-level folder name

### Category Normalization

All categories are normalized to a standard set:

```python
def normalize_category(value):
    if not value: return None
    aliases = {
        'pop': 'Pop',
        'rock': 'Rock',
        'classical': 'Classical',
        'spanish': 'Spanish',
        'chinese': 'Chinese'
    }
    return aliases.get(value.lower(), value)
```

**Why?** Ensures consistent display and filtering regardless of how users input categories ("POP", "pop", "Pop" all become "Pop").

---

## 5. Media Discovery & Metadata Scanning

### `background_scanner()` Process

Runs asynchronously on startup (after 30-second delay):

1. **Iterates through all `MEDIA_SOURCES`** (~/Music and ~/Video)
2. **Walks directory tree** for files with music/video extensions
3. **For each file:**
   - Calculates relative path from source directory
   - Checks if already in database (by path)
   - If missing sample_rate (metadata incomplete):
     - Extracts title, artist, album from file tags using `mutagen`
     - Extracts disc number from folder names (e.g., "Disc 2")
     - **Extracts track number:** First from tags; if missing, parses from filename (e.g., "05 - Title.flac" → track 5)
     - Calls `ffprobe` for technical details (sample_rate, bit_depth, format, duration)
     - **Inserts/updates** into `media_items` table
4. **Throttles with 0.3s sleep** between files to avoid system load

**Key Distinctions:**
- **Music files:** Full metadata extraction (tags, disc number, track number parsing)
- **Video files:** Minimal metadata extraction (basic title, no disc parsing)
- **Category field:** Not populated by scanner (user-assigned only)
- **Album field:** Populated from tags for music, used as lookup key for overrides

### Track Number Extraction Logic

Track numbers are essential for proper album display sorting. The extraction follows a two-step process:

1. **First attempt:** Extract from file tags using `mutagen`
2. **Fallback:** If tags have no track number, parse from filename:
   - Pattern: `^(\d+)\s*[-\s]` (e.g., "05 - Title.flac", "05-Title.flac", "05 Title.flac")
   - Extracts the leading number as track_number
   - Prevents tracks from being hidden due to missing track data

**Example:**
```
File: "05 - Eydie Gorme - Historia de un Amor.flac"
Result: track_number = 5 (extracted from filename)
```

**Why?** Some FLAC files may not have track number tags but have them in the filename. This fallback ensures all tracks are discoverable and sortable.

---

## 6. Frontend Display & Filtering Logic

### Music Tab Display

**Album Grid View (when `currentAlbum === null`):**
- Groups tracks by album (top-level folder name)
- Displays one card per album showing:
  - Album cover image
  - Album name
  - Artist name (from first track or album override)
  - **Category badge** (from first track with a non-empty category, prioritizing album override)
  - Track count

**Album Tracks View (when `currentAlbum` is set):**
- Shows all tracks within selected album
- Organizes by disc number if multi-disc
- Displays per-track technical details:
  - Format (FLAC, MP3, etc.)
  - Sample rate (kHz)
  - Bit depth badge (24BIT)
  - Hi-res badge (if ≥88.2kHz)

**Filters Available for Music:**
- **Category filter:** (buttons for Pop, Rock, Classical, Spanish, Chinese, All)
- **Artist filter:** (auto-generated from albums in selected category)
- **Rating filter:** (hidden for music — shows for videos only)

### Video Tab Display

**Video List View:**
- Shows individual videos (not grouped)
- Each video displays:
  - Video title
  - Artist/Creator
  - **Category badge** (if assigned)
  - Star rating (if assigned)
  - Technical details: Format, sample rate, kbps

**Filters Available for Videos:**
- **Category filter:** (same as music)
- **Artist filter:** (auto-generated from videos in selected category)
- **Star rating filter:** (★★★, ★★, ★, All)

**Why different filters?**
- Videos are often single items → no album grouping
- Videos need star rating as primary quality indicator
- Videos benefit from artist/creator filtering for multi-creator collections

---

## 7. Technical Details Display

### What's Displayed for Music Tracks

In the album tracks view, each track shows:

```
Track Number | Title | [HI-RES] [24BIT] | Format • SampleRate • BitRate
```

Example:
```
01 | Woman's World | [HI-RES] [24BIT] | FLAC • 96.0kHz • 3000kbps
```

**Extraction logic:**
```python
fmt = (s.tech.format or '').toUpperCase()        # "FLAC"
sr = s.tech.sample_rate ? f"{sr/1000:.1f}kHz"   # "44.1kHz"
br = s.tech.bit_rate ? f"{br/1000:.0f}kbps"     # "320kbps"
hires = sample_rate >= 88200                     # Badge display
b24 = bit_depth >= 24                            # Badge display
```

**Key columns used from database:**
- `format` → Format type
- `sample_rate` → Sampling frequency (stored as integer in Hz, displayed in kHz)
- `bit_depth` → Bits per sample (used for 24-bit badge)
- `bit_rate` → Bitrate (shown in kbps)
- `duration` → Total time

### What's Displayed for Videos

In the video list, each video shows:

```
Title | Category Badge | Artist Badge | ★★★ | Format • SampleRate • BitRate
```

Same technical details as music, but in a horizontal list layout.

---

## 8. Edit & Save Flow

### Album-Level Edits (Music Only)

When user clicks "Edit Album" on an album card:

1. **Modal opens** with fields:
   - Album name (read-only)
   - Artist (editable)
   - Category (dropdown: All, Pop, Rock, Classical, Spanish, Chinese)
   - Star rating (1–3 stars)

2. **On save:**
   - POST to `/api/albums/update`
   - Payload: `{ album: "folder_name", artist: "...", category: "...", rating: N }`
   - **Action:** Inserts/replaces in `albums` table
   - **Effect:** Next time `/api/songs` is fetched, all tracks in that album get the new category

3. **Category normalization** occurs on save:
   - User inputs "pop" → normalized to "Pop" before storing

### Track-Level Edits

When user clicks "☰" on a track:

1. **Modal opens** with fields:
   - Title (editable, or locked to filename)
   - Artist (editable)
   - Category (dropdown)
   - Star rating

2. **On save:**
   - POST to `/api/songs/update`
   - Payload: `{ path: "rel_path", title: "...", artist: "...", category: "...", rating: N }`
   - **Action:** Updates the `media_items` table directly for that track
   - **Note:** This is overridden by album-level metadata if both exist

---

## 9. Category System Overview

### Category Values

Supported categories (case-insensitive, normalized on save):
- `Pop`
- `Rock`
- `Classical`
- `Spanish`
- `Chinese`
- `All` (filter button, not a storable value)
- Custom values are stored as-is but not normalized

### How Categories Flow

1. **Database:** Stored in `media_items.category` (for individual tracks) and `albums.category` (for album overrides)
2. **Normalization:** Applied on save (front-end + back-end) and on display
3. **Filtering:**
   - User selects category → frontend filters tracks by normalized category
   - Tracks matching the category are shown
   - Artist filter dynamically updates based on filtered results

### Album vs. Video Category Behavior

| Aspect | Music Albums | Videos |
|--------|--------------|--------|
| Category storage | Track-level + album override | Track-level only |
| Category edit | Via album card (applies to all) | Per-video edit |
| Filter position | Primary filter (shown first) | Secondary filter |
| Default | "Uncategorized" if empty | Empty string → "All" |

---

## 10. Current Architecture Summary

| Aspect | Current Design | Reasoning |
|--------|-----------------|-----------|
| **Database files** | Single `media.db` (SQLite) | Simplicity, atomic updates, unified queries |
| **Media sources** | `~/Music` (albums) + `~/Video` (videos) | Simplified, single path per type, no fallbacks |
| **Album organization** | Folder-based (top-level folder name) | Matches user's file system organization |
| **Metadata extraction** | File tags + folder parsing + ffprobe + filename fallback | Handles FLAC tags + disc numbers + track numbers + technical specs |
| **Category storage** | Two layers (track + album override) | Album-level categories affect all tracks |
| **Filter types** | Category → Artist → Stars (for video) | Progressive refinement, video-specific ratings |
| **Multi-disc support** | Yes (disc_number column) | Supports classical/boxed sets |
| **Technical details** | Full capture (format, SR, BD, BR) | Displayed for music tracks and videos |

---

## 11. Future Improvement Considerations

### Potential Separate Database Architecture

If separating into `music.db` and `video.db`:

**Advantages:**
- Optimized schemas for each type (e.g., video without `disc_number`)
- Easier to scale one collection independently
- Different retention policies (archive music differently than videos)
- Possibility of different indexing strategies

**Disadvantages:**
- Settings table duplication (maintain in both files)
- Complex transaction handling (keep both in sync)
- Complicates backup/restore workflow
- Frontend must know which database to query

**Recommendation:** Keep unified database unless:
1. Music collection exceeds 10,000+ tracks (performance concern)
2. Video collection requires radically different schema (unlikely)
3. Scale demands separate infrastructure

### Recommended Improvements Without Schema Changes

1. **Video-specific fields:** Add `video_codec`, `audio_codec`, `resolution` columns (backward compatible)
2. **Smart category defaults:** Auto-assign categories based on filename/folder patterns
3. **Search/fuzzy matching:** Add full-text search on title, artist, album
4. **Playlist support:** Add `playlists` table linking to media items
5. **User profiles:** Track different users' ratings/preferences separately
6. **Advanced filters:** Combine category + artist + rating + format in a single query
7. **Import/export:** Backup album metadata to JSON, restore on new system

---

## 12. API Reference (Summary)

### Key Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/songs` | GET | List all songs (music or video), with overrides applied |
| `/api/albums/update` | POST | Update album-level metadata (artist, category, rating) |
| `/api/songs/update` | POST | Update track-level metadata |
| `/api/songs/delete` | POST | Delete a song file and database record |
| `/api/cover` | GET | Retrieve album cover image |
| `/api/status` | GET | Get playback status and current track details |
| `/api/play` | POST | Play a track |
| `/api/pause`, `/api/resume` | POST | Control playback |

---

## 13. Important Constraints & Assumptions

1. **Album folder naming:** Album key must match the top-level folder name exactly (case-sensitive)
2. **Metadata precedence:** Album overrides trump track-level data from tags
3. **Single audio output:** AUDIO_OUTPUT is global (one device for all playback)
4. **Relative paths:** Database stores paths relative to media source, not absolute
5. **No remapping:** If a file is moved to a different album folder, it becomes a separate entry
6. **Throttled scanning:** Background scanner runs once, doesn't watch for new files in real-time

---

## 14. Modification Guidelines

When making changes to this system:

1. **Media source paths:** `MEDIA_SOURCES` contains exactly two entries: `~/Music` (music only) and `~/Video` (video only). Do not add fallback paths.
2. **Update both front-end and back-end:** Category normalization must match in `main.py` and `desktop.html`
3. **Validate album key matching:** Any changes to path parsing must account for both absolute and relative paths
4. **Test multi-disc albums:** Verify disc number parsing still works when modifying folder logic
5. **Track number extraction:** Always try tags first; only use filename parsing as fallback. Maintain the regex pattern `^(\d+)\s*[-\s]` if modifying
6. **Backward compatibility:** New columns should have default values; don't require existing records to be rewritten
7. **Schema migrations:** Use `ON CONFLICT(path) DO UPDATE` pattern to avoid data loss during updates
8. **Filter consistency:** If adding new category values, update the dropdown in the edit modal AND the normalization function
9. **Display sorting:** Any changes to album display must preserve sorting by disc_number, then track_number

---

**Document Version:** 1.1  
**Last Updated:** 2026-08-14  
**Changes in v1.1:** Simplified MEDIA_SOURCES to single path per type; added track number filename extraction fallback  
**Author:** Architecture Documentation
