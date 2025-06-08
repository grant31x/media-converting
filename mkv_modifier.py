# mkv_modifier.py
# This module contains functions to directly modify MKV files, such as removing tracks.

import subprocess
import json
from pathlib import Path
from typing import List
import logging

# --- Configuration for MKVToolNix ---
MKVTOOLNIX_PATH = Path("C:/Program Files/MKVToolNix/")
MKVMERGE_PATH = MKVTOOLNIX_PATH / "mkvmerge.exe"

def remove_subtitle_tracks(mkv_file: Path, track_ids_to_remove: List[int]) -> bool:
    """
    Rewrites an MKV file to physically exclude a list of specific subtitle tracks.
    This is a destructive operation that replaces the original file.

    Args:
        mkv_file: The path to the MKV file to modify.
        track_ids_to_remove: A list of track IDs of the subtitles to remove.

    Returns:
        True if successful, False otherwise.
    """
    if not MKVMERGE_PATH.exists():
        logging.error(f"mkvmerge.exe not found at {MKVMERGE_PATH}. Cannot modify file.")
        return False

    temp_output_file = mkv_file.with_name(f"{mkv_file.stem}_modified.mkv")
    
    try:
        # Step 1: Identify all tracks in the source file
        id_cmd = [str(MKVMERGE_PATH), "-J", str(mkv_file)]
        result = subprocess.run(id_cmd, check=True, capture_output=True, text=True, encoding='utf-8')
        data = json.loads(result.stdout)

        video_tracks, audio_tracks, subtitle_tracks_to_keep = [], [], []
        
        # Step 2: Build lists of track IDs to keep
        for track in data.get("tracks", []):
            tid = str(track['id'])
            if track['type'] == 'video':
                video_tracks.append(tid)
            elif track['type'] == 'audio':
                audio_tracks.append(tid)
            elif track['type'] == 'subtitles':
                # FIX: Only add the subtitle if its ID is NOT in the removal list
                if track['id'] not in track_ids_to_remove:
                    subtitle_tracks_to_keep.append(tid)

        if not video_tracks and not audio_tracks:
            logging.error(f"No video or audio tracks found in {mkv_file.name}. Aborting modification.")
            return False

        # Step 3: Build the mkvmerge command to copy only the desired tracks
        command = [
            str(MKVMERGE_PATH),
            "-o", str(temp_output_file),
            "--video-tracks", ",".join(video_tracks),
            "--audio-tracks", ",".join(audio_tracks),
        ]
        if subtitle_tracks_to_keep:
            command.extend(["--subtitle-tracks", ",".join(subtitle_tracks_to_keep)])
        else:
            command.append("--no-subtitles")
        
        command.append(str(mkv_file))

        print(f"Rewriting MKV to remove tracks {track_ids_to_remove}: {' '.join(command)}")
        
        # Step 4: Execute the rewrite process
        subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8')
        
        # Step 5: Verify and replace the original file
        if temp_output_file.exists() and temp_output_file.stat().st_size > 0:
            mkv_file.unlink() # Delete original
            temp_output_file.rename(mkv_file) # Rename temp to original name
            logging.info(f"Successfully removed tracks {track_ids_to_remove} from '{mkv_file.name}'")
            return True
        else:
            logging.error(f"Modified file '{temp_output_file.name}' was not created or is empty.")
            temp_output_file.unlink(missing_ok=True)
            return False

    except Exception as e:
        logging.error(f"Failed to modify MKV file '{mkv_file.name}': {e}")
        error_details = getattr(e, 'stderr', '')
        logging.error(f"mkvmerge details: {error_details}")
        if temp_output_file.exists():
            temp_output_file.unlink()
        return False
