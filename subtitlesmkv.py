# subtitlesmkv.py
# This module scans media files to extract subtitle track information using ffprobe.

import subprocess
import json
from pathlib import Path
from typing import List

# Import the data models from our models.py file
from models import MediaFile, SubtitleTrack

# Centralized function for default scan directories
def get_default_scan_directories() -> List[Path]:
    return [Path("E:/Movies"), Path("E:/TVShows")]

def scan_directory(directory_path: Path) -> List[MediaFile]:
    """
    Scans a directory recursively for .mkv files and processes each one.

    Args:
        directory_path: The root directory to start scanning from.

    Returns:
        A list of MediaFile objects, each populated with subtitle data.
    """
    print(f"Scanning directory: {directory_path}...")
    media_files = []
    # Use rglob to find all .mkv files in the directory and its subdirectories
    for file_path in directory_path.rglob("*.mkv"):
        print(f"  Found file: {file_path.name}")
        media_file = scan_file(file_path)
        media_files.append(media_file)
    print(f"Scan complete. Found {len(media_files)} MKV files.")
    return media_files

def scan_file(file_path: Path) -> MediaFile:
    """
    Scans a single media file for subtitle tracks using ffprobe.

    This function executes ffprobe, parses its JSON output, and populates
    a MediaFile object with a list of SubtitleTrack objects. It also
    implements the business logic for auto-selecting forced subtitles.

    Args:
        file_path: The full path to the .mkv file.

    Returns:
        A populated MediaFile object.
    """
    media = MediaFile(source_path=file_path)
    media.status = "Scanning"
    
    try:
        # This ffprobe command is tailored to extract all subtitle streams (-select_streams s)
        # and their relevant metadata in a structured JSON format (-of json).
        cmd = [
            "ffprobe",
            "-v", "error",                   # Only show errors
            "-select_streams", "s",         # Select only subtitle streams
            "-show_entries", (              # Get specific data points
                "stream=index,codec_name:"
                "stream_tags=language,title:"
                "disposition=default,forced"
            ),
            "-of", "json",                    # Output as JSON
            str(file_path)                    # The file to scan
        ]
        
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            check=True,  # Raises CalledProcessError on non-zero exit codes
            encoding='utf-8'
        )
        
        data = json.loads(result.stdout)
        
        # The 'i' from enumerate corresponds to the ffmpeg-specific subtitle index (s:0, s:1, ...)
        for i, stream in enumerate(data.get("streams", [])):
            tags = stream.get("tags", {})
            disposition = stream.get("disposition", {})
            
            track = SubtitleTrack(
                index=stream.get("index"), # The absolute stream index in the container
                ffmpeg_index=i,            # The relative subtitle stream index for ffmpeg
                language=tags.get("language", "und"),
                title=tags.get("title"),
                codec=stream.get("codec_name"),
                is_default=bool(disposition.get("default", 0)),
                is_forced=bool(disposition.get("forced", 0))
            )
            media.subtitle_tracks.append(track)

        # After parsing all tracks, update the file's flags
        media.update_flags()

        # --- Auto-selection logic ---
        # Automatically select the first found English "forced" subtitle for burn-in.
        # This is a common requirement for movies with foreign language parts.
        for track in media.subtitle_tracks:
            if track.language == "eng" and track.is_forced:
                track.action = "burn"
                media.burned_subtitle = track
                print(f"    -> Auto-selected forced subtitle for '{media.filename}'")
                break # Stop after finding the first one

        media.status = "Ready" if not media.error_message else "Error"

    except FileNotFoundError:
        media.status = "Error"
        media.error_message = "ffprobe command not found. Is FFmpeg installed and in your system's PATH?"
    except subprocess.CalledProcessError as e:
        media.status = "Error"
        # Provide a clean error message from ffprobe's stderr
        media.error_message = f"ffprobe failed with exit code {e.returncode}. Stderr: {e.stderr.strip()}"
    except json.JSONDecodeError:
        media.status = "Error"
        media.error_message = "Failed to parse ffprobe's JSON output."
    except Exception as e:
        media.status = "Error"
        media.error_message = f"An unexpected error occurred: {e}"

    return media

# Example Usage:
if __name__ == "__main__":
    # To test this module, point this to a directory containing .mkv files.
    # IMPORTANT: You must have FFmpeg (and ffprobe) installed and accessible
    # in your system's PATH for this to work.
    
    test_dirs = get_default_scan_directories()
    try:
        print("--- Running subtitle scanner module in test mode ---")

        media_files_list = []
        for test_dir in test_dirs:
            if test_dir.exists():
                print(f"\nScanning directory: {test_dir}")
                media_files_list.extend(scan_directory(test_dir))
            else:
                print(f"\n⚠️ Directory does not exist: {test_dir}")

        print("\n2. Results of scan:")
        if not media_files_list:
            print("  No .mkv files were found or processed.")
        else:
            for mf in media_files_list:
                print(f"\n  File: {mf.filename}")
                print(f"    Status: {mf.status}")
                if mf.error_message:
                    print(f"    Error: {mf.error_message}")

                if mf.subtitle_tracks:
                    print("    Subtitles Found:")
                    for sub in mf.subtitle_tracks:
                        print(f"      - {sub.get_display_name()} | Action: {sub.action}")
                else:
                    print("    No subtitle tracks found or an error occurred.")

    except Exception as e:
        print(f"\nAn error occurred during the test run: {e}")
    finally:
        print("\n--- Test mode finished ---")
