# subtitlesmkv.py
# This module scans media files to extract subtitle track information using ffprobe.

import subprocess
import json
from pathlib import Path
from typing import List, Callable

# Import the data models from our models.py file
from models import MediaFile, SubtitleTrack

def scan_directory(directory_path: Path, stop_flag: bool = False) -> List[MediaFile]:
    """
    Scans a directory recursively for .mkv files and processes each one.

    Args:
        directory_path: The root directory to start scanning from.
        stop_flag: A boolean flag to gracefully stop the scan. If it becomes True, the loop will exit.
    """
    print(f"Scanning directory: {directory_path}...")
    media_files = []
    
    # Use rglob to find all .mkv files in the directory and its subdirectories
    for file_path in directory_path.rglob("*.mkv"):
        # The cancellation flag is checked here before processing each file.
        if stop_flag:
            print(f"  -> Scan of '{directory_path}' cancelled by user.")
            break
        
        print(f"  Found file: {file_path.name}")
        media_file = scan_file(file_path)
        media_files.append(media_file)
        
    if not stop_flag:
        print(f"Scan complete for '{directory_path}'. Found {len(media_files)} MKV files.")
    return media_files

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
        data = json.loads(result.stdout)
        
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
