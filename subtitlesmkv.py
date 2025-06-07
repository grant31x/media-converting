# subtitlesmkv.py
# This module scans media files to extract subtitle track information using ffprobe.

import subprocess
import json
from pathlib import Path
from typing import List

# Import the data models from our models.py file
from models import MediaFile, SubtitleTrack

def scan_media_folders(dir_paths: List[Path]) -> List[MediaFile]:
    """
    Scans a list of directories recursively for .mkv files and processes each one.

    Args:
        dir_paths: A list of Path objects for the root directories to scan.

    Returns:
        A list of MediaFile objects, each populated with subtitle data.
    """
    all_media_files = []
    print("--- Starting Media Scan ---")
    for dir_path in dir_paths:
        print(f"Scanning directory: {dir_path}...")
        if not dir_path.is_dir():
            print(f"  -> Warning: Path is not a directory, skipping: {dir_path}")
            continue
        for file_path in dir_path.rglob("*.mkv"):
            print(f"  Found file: {file_path.name}")
            media_file = scan_file(file_path)
            all_media_files.append(media_file)
    print(f"--- Scan Complete. Found {len(all_media_files)} total MKV files. ---")
    return all_media_files


def scan_file(file_path: Path) -> MediaFile:
    """
    Scans a single media file for subtitle tracks using ffprobe.
    """
    media = MediaFile(source_path=file_path)
    media.status = "Scanning"
    
    try:
        cmd = [
            "ffprobe", "-v", "error", "-select_streams", "s",
            "-show_entries", "stream=index,codec_name:stream_tags=language,title:disposition=default,forced",
            "-of", "json", str(file_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, encoding='utf-8')
        
        # DEBUGGING: Print the raw ffprobe output to the console.
        print(f"    ffprobe output for '{file_path.name}':\n    {result.stdout.strip()}")

        data = json.loads(result.stdout)
        
        if not data.get("streams"):
            print(f"    -> No subtitle streams found by ffprobe.")

        for i, stream in enumerate(data.get("streams", [])):
            tags = stream.get("tags", {})
            disposition = stream.get("disposition", {})
            track = SubtitleTrack(
                index=stream.get("index"),
                ffmpeg_index=i,
                language=tags.get("language", "und"),
                title=tags.get("title"),
                codec=stream.get("codec_name"),
                is_default=bool(disposition.get("default", 0)),
                is_forced=bool(disposition.get("forced", 0))
            )
            media.subtitle_tracks.append(track)

        media.update_flags()

        for track in media.subtitle_tracks:
            if track.language == "eng" and track.is_forced:
                track.action = "burn"
                media.burned_subtitle = track
                break
        media.status = "Ready"

    except FileNotFoundError:
        media.status = "Error"
        media.error_message = "ffprobe command not found. Is FFmpeg in your PATH?"
    except subprocess.CalledProcessError as e:
        media.status = "Error"
        media.error_message = f"ffprobe failed. Stderr: {e.stderr.strip()}"
    except Exception as e:
        media.status = "Error"
        media.error_message = f"An unexpected error occurred: {e}"

    return media
