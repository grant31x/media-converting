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
    DRY_RUN: bool = True
    MAX_WORKERS: int = 3
    LOGGING_ENABLED: bool = True # Set to True to enable logging to file and console

    # Paths to FFmpeg and FFprobe executables
    FFMPEG_PATH: Path = Path(r"C:\Programs2\ffmpeg\ffmpeg_essentials_build\bin\ffmpeg.exe")
    FFPROBE_PATH: Path = Path(r"C:\Programs2\ffmpeg\ffmpeg_essentials_build\bin\ffprobe.exe")

    # Paths for logging
    LOG_FILE_JSON: Path = Path("D:/Python/Logs/conversion_log.json") # For JSON log of conversion status
    LOG_FILE_ACTIVITY: Path = Path("D:/Python/Logs/conversion_activity.log") # For general activity log

    # Source and Destination directories for media
    SOURCE_MOVIES: Path = Path("E:/Movies")
    SOURCE_TV: Path = Path("E:/TV Shows") # Reverted to original path as requested
    DEST_MOVIES: Path = Path("Z:/Movies")
    DEST_TV: Path = Path("Z:/TV Shows")

    # Terms to clean from filenames (case-insensitive, whole words)
    CLEANUP_TERMS: list[str] = [
        "1080p", "720p", "BluRay", "x264", "YTS", "BRRip", "WEBRip", "WEB-DL",
        "HDRip", "DVDRip", "AAC", "5.1", "H264", "H265", "HEVC"
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
    if AppConfig.LOGGING_ENABLED:
        # Ensure log directory exists
        AppConfig.LOG_FILE_ACTIVITY.parent.mkdir(parents=True, exist_ok=True)
  
        # IMPORTANT: Specify encoding='utf-8' for both handlers to support emojis and wide characters.
        logging.basicConfig(
            level=logging.DEBUG, # Changed to DEBUG to show detailed logs for debugging
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(AppConfig.LOG_FILE_ACTIVITY, encoding='utf-8'), # Log to a file with UTF-8
                logging.StreamHandler(os.sys.stdout) # Also log to console (using sys.stdout explicitly)
            ]
        )
        # Ensure the console stream is also set to UTF-8
        # This typically needs to be done directly on the stream if default is not UTF-8
        # However, passing it to StreamHandler usually handles it. If issues persist,
        # set PYTHONIOENCODING=utf-8 in your environment variables.
    else:
        # Disable all logging if not enabled in configuration
        logging.disable(logging.CRITICAL)

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
            logging.error(f"❌ Failed to write conversion log JSON: {e}")

# --- FFprobe Helper Functions ---
def _run_ffprobe(file_path: Path, stream_type: str) -> dict:
    """
    Helper function to run ffprobe and return parsed JSON output for a specified stream type.

    Args:
        file_path: The Path object of the media file.
        stream_type: The stream type to select (e.g., "a:0", "v:0", "s").

    Returns:
        A dictionary containing FFprobe's JSON output for the streams,
        or an empty dictionary if an error occurs.
    """
    try:
        # IMPORTANT: Added 'disposition' to probe_entries for subtitle streams.
        # disposition contains flags like 'forced', 'default', etc.
        probe_entries = "stream=index,codec_name,tags=language,title,forced,disposition" if stream_type == "s" else "stream=codec_name"
        command = [
            str(AppConfig.FFPROBE_PATH), "-v", "error", "-select_streams", stream_type,
            "-show_entries", probe_entries, "-of", "json", str(file_path)
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8')
        return json.loads(result.stdout)
    except FileNotFoundError:
        logging.error(f"❌ FFprobe not found at {AppConfig.FFPROBE_PATH}. Please check your path.")
        return {"streams": []}
    except subprocess.CalledProcessError as e:
        logging.warning(f"⚠️ FFprobe command failed for {file_path.name} ({stream_type}): {e.stderr.strip()}")
        return {"streams": []}
    except (json.JSONDecodeError, IndexError) as e:
        logging.warning(f"⚠️ Failed to parse FFprobe output for {file_path.name} ({stream_type}): {e}")
        return {"streams": []}
    except Exception as e:
        logging.warning(f"⚠️ An unexpected error occurred with FFprobe for {file_path.name}: {e}")
        return {"streams": []}

def get_audio_codec(file_path: Path) -> str:
    """
    Retrieves the audio codec name of the first audio stream in a given media file.

    Args:
        file_path: The Path object of the media file.

    Returns:
        The name of the audio codec (e.g., "aac", "ac3"), or "unknown" if an error occurs.
    """
    data = _run_ffprobe(file_path, "a:0")
    streams = data.get("streams", [])
    return streams[0]["codec_name"] if streams else "unknown"

def get_video_codec(file_path: Path) -> str:
    """
    Retrieves the video codec name of the first video stream in a given media file.

    Args:
        file_path: The Path object of the media file.

    Returns:
        The name of the video codec (e.g., "h264", "hevc"), or "unknown" if an error occurs.
    """
    data = _run_ffprobe(file_path, "v:0")
    streams = data.get("streams", [])
    return streams[0]["codec_name"] if streams else "unknown"

def get_subtitle_indices(file_path: Path) -> Tuple[int, int]:
    """
    Determines the indices for forced subtitles (to be burned-in) and
    English soft subtitles (for optional display).

    Prioritizes any explicitly forced subtitle for burn-in, then any subtitle with "forced" in its title.
    Separately, it finds the first non-forced English subtitle for soft-coding.
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
    english_streams_candidates = [] # To keep track of English streams for soft subtitle heuristic

    data = _run_ffprobe(file_path, "s")
    all_streams = data.get("streams", [])

    logging.debug(f"DEBUG: Subtitle streams for {file_path.name}: {json.dumps(all_streams, indent=2)}")

    # First pass: Prioritize finding any explicitly forced subtitle (highest priority for burn-in)
    for stream in all_streams:
        tags = stream.get("tags", {})
        codec = stream.get("codec_name", "")
        # Check disposition.forced first, as it's the most reliable flag
        is_disposition_forced = stream.get("disposition", {}).get("forced") == 1 
        is_forced_tag = tags.get("forced") == "1" # Fallback to old 'tags.forced' if disposition not present
        title = tags.get("title", "").lower()

        if codec in ["pgs", "hdmv_pgs_subtitle"]:
            logging.debug(f"DEBUG: Skipping PGS subtitle stream {stream.get('index')}")
            continue

        if is_disposition_forced: # Prioritize disposition.forced
            forced_burn_in_idx = stream["index"]
            logging.debug(f"DEBUG: Found disposition-based forced subtitle at index: {forced_burn_in_idx}")
            break 
        elif is_forced_tag: # Fallback to tags.forced
            forced_burn_in_idx = stream["index"]
            logging.debug(f"DEBUG: Found tags-based forced subtitle at index: {forced_burn_in_idx}")
            break

    # Second pass: If no explicit forced subtitle, fallback to "forced" in title
    if forced_burn_in_idx == -1:
        for stream in all_streams:
            tags = stream.get("tags", {})
            codec = stream.get("codec_name", "")
            title = tags.get("title", "").lower()

            if codec in ["pgs", "hdmv_pgs_subtitle"]:
                continue

            if "forced" in title:
                forced_burn_in_idx = stream["index"]
                logging.debug(f"DEBUG: Found title-based forced subtitle at index: {forced_burn_in_idx}")
                break 

    # Collect all English streams for soft subtitle consideration and heuristic forced
    for stream in all_streams:
        tags = stream.get("tags", {})
        codec = stream.get("codec_name", "")
        lang = tags.get("language", "").lower()
        # Also ensure this English stream is not the one we just picked as forced
        is_current_stream_forced_candidate = (stream.get("disposition", {}).get("forced") == 1) or \
                                             (tags.get("forced") == "1") or \
                                             ("forced" in tags.get("title", "").lower())

        if codec in ["pgs", "hdmv_pgs_subtitle"]:
            continue

        # Only consider truly non-forced English streams for the soft subtitle track
        if lang == "eng" and not is_current_stream_forced_candidate:
            english_streams_candidates.append(stream["index"])
            logging.debug(f"DEBUG: Added English stream candidate: {stream['index']}")

    # Heuristic for forced burn-in if no explicit forced tag or title-based forced was found
    # and we have English streams available. This assumes the *first* English stream is the forced one.
    if forced_burn_in_idx == -1 and len(english_streams_candidates) > 0:
        forced_burn_in_idx = english_streams_candidates[0]
        logging.debug(f"DEBUG: Heuristic: Assigning first English stream {forced_burn_in_idx} as forced burn-in (as no explicit forced found).")

    # Find soft English subtitle: first English track that is NOT the forced one
    # This loop ensures we find a *different* English stream for soft-coding
    for eng_idx in english_streams_candidates:
        if eng_idx != forced_burn_in_idx:
            soft_english_cc_idx = eng_idx
            logging.debug(f"DEBUG: Found soft English subtitle at index: {soft_english_cc_idx}")
            break

    # Final check: If only one relevant English track was found and used as forced, then no separate soft track
    if soft_english_cc_idx == forced_burn_in_idx:
        soft_english_cc_idx = -1 
        logging.debug("DEBUG: Forced and soft English indices are the same, clearing soft_english_cc_idx.")

    logging.debug(f"DEBUG: Final subtitle indices for {file_path.name}: Forced Burn-in: {forced_burn_in_idx}, Soft English: {soft_english_cc_idx}")
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
            logging.info(f"✨ Renamed {file_path.name} to {new_path.name}")
            return new_path # Return the new path if renamed
        except OSError as e: # Catch OSError for file system operations
            logging.warning(f"⚠️ Could not rename {file_path.name} to {new_path.name}: {e}")
    return file_path # Return original path if not renamed or on error

def move_file(src: Path, dest: Path):
    """
    Moves a file from a source path to a destination path.
    Creates parent directories at the destination if they don't exist.

    Args:
        src: The source Path object of the file to move.
        dest: The destination Path object where the file should be moved.
    """
    if AppConfig.DRY_RUN:
        logging.info(f"🧪 DRY-RUN MOVE: {src} → {dest}")
        return
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        logging.info(f"🚚 Moved: {src.name} to {dest}")
    except Exception as e:
        logging.error(f"❌ Failed to move {src.name} to {dest}: {e}")

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

    # Video encoding strategy
    if forced_burn_in_idx >= 0:
        # Properly escape path for FFmpeg subtitles filter on Windows
        input_ffmpeg_path = str(input_file).replace("\\", "/").replace(":", "\\:")
        subtitle_filter = f"subtitles='{input_ffmpeg_path}':si={forced_burn_in_idx}:force_style='FontName=Arial'"
        command.extend(["-vf", subtitle_filter, "-c:v", "libx264", "-crf", "23", "-preset", "veryfast"]) 
    else:
        # If no forced subtitle or if video is already H.264, copy video stream
        command.extend(["-c:v", "copy"] if video_codec == "h264" else ["-c:v", "libx264", "-crf", "23", "-preset", "veryfast"])

    # Audio encoding strategy
    command.extend(["-c:a", "copy"] if audio_codec == "aac" else ["-c:a", "aac", "-b:a", "384k"])

    # Map video and audio streams
    command.extend(["-map", "0:v:0", "-map", "0:a:0"])

    # Add soft English subtitles if found and not already burned-in (though current logic keeps them separate)
    if soft_english_cc_idx >= 0:
        command.extend(["-map", f"0:s:{soft_english_cc_idx}", "-scodec:s", "mov_text"])

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
    # File started message
    logging.info(f"▶️ File: '{input_file.name}' - STARTED (Thread {threading.get_ident()})")

    output_file = input_file.with_suffix(".mp4")
    if output_file.exists():
        logging.info(f"⏭️ File: '{input_file.name}' - Already converted to '{output_file.name}'")
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
    
    logging.info(f"📝 File: '{input_file.name}' - Subtitles: {' + '.join(sub_status_parts)}")

    if AppConfig.DRY_RUN:
        logging.info(f"🧪 File: '{input_file.name}' - DRY-RUN ONLY. No actual conversion will occur.")
        return True

    temp_file = input_file.with_suffix(".temp.mp4")
    command = _build_ffmpeg_command(input_file, video_codec, audio_codec, forced_burn_in_idx, soft_english_cc_idx)
    command.append(str(temp_file)) # Add output file to the command

    # Converting message
    logging.info(f"🔄 File: '{input_file.name}' - CONVERTING...")

    try:
        # Execute FFmpeg command, capturing output for detailed error logging
        # Added encoding='utf-8' here for subprocess.run as well
        result = subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8')
        shutil.move(str(temp_file), str(output_file))
        input_file.unlink() # Delete original MKV only after successful conversion and move
        # Done message with new name
        logging.info(f"✅ File: '{input_file.name}' - DONE. Converted to: '{output_file.name}'")
        return True
    except FileNotFoundError:
        logging.error(f"❌ File: '{input_file.name}' - FAILED. FFmpeg not found at {AppConfig.FFMPEG_PATH}. Please check your path.")
        return False
    except subprocess.CalledProcessError as e:
        logging.error(f"❌ File: '{input_file.name}' - FAILED. FFmpeg conversion error. "
                      f"Return Code: {e.returncode}\nSTDOUT: {e.stdout.strip()}\nSTDERR: {e.stderr.strip()}")
        return False
    except Exception as e:
        logging.error(f"❌ File: '{input_file.name}' - FAILED. An unexpected error occurred: {e}")
        return False
    finally:
        # Ensure temporary file is always cleaned up
        if temp_file.exists():
            try:
                temp_file.unlink()
                logging.debug(f"🗑️ Cleaned up temporary file: {temp_file.name}")
            except OSError as e:
                logging.warning(f"⚠️ Could not delete temporary file {temp_file.name}: {e}")

# --- Main Workflow Functions ---
def flatten_and_clean_movies():
    """
    Moves all converted MP4 movies from source to a flat destination directory.
    Also removes empty directories in the source movie path after files are moved.
    """
    logging.info(f"\n--- 🎞️ Flattening Movies ---")
    mp4_files = list(AppConfig.SOURCE_MOVIES.rglob("*.mp4")) # Get all files first to count for tqdm
    for mp4_file in tqdm(mp4_files, desc="🚚 Moving Movies", dynamic_ncols=True):
        dest_file = AppConfig.DEST_MOVIES / mp4_file.name
        move_file(mp4_file, dest_file)

    # Clean up empty directories in source
    logging.info("🧹 Cleaning up empty movie directories...")
    for dirpath, dirnames, filenames in os.walk(AppConfig.SOURCE_MOVIES, topdown=False):
        if not dirnames and not filenames: # If directory has no subdirectories and no files
            try:
                if not AppConfig.DRY_RUN:
                    os.rmdir(dirpath)
                logging.info(f"🧹 Removed empty folder: {dirpath}")
            except OSError as e:
                logging.warning(f"⚠️ Could not remove empty folder {dirpath}: {e}")

def preserve_structure_tv():
    """
    Moves all converted MP4 TV shows from source to destination, preserving
    the original directory structure.
    """
    logging.info(f"\n--- 📺 Preserving TV Show Structure ---")
    mp4_files = list(AppConfig.SOURCE_TV.rglob("*.mp4")) # Get all files first to count for tqdm
    for mp4_file in tqdm(mp4_files, desc="🚚 Moving TV Shows", dynamic_ncols=True):
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
    logging.info(f"🔍 Found {len(all_files_mkv)} MKV files to process.")

    # Step 1: Pre-clean filenames for all found MKV files
    logging.info("✨ Cleaning filenames before conversion...")
    cleaned_files_for_conversion = []
    for file_path in tqdm(all_files_mkv, desc="✨ Cleaning Filenames", dynamic_ncols=True):
        cleaned_files_for_conversion.append(clean_filename(file_path))

    # Step 2: Perform concurrent conversion
    results = []
    with ThreadPoolExecutor(max_workers=AppConfig.MAX_WORKERS) as executor:
        futures = {executor.submit(convert_to_mp4, f): f for f in cleaned_files_for_conversion}
        for future in tqdm(as_completed(futures), total=len(futures), desc="🔄 Converting", dynamic_ncols=True):
            file_being_processed = futures[future] # Original path (potentially cleaned) for logging
            success = future.result()
            if AppConfig.LOGGING_ENABLED:
                conversion_log[str(file_being_processed)] = "converted" if success else "error"
            results.append(success)
            save_log() # Save log after each conversion attempt
    logging.info(f"📊 Conversion Summary: Converted: {results.count(True)} | ❌ Failed: {results.count(False)}")

def main():
    """
    Main function to orchestrate the media conversion process.
    Initializes logging, performs conversions, and then organizes the converted files.
    """
    setup_logging()
    logging.info("▶️ Starting media conversion process...")
    convert_all()
    flatten_and_clean_movies()
    preserve_structure_tv()
    logging.info("🎉 Media conversion process completed.")

if __name__ == "__main__":
    main()
