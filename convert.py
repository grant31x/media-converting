# convert.py
# This module handles the video conversion process using FFmpeg.

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
        if _should_skip_conversion(media):
            print(f"Skipping '{media.filename}' (already MP4 or marked as not needing conversion).")
            media.status = "Skipped"
            continue
        
        convert_media_file(media, settings)
    
    print("--- Batch Conversion Finished ---")
    return media_files

def _should_skip_conversion(media: MediaFile) -> bool:
    """
    Determines if a file conversion should be skipped.

    Args:
        media: The MediaFile object to check.

    Returns:
        True if the conversion should be skipped, False otherwise.
    """
    # Skip if the user manually flagged it
    if not media.needs_conversion:
        return True
    
    # Skip if it's already an MP4 and no subtitle burn-in is required.
    # Burning subtitles always requires a full video re-encode.
    is_mp4 = media.source_path.suffix.lower() == ".mp4"
    if is_mp4 and not media.burned_subtitle:
        return True
        
    return False

def convert_media_file(media: MediaFile, settings: ConversionSettings):
    """
    Converts a single media file using FFmpeg.

    Args:
        media: The MediaFile to convert.
        settings: The conversion settings.
    """
    media.status = "Converting"
    output_path = settings.output_directory / media.output_filename
    media.destination_path = output_path
    
    try:
        # 1. Build the command based on the file's needs and user settings
        cmd_list = _build_ffmpeg_command(media, settings)
        cmd_str = " ".join(shlex.quote(str(c)) for c in cmd_list)
        print(f"\nProcessing: {media.filename}")
        print(f"  Command: {cmd_str}")

        if settings.dry_run:
            media.status = "Dry Run"
            print("  -> Dry Run: Command not executed.")
            return

        # 2. Execute the FFmpeg command
        result = subprocess.run(
            cmd_list,
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True # Will raise CalledProcessError on failure
        )
        
        media.status = "Converted"
        print(f"  -> Success: Converted '{media.filename}' to '{output_path.name}'")
        # In a real run, you'd get file sizes here
        # media.converted_size_mb = output_path.stat().st_size / (1024 * 1024)

    except FileNotFoundError:
        media.status = "Error"
        media.error_message = "ffmpeg command not found. Is FFmpeg installed and in your system's PATH?"
        print(f"  -> Error: {media.error_message}")
    except subprocess.CalledProcessError as e:
        media.status = "Error"
        error_details = e.stderr.strip().split('\n')[-3:] # Get last few lines of error
        media.error_message = f"FFmpeg failed with exit code {e.returncode}. Error: {' '.join(error_details)}"
        print(f"  -> Error: {media.error_message}")
    except Exception as e:
        media.status = "Error"
        media.error_message = f"An unexpected error occurred: {e}"
        print(f"  -> Error: {media.error_message}")


def _build_ffmpeg_command(media: MediaFile, settings: ConversionSettings) -> List[str]:
    """Constructs the full FFmpeg command as a list of arguments."""
    
    # --- Base Command ---
    command = ["ffmpeg", "-y", "-i", media.source_path]

    # --- Video Filter (for burning subtitles) ---
    video_filters = []
    if media.burned_subtitle:
        # IMPORTANT: FFmpeg needs the source file path escaped for the subtitles filter.
        # On Windows, this involves escaping colons and backslashes.
        subtitle_file_path = str(media.source_path).replace('\\', '/').replace(':', '\\:')
        # Use the original stream index for the filter
        video_filters.append(f"subtitles='{subtitle_file_path}':stream_index={media.burned_subtitle.index}")
    
    if video_filters:
        command.extend(["-vf", ",".join(video_filters)])

    # --- Video Codec ---
    # Re-encode if burning subs, otherwise copy if possible.
    if media.burned_subtitle:
        if settings.use_nvenc:
            command.extend([
                "-c:v", "hevc_nvenc",
                "-preset", "p5",
                "-rc:v", "vbr_hq",
                "-cq", "20",
                "-tier", "high"
            ])
        else:
            # Fallback to software encoding
            command.extend(["-c:v", "libx265", "-crf", str(settings.crf), "-preset", "slow"])
    else:
        command.extend(["-c:v", "copy"])

    # --- Audio Codec ---
    # Map all audio streams and re-encode to AAC if necessary.
    command.extend(["-map", "0:a", "-c:a", settings.audio_codec, "-b:a", settings.audio_bitrate])

    # --- Subtitle Handling (Soft-copy) ---
    soft_copy_subs = [s for s in media.subtitle_tracks if s.action == 'copy']
    output_sub_index = 0
    
    # We can only copy text-based subtitles to MP4.
    TEXT_SUB_CODECS = ['subrip', 'ass', 'mov_text', 'ssa']

    for sub in soft_copy_subs:
        if sub.codec in TEXT_SUB_CODECS:
            # Map the subtitle stream using its relative ffmpeg index
            command.extend(["-map", f"0:s:{sub.ffmpeg_index}"])
            # Set the codec for this specific output stream
            command.extend([f"-c:s:{output_sub_index}", "mov_text"])
            output_sub_index += 1
    
    # If no streams are explicitly mapped, ffmpeg picks the "best" one.
    # To ensure we only get what we want, we should map the video stream too.
    command.extend(["-map", "0:v"])

    # --- Metadata and Output ---
    command.extend(["-map_metadata", "0"])
    command.append(settings.output_directory / media.output_filename)

    return command

# Example Usage:
if __name__ == "__main__":
    print("--- Running converter module in test mode (Dry Run) ---")
    
    # 1. Setup a mock environment
    test_dir = Path("./__test_mkv_folder__")
    output_dir = Path("./__converted_output__")
    test_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)
    dummy_mkv_path = test_dir / "Alien.Invasion.2025.mkv"
    dummy_mkv_path.touch()

    # 2. Define Conversion Settings
    conv_settings = ConversionSettings(
        output_directory=output_dir,
        use_nvenc=True,
        dry_run=True  # IMPORTANT: Set to True for testing to only print commands
    )
    
    # 3. Create mock MediaFile objects for different scenarios

    # --- SCENARIO 1: Burn-in a forced subtitle ---
    media1 = MediaFile(source_path=dummy_mkv_path)
    sub_forced = SubtitleTrack(index=3, ffmpeg_index=1, language="eng", title="Forced", is_forced=True)
    media1.subtitle_tracks = [
        SubtitleTrack(index=2, ffmpeg_index=0, language="eng", title="Full"),
        sub_forced
    ]
    media1.burned_subtitle = sub_forced # User or logic has selected this for burning
    sub_forced.action = 'burn'

    # --- SCENARIO 2: Soft-copy two subtitles ---
    media2 = MediaFile(source_path=dummy_mkv_path)
    media2.output_filename = "soft_copy_test.mp4"
    sub_eng = SubtitleTrack(index=2, ffmpeg_index=0, language="eng", codec="subrip", action="copy")
    sub_spa = SubtitleTrack(index=3, ffmpeg_index=1, language="spa", codec="subrip", action="copy")
    sub_pgs = SubtitleTrack(index=4, ffmpeg_index=2, language="eng", codec="hdmv_pgs_subtitle", action="copy") # Image-based, should be ignored
    media2.subtitle_tracks = [sub_eng, sub_spa, sub_pgs]

    # --- SCENARIO 3: File to be skipped ---
    media3 = MediaFile(source_path=Path("already_converted.mp4"))

    # 4. Run the batch conversion
    batch_list = [media1, media2, media3]
    convert_batch(batch_list, conv_settings)
    
    # 5. Print results
    print("\n--- Final Statuses ---")
    for m in batch_list:
        print(f"File: {m.filename}, Status: {m.status}")
        if m.error_message:
            print(f"  Error: {m.error_message}")
            
    # 6. Cleanup
    dummy_mkv_path.unlink()
    test_dir.rmdir()
    # Note: In a real dry run, the output directory would remain empty.
    # If not a dry run, you'd want to clean up generated files.
    for f in output_dir.glob("*"): f.unlink()
    output_dir.rmdir()

