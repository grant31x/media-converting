# subtitlesmkv.py
# This module scans media files to extract subtitle track information using mkvmerge.

import subprocess
import json
from pathlib import Path
from typing import List

# Import the data models from our models.py file
from models import MediaFile, SubtitleTrack

# --- Configuration for MKVToolNix ---
# Define the path to mkvmerge.exe. Update this if your installation is different.
MKVMERGE_PATH = Path("C:/Program Files/MKVToolNix/mkvmerge.exe")


def scan_directory(directory_path: Path) -> List[MediaFile]:
    """
    Scans a single directory recursively for .mkv files and processes each one.

    Args:
        directory_path: A Path object for the root directory to scan.

    Returns:
        A list of MediaFile objects found in that directory.
    """
    media_files = []
    print(f"--- Scanning directory with mkvmerge: {directory_path} ---")
    if not MKVMERGE_PATH.exists():
        print(f"[ERROR] mkvmerge.exe not found at the specified path: {MKVMERGE_PATH}")
        print("[ERROR] Please update the MKVMERGE_PATH in subtitlesmkv.py or install MKVToolNix.")
        return media_files

    if not directory_path.is_dir():
        print(f"  -> Warning: Path is not a directory, skipping: {directory_path}")
        return media_files

    for file_path in directory_path.rglob("*.mkv"):
        print(f"  Found file: {file_path.name}")
        media_file = scan_file(file_path)
        media_files.append(media_file)
        
    print(f"--- Scan of {directory_path} complete. Found {len(media_files)} files. ---")
    return media_files


def scan_file(file_path: Path) -> MediaFile:
    """
    Scans a single MKV file for subtitle tracks using mkvmerge.
    """
    media = MediaFile(source_path=file_path)
    media.status = "Scanning"
    
    try:
        # Command to get JSON identification from mkvmerge
        cmd = [
            str(MKVMERGE_PATH),
            "-J", # Output in JSON format
            str(file_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, encoding='utf-8')
        
        # DEBUGGING: Print the raw mkvmerge output to the console.
        print(f"    mkvmerge output for '{file_path.name}':\n    {result.stdout.strip()}")

        data = json.loads(result.stdout)
        
        subtitle_ffmpeg_index = 0
        for track in data.get("tracks", []):
            if track.get("type") == "subtitles":
                properties = track.get("properties", {})
                
                new_track = SubtitleTrack(
                    index=track.get("id"), # This is the mkvmerge track ID
                    ffmpeg_index=subtitle_ffmpeg_index,
                    language=properties.get("language", "und"),
                    title=properties.get("track_name"),
                    codec=track.get("codec"),
                    is_default=properties.get("default_track", False),
                    is_forced=properties.get("forced_track", False)
                )
                media.subtitle_tracks.append(new_track)
                subtitle_ffmpeg_index += 1 # Increment only for subtitle tracks

        if not media.subtitle_tracks:
            print(f"    -> No subtitle streams found by mkvmerge.")

        media.update_flags()

        # Auto-select forced English subtitle
        for track in media.subtitle_tracks:
            if track.language == "eng" and track.is_forced:
                track.action = "burn"
                media.burned_subtitle = track
                print(f"    -> Auto-selected forced subtitle: {track.get_display_name()}")
                break
        media.status = "Ready"

    except FileNotFoundError:
        media.status = "Error"
        media.error_message = f"mkvmerge.exe not found at path: {MKVMERGE_PATH}. Please check the path in subtitlesmkv.py."
    except subprocess.CalledProcessError as e:
        media.status = "Error"
        media.error_message = f"mkvmerge failed. Stderr: {e.stderr.strip()}"
    except Exception as e:
        media.status = "Error"
        media.error_message = f"An unexpected error occurred during scan: {e}"

    return media
