# convert.py
# This module handles the video conversion process using FFmpeg with a safe temp-file workflow.

import subprocess
import shlex
from pathlib import Path
from typing import List

# Import the data models and settings from our models.py file
from models import MediaFile, SubtitleTrack, ConversionSettings

def convert_batch(media_files: List[MediaFile], settings: ConversionSettings) -> List[MediaFile]:
    """
    Processes a list of MediaFile objects, converting them based on settings.

    Args:
        media_files: A list of MediaFile objects to process.
        settings: The global conversion settings.

    Returns:
        The updated list of MediaFile objects with new statuses.
    """
    print("--- Starting Batch Conversion ---")
    for media in media_files:
        if _should_skip_conversion(media, settings):
            continue
        
        # Pass the delete_source flag from settings, defaulting to False for safety.
        delete_source = getattr(settings, 'delete_source_on_success', False)
        convert_media_file(media, settings, delete_source=delete_source)
    
    print("--- Batch Conversion Finished ---")
    return media_files

def _should_skip_conversion(media: MediaFile, settings: ConversionSettings) -> bool:
    """
    Determines if a file conversion should be skipped based on its state or existence at destination.

    Args:
        media: The MediaFile object to check.
        settings: The conversion settings, used to find the output directory.

    Returns:
        True if the conversion should be skipped, False otherwise.
    """
    if not media.needs_conversion:
        print(f"Skipping '{media.filename}' (manually marked as not needing conversion).")
        media.status = "Skipped"
        return True
    
    # Check if final file already exists to prevent overwriting
    final_output_path = settings.output_directory / media.output_filename
    if final_output_path.exists():
        print(f"Skipping '{media.filename}' (destination file already exists).")
        media.status = "Skipped (Exists)"
        return True

    is_mp4 = media.source_path.suffix.lower() == ".mp4"
    if is_mp4 and not media.burned_subtitle:
        print(f"Skipping '{media.filename}' (already MP4 and no burn-in required).")
        media.status = "Skipped"
        return True
        
    return False

def convert_media_file(media: MediaFile, settings: ConversionSettings, delete_source: bool = False):
    """
    Converts a single media file using FFmpeg, employing a temporary file for safety.

    Args:
        media: The MediaFile to convert.
        settings: The conversion settings.
        delete_source: If True, the original .mkv file will be deleted upon success.
    """
    media.status = "Converting"
    final_output_path = settings.output_directory / media.output_filename
    # Define a temporary output file path.
    temp_output_path = final_output_path.with_suffix(".temp.mp4")
    media.destination_path = final_output_path  # The ultimate destination remains the same.
    
    # Pre-cleanup: ensure no old temp file exists from a previous failed run.
    temp_output_path.unlink(missing_ok=True)
    
    try:
        # 1. Build the command to write to the temporary file.
        cmd_list = _build_ffmpeg_command(media, settings, temp_output_path)
        cmd_str = " ".join(shlex.quote(str(c)) for c in cmd_list)
        print(f"\nProcessing: {media.filename}")
        print(f"  -> Writing to temp file: {temp_output_path.name}")
        print(f"  Command: {cmd_str}")

        if settings.dry_run:
            media.status = "Dry Run"
            print("  -> Dry Run: Command not executed.")
            return

        # 2. Execute the FFmpeg command.
        subprocess.run(
            cmd_list,
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True # Will raise CalledProcessError on non-zero exit codes.
        )
        
        # 3. VERIFY & RENAME: If successful, rename the temp file to the final name.
        print(f"  -> FFmpeg process completed successfully.")
        print(f"  -> Renaming '{temp_output_path.name}' to '{final_output_path.name}'")
        temp_output_path.rename(final_output_path)
        
        media.status = "Converted"
        
        # 4. DELETE SOURCE (Optional): If enabled, delete the original .mkv file.
        if delete_source:
            print(f"  -> Deleting source file: '{media.source_path}'")
            try:
                media.source_path.unlink()
            except Exception as e:
                print(f"  -> Warning: Failed to delete source file. Error: {e}")
        else:
            print("  -> Source file preserved as per settings.")

    except subprocess.CalledProcessError as e:
        media.status = "Error"
        error_details = e.stderr.strip().split('\n')[-3:] # Get last few lines of error.
        media.error_message = f"FFmpeg failed. Error: {' '.join(error_details)}"
        print(f"  -> Error: {media.error_message}")
        # CLEANUP: Delete the partial temp file on failure.
        print(f"  -> Cleaning up partial temp file: '{temp_output_path.name}'")
        temp_output_path.unlink(missing_ok=True)

    except Exception as e:
        media.status = "Error"
        media.error_message = f"An unexpected error occurred during conversion: {e}"
        print(f"  -> Error: {media.error_message}")
        # CLEANUP: Delete the partial temp file on failure.
        print(f"  -> Cleaning up partial temp file: '{temp_output_path.name}'")
        temp_output_path.unlink(missing_ok=True)

def _build_ffmpeg_command(media: MediaFile, settings: ConversionSettings, output_path: Path) -> List[str]:
    """Constructs the full FFmpeg command, pointing to a specified output path."""
    
    # Use -n to prevent overwriting temp file, though our script's logic should already prevent this.
    command = ["ffmpeg", "-n", "-i", media.source_path]

    video_filters = []
    if media.burned_subtitle:
        subtitle_file_path = str(media.source_path).replace('\\', '/').replace(':', '\\:')
        video_filters.append(f"subtitles='{subtitle_file_path}':stream_index={media.burned_subtitle.index}")
    
    if video_filters:
        command.extend(["-vf", ",".join(video_filters)])

    if media.burned_subtitle:
        if settings.use_nvenc:
            command.extend(["-c:v", "hevc_nvenc", "-preset", "p5", "-rc:v", "vbr_hq", "-cq", "20", "-tier", "high"])
        else:
            command.extend(["-c:v", "libx265", "-crf", str(settings.crf), "-preset", "slow"])
    else:
        command.extend(["-c:v", "copy"])

    command.extend(["-map", "0:a", "-c:a", settings.audio_codec, "-b:a", settings.audio_bitrate])

    soft_copy_subs = [s for s in media.subtitle_tracks if s.action == 'copy']
    output_sub_index = 0
    TEXT_SUB_CODECS = ['subrip', 'ass', 'mov_text', 'ssa']

    for sub in soft_copy_subs:
        if sub.codec in TEXT_SUB_CODECS:
            command.extend(["-map", f"0:s:{sub.ffmpeg_index}", f"-c:s:{output_sub_index}", "mov_text"])
            output_sub_index += 1
    
    command.extend(["-map", "0:v", "-map_metadata", "0"])
    
    # CRITICAL: Use the passed output path (which should be the .temp.mp4 path).
    command.append(output_path)

    return command
