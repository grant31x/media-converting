# basic_convert.py
# This module handles fast, simple MKV to MP4 remuxing (no re-encoding).

import subprocess
import shlex
from pathlib import Path
from typing import List
import concurrent.futures

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
    
    final_output_path = media.source_path.with_suffix(".mp4")
    temp_output_path = media.source_path.with_suffix(".temp.mp4")
    media.destination_path = final_output_path
    
    temp_output_path.unlink(missing_ok=True)
    
    try:
        if media.source_path.exists():
            media.original_size_gb = media.source_path.stat().st_size / (1024**3)

        command = [
            "ffmpeg", "-y",
            "-i", str(media.source_path),
            "-c:v", "copy",
            "-c:a", "copy",
            "-sn",
            str(temp_output_path)
        ]
        
        print(f"\nProcessing (Basic): {media.filename}")
        print(f"  Command: {' '.join(shlex.quote(str(c)) for c in command)}")

        if settings.dry_run:
            media.status = "Dry Run (Basic)"
            return

        subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8')
        
        temp_output_path.rename(final_output_path)
        
        media.status = "Converted (Basic)"
        print(f"  -> Success: Remuxed '{media.filename}'")

        if final_output_path.exists():
            media.converted_size_gb = final_output_path.stat().st_size / (1024**3)
        
        setattr(media, 'audio_conversion_details', "Copied (Remux)")
        media.burned_subtitle = None
        for track in media.subtitle_tracks:
            track.action = "ignore"

    except Exception as e:
        media.status = "Error (Basic)"
        error_output = getattr(e, 'stderr', str(e))
        media.error_message = f"Basic remux failed: {error_output.strip()[-250:]}"
        print(f"  -> [ERROR] {media.error_message}")
    finally:
        if temp_output_path.exists():
            temp_output_path.unlink()

def run_batch_basic_conversion(media_files: List[MediaFile], settings: ConversionSettings):
    """
    Performs basic remuxing for a batch of files concurrently.

    Args:
        media_files: A list of MediaFile objects to process.
        settings: The application's conversion settings.
    """
    print(f"Starting basic conversion for {len(media_files)} files using up to 3 threads.")
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(run_basic_conversion, media, settings) for media in media_files]
        
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                print(f'A basic conversion task generated an exception: {exc}')

    return media_files