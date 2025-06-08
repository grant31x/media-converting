# subtitlesmkv.py
# Version: 2.1
# This module scans media files and extracts subtitle track information or snippets.

import subprocess
import json
from pathlib import Path
from typing import List, Tuple
import logging
import re
try:
    from langdetect import detect, DetectorFactory
    # Ensure consistent results from langdetect
    DetectorFactory.seed = 0
    LANGDETECT_AVAILABLE = True
except ImportError:
    LANGDETECT_AVAILABLE = False
    logging.warning("langdetect library not found. Language detection will be skipped. Run 'pip install langdetect'")


# Import the data models from our models.py file
from models import MediaFile, SubtitleTrack

# --- Configuration for MKVToolNix ---
MKVTOOLNIX_PATH = Path("C:/Program Files/MKVToolNix/")
MKVMERGE_PATH = MKVTOOLNIX_PATH / "mkvmerge.exe"
MKVEXTRACT_PATH = MKVTOOLNIX_PATH / "mkvextract.exe"


def scan_directory(directory_path: Path) -> List[MediaFile]:
    """Scans a single directory recursively for .mkv files."""
    media_files = []
    if not MKVMERGE_PATH.exists():
        print(f"[ERROR] mkvmerge.exe not found at: {MKVMERGE_PATH}")
        return media_files
    if not directory_path.is_dir():
        return media_files

    for file_path in directory_path.rglob("*.mkv"):
        media_files.append(scan_file(file_path))
    return media_files


def scan_file(file_path: Path) -> MediaFile:
    """Scans a single MKV file for subtitle and audio tracks using mkvmerge."""
    media = MediaFile(source_path=file_path)
    media.status = "Scanning"
    try:
        # FIX: Calculate file size immediately on scan
        if file_path.exists():
            media.original_size_gb = file_path.stat().st_size / (1024**3)

        cmd = [str(MKVMERGE_PATH), "-J", str(file_path)]
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8')
        data = json.loads(result.stdout)
        
        subtitle_ffmpeg_index = 0
        audio_tracks_found, video_tracks_found = [], []
        
        media.container = data.get("container", {}).get("type", "Unknown")

        for track in data.get("tracks", []):
            properties = track.get("properties", {})
            if track.get("type") == "video":
                video_tracks_found.append({
                    'codec': track.get("codec"),
                    'width': properties.get("pixel_dimensions", "0x0").split('x')[0],
                    'fps': properties.get("video_frames_per_second", 0.0)
                })
            elif track.get("type") == "audio":
                audio_tracks_found.append({
                    'codec': track.get("codec"),
                    'channels': properties.get("audio_channels"),
                    'is_default': properties.get("default_track", False)
                })
            elif track.get("type") == "subtitles":
                media.subtitle_tracks.append(SubtitleTrack(
                    index=track.get("id"), ffmpeg_index=subtitle_ffmpeg_index,
                    language=properties.get("language", "und"), title=properties.get("track_name"),
                    codec=track.get("codec"), is_default=properties.get("default_track", False),
                    is_forced=properties.get("forced_track", False), is_text_based=properties.get("text_subtitles", False) 
                ))
                subtitle_ffmpeg_index += 1

        if video_tracks_found:
            primary_video = video_tracks_found[0]
            media.video_codec = primary_video['codec']
            media.video_width = int(primary_video['width'])
            media.video_fps = primary_video['fps']
        
        if audio_tracks_found:
            primary_audio = next((t for t in audio_tracks_found if t['is_default']), audio_tracks_found[0])
            media.audio_codec = primary_audio['codec']
            media.audio_channels = primary_audio['channels']

        media.update_flags()
        for track in media.subtitle_tracks:
            if track.language == "eng" and track.is_forced:
                track.action = "burn"; media.burned_subtitle = track
                break
        media.status = "Ready"
    except Exception as e:
        media.status = "Error"; media.error_message = f"Scan error: {e}"
    return media

def get_subtitle_details(mkv_file: Path, track_id: int) -> Tuple[str, str]:
    """
    Extracts a subtitle snippet and detects its language.
    """
    if not MKVEXTRACT_PATH.exists():
        return f"Error: mkvextract.exe not found.", "unknown"

    temp_srt_path = mkv_file.with_name(f"{mkv_file.stem}_preview_{track_id}.srt")
    
    try:
        command = [str(MKVEXTRACT_PATH), "tracks", str(mkv_file), f"{track_id}:{temp_srt_path}"]
        subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8')

        with open(temp_srt_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        
        text_lines = [line.strip() for line in content.splitlines() if not re.match(r'^\d+$', line.strip()) and '-->' not in line]
        clean_text = "\n".join(text_lines)
        
        if not clean_text:
            return "No text found in track.", "unknown"

        detected_lang = "n/a"
        if LANGDETECT_AVAILABLE:
            try:
                detected_lang = detect(clean_text)
            except Exception as e:
                detected_lang = f"detection_failed ({e})"

        snippet = "\n".join(text_lines[:10])
        
        return snippet, detected_lang

    except Exception as e:
        logging.error(f"Error getting subtitle details for track {track_id}: {e}")
        return f"Error extracting subtitle preview: {e}", "error"
    finally:
        if temp_srt_path.exists():
            temp_srt_path.unlink()

def verify_subtitle_language_is_english(mkv_file: Path, track_id: int) -> bool:
    """Uses the new details function to perform a simple boolean check."""
    if not LANGDETECT_AVAILABLE:
        return True # Skip check if library is not installed

    _snippet, detected_lang = get_subtitle_details(mkv_file, track_id)
    return detected_lang == 'en'