# basic_convert.py
# This module handles fast, simple MKV to MP4 remuxing (no re-encoding).

import subprocess
import shlex
from pathlib import Path

from models import MediaFile, ConversionSettings

def run_basic_conversion(media: MediaFile, settings: ConversionSettings):
    """
    Performs a basic remux of an MKV file to MP4, copying video/audio and discarding subtitles.
    This is very fast as it does not re-encode video or audio.

    Args:
        media: The MediaFile object to process.
        settings: The application's conversion settings.
    """
    media.status = "Remuxing"
    
    # In a basic conversion, the output path is always next to the source.
    final_output_path = media.source_path.with_suffix(".mp4")
    temp_output_path = media.source_path.with_suffix(".temp.mp4")
    media.destination_path = final_output_path
    
    # Pre-cleanup of any old temp files
    temp_output_path.unlink(missing_ok=True)
    
    try:
        # Get original file size for comparison
        if media.source_path.exists():
            media.original_size_gb = media.source_path.stat().st_size / (1024**3)

        # Build the simple FFmpeg remux command
        command = [
            "ffmpeg", "-y",
            "-i", str(media.source_path),
            "-c:v", "copy",        # Copy the video stream without re-encoding
            "-c:a", "copy",        # Copy the audio stream without re-encoding
            "-sn",                 # Exclude (skip) all subtitle streams
            str(temp_output_path)
        ]
        
        print(f"\nProcessing (Basic): {media.filename}")
        print(f"  Command: {' '.join(shlex.quote(str(c)) for c in command)}")

        if settings.dry_run:
            media.status = "Dry Run (Basic)"
            return

        # Execute the command
        subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8')
        
        # Rename the temp file to the final output file on success
        temp_output_path.rename(final_output_path)
        
        media.status = "Converted (Basic)"
        print(f"  -> Success: Remuxed '{media.filename}'")

        # Get final file size and set details for the summary view
        if final_output_path.exists():
            media.converted_size_gb = final_output_path.stat().st_size / (1024**3)
        
        setattr(media, 'audio_conversion_details', "Copied (Remux)")
        # Since we use -sn, no subs are processed. Clear any prior selections.
        media.burned_subtitle = None
        for track in media.subtitle_tracks:
            track.action = "ignore"


    except Exception as e:
        media.status = "Error (Basic)"
        error_output = getattr(e, 'stderr', str(e))
        media.error_message = f"Basic remux failed: {error_output.strip()[-250:]}"
        print(f"  -> [ERROR] {media.error_message}")
    finally:
        # Ensure the temp file is deleted on failure
        if temp_output_path.exists():
            temp_output_path.unlink()
