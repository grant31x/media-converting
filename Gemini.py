import re
import subprocess
import logging
from pathlib import Path
from tqdm import tqdm
import os
import json
import shutil
from typing import Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# --- Configuration (Centralized) ---
class AppConfig:
    """
    Configuration settings for the media conversion script.
    """
    DRY_RUN: bool = True # Set to False for actual conversion, True for simulation
    MAX_WORKERS: int = 3
    LOGGING_ENABLED: bool = True # Master toggle for all logging (true/false)
    # DEBUG_LOGGING_ENABLED removed to simplify logging behavior

    # Paths to FFmpeg and FFprobe executables
    FFMPEG_PATH: Path = Path(r"C:\Programs2\ffmpeg\ffmpeg_essentials_build\bin\ffmpeg.exe")
    FFPROBE_PATH: Path = Path(r"C:\Programs2\ffmpeg\ffmpeg_essentials_build\bin\ffprobe.exe")
    # Path to mkvmerge executable (part of MKVToolNix)
    MKVMERGE_PATH: Path = Path(r"C:\Program Files\MKVToolNix\mkvmerge.exe") 

    # Paths for logging
    LOG_FILE_JSON: Path = Path("D:/Python/Logs/conversion_log.json") # For JSON log of conversion status
    LOG_FILE_ACTIVITY: Path = Path("D:/Python/Logs/conversion_activity.log") # For general activity log

    # Source and Destination directories for media
    SOURCE_MOVIES: Path = Path("E:/Movies")
    SOURCE_TV: Path = Path("E:/TVShows")
    DEST_MOVIES: Path = Path("Z:/Movies")
    DEST_TV: Path = Path("Z:/TV Shows")

    # Filename cleanup terms
    CLEANUP_TERMS: list[str] = [
        "1080p", "720p", "BluRay", "x264", "YTS", "BRRip", "WEBRip", "WEB-DL",
        "HDRip", "DVDRip", "AAC", "5.1", "H264", "H265", "HEVC", 
        "DTS", "TrueHD", "Atmos", "REMUX", "AMZN", "NF", "UHD", "x265", "FHD"
    ]

# --- Global Data and Locks ---
conversion_log: dict[str, str] = {}
conversion_log_lock: threading.Lock = threading.Lock() # Lock for thread-safe writing to JSON log

# --- Logging Setup ---
def setup_logging():
    """
    Configures the logging system based on AppConfig.LOGGING_ENABLED.
    Logs messages to both a file and the console.
    """
    # Get the root logger
    root_logger = logging.getLogger()
    
    # Remove any existing handlers from the root logger to prevent duplicates or interference
    for handler in root_logger.handlers[:]: # Iterate over a slice to modify in place
        root_logger.removeHandler(handler)

    if AppConfig.LOGGING_ENABLED:
        # Ensure log directory exists
        AppConfig.LOG_FILE_ACTIVITY.parent.mkdir(parents=True, exist_ok=True)
  
        # Set logging level to INFO (DEBUG messages will be suppressed)
        log_level = logging.INFO

        # Set the root logger's level
        root_logger.setLevel(log_level)

        # Create and add file handler
        file_handler = logging.FileHandler(AppConfig.LOG_FILE_ACTIVITY, encoding='utf-8')
        file_handler.setLevel(log_level) # Explicitly set level for file handler
        file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        root_logger.addHandler(file_handler)

        # Create and add console handler
        console_handler = logging.StreamHandler(os.sys.stdout)
        console_handler.setLevel(log_level) # Explicitly set level for console handler
        console_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        root_logger.addHandler(console_handler)

    else:
        # If logging is disabled, disable all log levels on the root logger
        root_logger.setLevel(logging.CRITICAL + 1) # Set to a level higher than CRITICAL
        logging.disable(logging.CRITICAL) # Also use the global disable function for good measure

def _format_log_message(message: str) -> str:
    """
    Formats log messages by keeping emojis (as DEBUG_LOGGING_ENABLED is removed).
    This function now acts as a pass-through for INFO messages, ensuring emojis are kept.
    """
    return message # Always return original message with emojis for INFO level.

def save_log():
    """
    Saves the current state of the conversion log to a JSON file.
    Uses a threading lock to ensure thread safety during file write operations.
    """
    if not AppConfig.LOGGING_ENABLED:
        return
    with conversion_log_lock:
        try:
            # Ensure the directory for the JSON log also exists
            AppConfig.LOG_FILE_JSON.parent.mkdir(parents=True, exist_ok=True)
            with open(AppConfig.LOG_FILE_JSON, "w", encoding="utf-8") as f: # Ensure JSON log is UTF-8
                json.dump(conversion_log, f, indent=4)
        except Exception as e:
            logging.error(_format_log_message(f"❌ Failed to write conversion log JSON: {e}"))

# --- Media Probe Helper Function ---
def _run_media_probe(file_path: Path, stream_type: str) -> dict:
    """
    Helper function to run ffprobe (for video/audio) or mkvmerge (for subtitles)
    and return parsed JSON output.
    """
    if stream_type == "s": # Use mkvmerge for subtitle probing (more reliable metadata for MKV)
        try:
            command = [
                str(AppConfig.MKVMERGE_PATH), "-J", str(file_path)
            ]
            result = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8')
            return json.loads(result.stdout)
        except FileNotFoundError:
            logging.error(_format_log_message(f"❌ mkvmerge not found at {AppConfig.MKVMERGE_PATH}. Please check your path."))
            return {"tracks": []} # mkvmerge returns 'tracks' not 'streams'
        except subprocess.CalledProcessError as e:
            logging.warning(_format_log_message(f"⚠️ mkvmerge command failed for {file_path.name}: {e.stderr.strip()}"))
            return {"tracks": []}
        except (json.JSONDecodeError, IndexError) as e:
            logging.warning(_format_log_message(f"⚠️ Failed to parse mkvmerge output for {file_path.name}: {e}"))
            return {"tracks": []}
        except Exception as e:
            logging.warning(_format_log_message(f"⚠️ An unexpected error occurred with mkvmerge for {file_path.name}: {e}"))
            return {"tracks": []}
    else: # Use ffprobe for video/audio probing
        try:
            # For video/audio, we still need codec_name
            probe_entries = "stream=codec_name"
            command = [
                str(AppConfig.FFPROBE_PATH), "-v", "error", "-select_streams", stream_type,
                "-show_entries", probe_entries, "-of", "json", str(file_path)
            ]
            result = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8')
            return json.loads(result.stdout)
        except FileNotFoundError:
            logging.error(_format_log_message(f"❌ FFprobe not found at {AppConfig.FFPROBE_PATH}. Please check your path."))
            return {"streams": []}
        except subprocess.CalledProcessError as e:
            logging.warning(_format_log_message(f"⚠️ FFprobe command failed for {file_path.name} ({stream_type}): {e.stderr.strip()}"))
            return {"streams": []}
        except (json.JSONDecodeError, IndexError) as e:
            logging.warning(_format_log_message(f"⚠️ Failed to parse FFprobe output for {file_path.name} ({stream_type}): {e}"))
            return {"streams": []}
        except Exception as e:
            logging.warning(_format_log_message(f"⚠️ An unexpected error occurred with FFprobe for {file_path.name}: {e}"))
            return {"streams": []}

def get_audio_codec(file_path: Path) -> str:
    """
    Retrieves the audio codec name of the first audio stream in a given media file using ffprobe.

    Args:
        file_path: The Path object of the media file.

    Returns:
        The name of the audio codec (e.g., "aac", "ac3"), or "unknown" if an error occurs.
    """
    data = _run_media_probe(file_path, "a:0")
    streams = data.get("streams", [])
    return streams[0]["codec_name"] if streams else "unknown"

def get_video_codec(file_path: Path) -> str:
    """
    Retrieves the video codec name of the first video stream in a given media file using ffprobe.

    Args:
        file_path: The Path object of the media file.

    Returns:
        The name of the video codec (e.g., "h264", "hevc"), or "unknown" if an error occurs.
    """
    data = _run_media_probe(file_path, "v:0")
    streams = data.get("streams", [])
    return streams[0]["codec_name"] if streams else "unknown"

def get_subtitle_indices(file_path: Path) -> Tuple[int, int]:
    """
    Determines the indices for forced subtitles (to be burned-in) and
    English soft subtitles (for optional display) using mkvmerge metadata.

    Prioritizes explicitly tagged forced subtitles. Finds the first non-forced English subtitle.
    PGS (image-based) subtitles are skipped for both.

    Args:
        file_path: The Path object of the media file.

    Returns:
        A tuple containing:
            - forced_burn_in_idx (int): Index of the first forced subtitle found (any language), or -1 if none.
            - soft_english_cc_idx (int): Index of the first non-forced English subtitle found, or -1 if none.
    """
    forced_burn_in_idx = -1
    soft_english_cc_idx = -1
    all_english_streams_ids = [] # To keep track of all English streams for soft sub selection

    # Get track information using mkvmerge
    mkvmerge_data = _run_media_probe(file_path, "s") # 's' indicates subtitle track request
    all_tracks = mkvmerge_data.get("tracks", [])

    # First pass: Identify the forced subtitle for burn-in (highest priority: explicit 'forced' flag)
    # mkvmerge outputs `id` as the track ID and `properties.forced_track` as a boolean
    for track in all_tracks:
        if track.get("type") != "subtitles":
            continue

        codec = track.get("properties", {}).get("codec_id", "").lower()
        if codec in ["s_vobsub", "s_image", "s_hdpg", "s_hdmv/pgs"]: # Common PGS/image-based codecs
            continue

        if track.get("properties", {}).get("forced_track") is True:
            forced_burn_in_idx = track["id"]
            break # Found the primary forced track, no need to check further

    # Second pass: Collect all English subtitle tracks and identify the soft English one
    for track in all_tracks:
        if track.get("type") != "subtitles":
            continue

        codec = track.get("properties", {}).get("codec_id", "").lower()
        if codec in ["s_vobsub", "s_image", "s_hdpg", "s_hdmv/pgs"]:
            continue

        lang = track.get("properties", {}).get("language", "").lower()
        
        if lang == "eng":
            all_english_streams_ids.append(track["id"])

    # Heuristic for forced burn-in if no explicit forced flag was found but there are English tracks
    # This aligns with the user's scenario: first English track is the forced one.
    if forced_burn_in_idx == -1 and len(all_english_streams_ids) > 0:
        forced_burn_in_idx = all_english_streams_ids[0]

    # Find soft English subtitle: the first English track that is NOT the forced one
    for eng_id in all_english_streams_ids:
        if eng_id != forced_burn_in_idx:
            soft_english_cc_idx = eng_id
            break

    # Final check: If only one relevant English track was found and used as forced, then no separate soft track
    if soft_english_cc_idx == forced_burn_in_idx:
        soft_english_cc_idx = -1 

    return forced_burn_in_idx, soft_english_cc_idx

# --- File Operations ---
def clean_filename(file_path: Path) -> Path:
    """
    Cleans a filename by removing common release tags (e.g., "1080p", "x264").
    Uses regular expressions for precise, case-insensitive, whole-word replacement.

    Args:
        file_path: The original Path object of the file.

    Returns:
        The new Path object after renaming, or the original Path if no rename occurred or on error.
    """
    original_stem = file_path.stem
    cleaned_stem = original_stem
    for term in AppConfig.CLEANUP_TERMS:
        # Use regex to replace whole words, ignoring case
        cleaned_stem = re.sub(r'\b' + re.escape(term) + r'\b', '', cleaned_stem, flags=re.IGNORECASE)

    # Replace multiple spaces/periods with single space, strip, and replace spaces with underscores
    cleaned_stem = re.sub(r'[.\s]+', ' ', cleaned_stem).strip().replace(' ', '_')

    # Remove any leading/trailing underscores that might result from cleaning
    cleaned_stem = cleaned_stem.strip('_')

    # If the cleaning resulted in an empty string, revert to original_stem to prevent issues
    if not cleaned_stem:
        cleaned_stem = original_stem

    new_path = file_path.with_stem(cleaned_stem)

    if new_path != file_path:
        try:
            file_path.rename(new_path)
            logging.info(_format_log_message(f"✨ Renamed {file_path.name} to {new_path.name}"))
            return new_path # Return the new path if renamed
        except OSError as e: # Catch OSError for file system operations
            logging.warning(_format_log_message(f"⚠️ Could not rename {file_path.name} to {new_path.name}: {e}"))
    return file_path # Return original path if not renamed or on error

def delete_sidecar_files(original_file_path: Path):
    """
    Deletes common metadata and subtitle sidecar files associated with an original MKV file.
    Also deletes the original MKV file itself after successful conversion.
    This function is optional and respects DRY_RUN.

    Args:
        original_file_path: The Path object of the original MKV file (before conversion).
    """
    if AppConfig.DRY_RUN:
        logging.info(_format_log_message(f"🧪 DRY-RUN CLEANUP: Skipping deletion of sidecar files for {original_file_path.name}"))
        return

    # Files to consider for deletion (based on original MKV name)
    files_to_delete = [
        original_file_path,  # The original MKV file itself
        original_file_path.with_suffix('.nfo'),
        original_file_path.with_suffix('.srt'),
        # Add other common sidecar extensions here if needed, e.g., .idx, .sub, .ass
    ]

    logging.info(_format_log_message(f"🗑️ Attempting to clean sidecar files for {original_file_path.name}..."))
    for f_path in files_to_delete:
        if f_path.exists():
            try:
                f_path.unlink()
                logging.info(_format_log_message(f"🗑️ Deleted sidecar file: {f_path.name}"))
            except OSError as e:
                logging.warning(_format_log_message(f"⚠️ Could not delete sidecar file {f_path.name}: {e}"))
        else:
            logging.info(_format_log_message(f"🗑️ Sidecar file not found: {f_path.name}")) # Changed to INFO for better visibility when not debugging

def move_file(src: Path, dest: Path):
    """
    Moves a file from a source path to a destination path.
    Creates parent directories at the destination if they don't exist.

    Args:
        src: The source Path object of the file to move.
        dest: The destination Path object where the file should be moved.
    """
    if AppConfig.DRY_RUN:
        logging.info(_format_log_message(f"🧪 DRY-RUN MOVE: {src} → {dest}"))
        return
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        logging.info(_format_log_message(f"🚚 Moved: {src.name} to {dest}"))
    except Exception as e:
        logging.error(_format_log_message(f"❌ Failed to move {src.name} to {dest}: {e}"))

# --- Conversion Logic ---
def _build_ffmpeg_command(input_file: Path, video_codec: str, audio_codec: str, forced_burn_in_idx: int, soft_english_cc_idx: int) -> list[str]:
    """
    Constructs the FFmpeg command list for media conversion.

    Args:
        input_file: The Path object of the input media file.
        video_codec: The detected video codec of the input file.
        audio_codec: The detected audio codec of the input file.
        forced_burn_in_idx: The index of the forced subtitle stream to burn in, or -1.
        soft_english_cc_idx: The index of the English soft subtitle stream to include, or -1.

    Returns:
        A list of strings representing the FFmpeg command.
    """
    command = [str(AppConfig.FFMPEG_PATH), "-y", "-i", str(input_file)]

    # VIDEO ENCODING STRATEGY:
    # 1. If forced subtitles are burned, video MUST be re-encoded. Re-encode to H.265 for 4K efficiency.
    # 2. If no forced subtitles, prefer copying existing H.265 or H.264.
    # 3. Otherwise (e.g., non-HEVC/H264 video, no forced subs), re-encode to H.265.

    video_reencode_needed = False
    if forced_burn_in_idx >= 0:
        video_reencode_needed = True
        # logging.debug moved below after conditional message
        
    if video_reencode_needed:
        input_ffmpeg_path = str(input_file).replace("\\", "/").replace(":", "\\:")
        subtitle_filter = f"subtitles='{input_ffmpeg_path}':si={forced_burn_in_idx}:force_style='FontName=Arial'"
        command.extend(["-vf", subtitle_filter, "-c:v", "libx265", "-crf", "28", "-preset", "medium"])
        logging.info(_format_log_message(f"Video for {input_file.name} will be re-encoded to H.265 with burn-in."))
    elif video_codec == "hevc":
        command.extend(["-c:v", "copy"])
        logging.info(_format_log_message(f"Video for {input_file.name} (HEVC) will be copied."))
    elif video_codec == "h264":
        command.extend(["-c:v", "copy"])
        logging.info(_format_log_message(f"Video for {input_file.name} (H.264) will be copied."))
    else:
        # Catch other less common video codecs and re-encode to H.265
        command.extend(["-c:v", "libx265", "-crf", "28", "-preset", "medium"])
        logging.info(_format_log_message(f"Video for {input_file.name} (unknown codec '{video_codec}') will be re-encoded to H.265."))

    # AUDIO ENCODING STRATEGY: Always output AAC (640k)
    if audio_codec == "aac": # If source is already AAC, copy it
        command.extend(["-c:a", "copy"])
        logging.info(_format_log_message(f"Audio for {input_file.name} (AAC) will be copied."))
    else: # Re-encode all other audio formats to high-quality AAC
        command.extend(["-c:a", "aac", "-b:a", "640k"]) # High-quality AAC
        logging.info(_format_log_message(f"Audio for {input_file.name} (codec '{audio_codec}') will be re-encoded to AAC 640k."))

    # Map video and audio streams
    command.extend(["-map", "0:v:0", "-map", "0:a:0"])

    # Add soft English subtitles if found and not already burned-in
    if soft_english_cc_idx >= 0:
        command.extend(["-map", f"0:s:{soft_english_cc_idx}", "-scodec:s", "mov_text"])
        logging.info(_format_log_message(f"Soft English subtitles (index {soft_english_cc_idx}) will be included for {input_file.name}."))

    return command

def convert_to_mp4(input_file: Path) -> bool:
    """
    Converts a given MKV media file to MP4 format.
    Handles codec detection, subtitle burning/soft-coding, and temporary file cleanup.

    Args:
        input_file: The Path object of the MKV file to convert.

    Returns:
        True if the conversion was successful, False otherwise.
    """
    input_file_size_bytes = 0
    try:
        input_file_size_bytes = input_file.stat().st_size
        input_file_size_gb = input_file_size_bytes / (1024**3)
        logging.info(_format_log_message(f"▶️ File: '{input_file.name}' - STARTED (Input Size: {input_file_size_gb:.2f} GB) (Thread {threading.get_ident()})"))
    except FileNotFoundError:
        logging.error(_format_log_message(f"❌ File: '{input_file.name}' not found. Skipping conversion."))
        return False
    except Exception as e:
        logging.warning(_format_log_message(f"⚠️ Could not get size for {input_file.name}: {e}. Proceeding without size info."))
        logging.info(_format_log_message(f"▶️ File: '{input_file.name}' - STARTED (Thread {threading.get_ident()})"))


    output_file = input_file.with_suffix(".mp4")
    if output_file.exists():
        output_file_size_bytes = 0
        try:
            output_file_size_bytes = output_file.stat().st_size
            output_file_size_gb = output_file_size_bytes / (1024**3)
            logging.info(_format_log_message(f"⏭️ File: '{input_file.name}' - Already converted to '{output_file.name}' (Output Size: {output_file_size_gb:.2f} GB)"))
        except Exception as e:
            logging.warning(_format_log_message(f"⚠️ Could not get output file size for {output_file.name}: {e}. Proceeding without size info."))
            logging.info(_format_log_message(f"⏭️ File: '{input_file.name}' - Already converted to '{output_file.name}'"))
        return True

    video_codec = get_video_codec(input_file)
    audio_codec = get_audio_codec(input_file)
    forced_burn_in_idx, soft_english_cc_idx = get_subtitle_indices(input_file)

    # Subtitle status message
    sub_status_parts = []
    if forced_burn_in_idx >= 0:
        sub_status_parts.append(f"🔥 Burned-in Forced (Index: {forced_burn_in_idx})")
    else:
        sub_status_parts.append("🚫 No Forced Burn-in")

    if soft_english_cc_idx >= 0:
        sub_status_parts.append(f"💬 Soft English (Index: {soft_english_cc_idx})")
    else:
        sub_status_parts.append("❌ No Soft English")
    
    logging.info(_format_log_message(f"📝 File: '{input_file.name}' - Subtitles: {' + '.join(sub_status_parts)}"))

    if AppConfig.DRY_RUN:
        logging.info(_format_log_message(f"🧪 File: '{input_file.name}' - DRY-RUN ONLY. No actual conversion will occur."))
        return True

    temp_file = input_file.with_suffix(".temp.mp4")
    command = _build_ffmpeg_command(input_file, video_codec, audio_codec, forced_burn_in_idx, soft_english_cc_idx)
    command.append(str(temp_file)) # Add output file to the command

    # Converting message
    logging.info(_format_log_message(f"🔄 File: '{input_file.name}' - CONVERTING..."))

    try:
        # Execute FFmpeg command, capturing output for detailed error logging
        result = subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8')
        shutil.move(str(temp_file), str(output_file))
        # Call sidecar cleanup after conversion and move, as original_file_path is needed
        delete_sidecar_files(input_file) 

        # Get and display output file size after successful conversion
        output_file_size_bytes = 0
        try:
            output_file_size_bytes = output_file.stat().st_size
            output_file_size_gb = output_file_size_bytes / (1024**3)
            logging.info(_format_log_message(f"✅ File: '{input_file.name}' - DONE. Converted to: '{output_file.name}' (Output Size: {output_file_size_gb:.2f} GB)"))
        except Exception as e:
            logging.warning(_format_log_message(f"⚠️ Could not get final output file size for {output_file.name}: {e}. Proceeding without size info."))
            logging.info(_format_log_message(f"✅ File: '{input_file.name}' - DONE. Converted to: '{output_file.name}'"))

        return True
    except FileNotFoundError:
        logging.error(_format_log_message(f"❌ File: '{input_file.name}' - FAILED. FFmpeg not found at {AppConfig.FFMPEG_PATH}. Please check your path."))
        return False
    except subprocess.CalledProcessError as e:
        logging.error(_format_log_message(f"❌ File: '{input_file.name}' - FAILED. FFmpeg conversion error. "
                      f"Return Code: {e.returncode}\nSTDOUT: {e.stdout.strip()}\nSTDERR: {e.stderr.strip()}"))
        return False
    except Exception as e:
        logging.error(_format_log_message(f"❌ File: '{input_file.name}' - FAILED. An unexpected error occurred: {e}"))
        return False
    finally:
        # Ensure temporary file is always cleaned up
        if temp_file.exists():
            try:
                temp_file.unlink()
                logging.info(_format_log_message(f"🗑️ Cleaned up temporary file: {temp_file.name}")) # Changed to INFO
            except OSError as e:
                logging.warning(_format_log_message(f"⚠️ Could not delete temporary file {temp_file.name}: {e}"))

# --- Main Workflow Functions ---
def flatten_and_clean_movies():
    """
    Moves all converted MP4 movies from source to a flat destination directory.
    Also removes empty directories in the source movie path after files are moved.
    """
    logging.info(_format_log_message(f"\n--- 🎞️ Flattening Movies ---"))
    mp4_files = list(AppConfig.SOURCE_MOVIES.rglob("*.mp4")) # Get all files first to count for tqdm
    for mp4_file in tqdm(mp4_files, desc=_format_log_message("🚚 Moving Movies"), dynamic_ncols=True):
        dest_file = AppConfig.DEST_MOVIES / mp4_file.name
        move_file(mp4_file, dest_file)

    # Clean up empty directories in source
    logging.info(_format_log_message("🧹 Cleaning up empty movie directories..."))
    for dirpath, dirnames, filenames in os.walk(AppConfig.SOURCE_MOVIES, topdown=False):
        if not dirnames and not filenames: # If directory has no subdirectories and no files
            try:
                if not AppConfig.DRY_RUN:
                    os.rmdir(dirpath)
                logging.info(_format_log_message(f"🧹 Removed empty folder: {dirpath}"))
            except OSError as e:
                logging.warning(_format_log_message(f"⚠️ Could not remove empty folder {dirpath}: {e}"))

def preserve_structure_tv():
    """
    Moves all converted MP4 TV shows from source to destination, preserving
    the original directory structure.
    """
    logging.info(_format_log_message(f"\n--- 📺 Preserving TV Show Structure ---"))
    mp4_files = list(AppConfig.SOURCE_TV.rglob("*.mp4")) # Get all files first to count for tqdm
    for mp4_file in tqdm(mp4_files, desc=_format_log_message("🚚 Moving TV Shows"), dynamic_ncols=True):
        rel_path = mp4_file.relative_to(AppConfig.SOURCE_TV)
        dest_path = AppConfig.DEST_TV / rel_path
        move_file(mp4_file, dest_path)

def convert_all():
    """
    Finds all MKV files in source directories, pre-cleans their filenames,
    and then converts them to MP4 using a ThreadPoolExecutor for concurrent processing.
    """
    all_files_mkv = list(AppConfig.SOURCE_MOVIES.rglob("*.mkv")) + \
                    list(AppConfig.SOURCE_TV.rglob("*.mkv"))
    logging.info(_format_log_message(f"🔍 Found {len(all_files_mkv)} MKV files to process."))

    # Step 1: Pre-clean filenames for all found MKV files
    logging.info(_format_log_message("✨ Cleaning filenames before conversion..."))
    cleaned_files_for_conversion = []
    for file_path in tqdm(all_files_mkv, desc=_format_log_message("✨ Cleaning Filenames"), dynamic_ncols=True):
        cleaned_files_for_conversion.append(clean_filename(file_path))

    # Step 2: Perform concurrent conversion
    results = []
    with ThreadPoolExecutor(max_workers=AppConfig.MAX_WORKERS) as executor:
        futures = {executor.submit(convert_to_mp4, f): f for f in cleaned_files_for_conversion}
        for future in tqdm(as_completed(futures), total=len(futures), desc=_format_log_message("🔄 Converting"), dynamic_ncols=True):
            file_being_processed = futures[future] # Original path (potentially cleaned) for logging
            success = future.result()
            if AppConfig.LOGGING_ENABLED:
                conversion_log[str(file_being_processed)] = "converted" if success else "error"
            results.append(success)
            save_log() # Save log after each conversion attempt
    logging.info(_format_log_message(f"📊 Conversion Summary: Converted: {results.count(True)} | ❌ Failed: {results.count(False)}"))

def main():
    """
    Main function to orchestrate the media conversion process.
    Initializes logging, performs conversions, and then organizes the converted files.
    """
    setup_logging()
    logging.info(_format_log_message("▶️ Starting media conversion process..."))
    convert_all()
    flatten_and_clean_movies()
    preserve_structure_tv()
    logging.info(_format_log_message("🎉 Media conversion process completed."))

if __name__ == "__main__":
    main()
