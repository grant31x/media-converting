# robocopy.py
# This module handles the final transfer of converted media files to their destination.

import shutil
import json
from pathlib import Path
from typing import List, Dict, Any

# Import the data models. We assume the MediaFile object will be populated
# with additional attributes like `media_type`, `title`, etc., before being passed here.
from models import MediaFile

# --- Configuration ---
# In a real application, these might be part of a settings class or config file.
MOVIE_DESTINATION_BASE = Path("Z:/Movies")
TV_SHOW_DESTINATION_BASE = Path("Z:/TV Shows")
MOVE_LOG_FILE = Path("./move_log.json")

def move_batch(media_files: List[MediaFile], dry_run: bool = False):
    """
    Processes a list of MediaFile objects, moving them to their final destination.

    Args:
        media_files: A list of converted MediaFile objects to move.
        dry_run: If True, simulates the move without touching files.
    """
    print("--- Starting Final File Transfer ---")
    move_log = _read_move_log()

    for media in media_files:
        # We only want to move files that were successfully converted.
        if media.status != "Converted":
            print(f"Skipping '{media.filename}' (status is '{media.status}', not 'Converted').")
            continue
        
        move_converted_file(media, move_log, dry_run=dry_run)
    
    print("--- File Transfer Finished ---")

def _read_move_log() -> Dict[str, Any]:
    """Reads the move log JSON file."""
    if not MOVE_LOG_FILE.exists():
        return {}
    try:
        with open(MOVE_LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        # If the log is corrupted or unreadable, start with a fresh one.
        return {}

def _write_to_move_log(log_data: Dict[str, Any]):
    """Writes data to the move log JSON file."""
    try:
        with open(MOVE_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=4)
    except IOError as e:
        print(f"Error: Could not write to move log file: {e}")

def move_converted_file(media: MediaFile, move_log: Dict[str, Any], dry_run: bool):
    """
    Moves a single converted file to its final destination based on its type.

    Args:
        media: The MediaFile object for the converted file.
        move_log: The dictionary tracking already moved files.
        dry_run: If True, simulates the move.
    """
    source_path = media.destination_path # This is the output path from convert.py
    
    # --- Pre-move Checks ---
    if not source_path or not source_path.exists():
        media.status = "Error (Move)"
        media.error_message = f"Source file not found at '{source_path}'."
        print(f"Error: Cannot move '{media.filename}'. {media.error_message}")
        return

    if str(source_path) in move_log:
        media.status = "Skipped (Moved)"
        print(f"Skipping '{source_path.name}', already in move log.")
        return

    try:
        # 1. Determine the final destination path
        final_destination = _get_final_destination_path(media)
        if not final_destination:
            return # Error message is already set in media object by the helper

        print(f"\nPlanning move for: {source_path.name}")
        print(f"  -> Type: {getattr(media, 'media_type', 'N/A')}")
        print(f"  -> Destination: {final_destination}")

        if dry_run:
            media.status = "Dry Run (Move)"
            print("  -> Dry Run: Move not executed.")
            return

        # 2. Create the destination directory if it doesn't exist
        final_destination.parent.mkdir(parents=True, exist_ok=True)
        
        # 3. Move the file
        # shutil.move is a cut-and-paste operation.
        # For more robust, resumable copies on Windows, a robocopy subprocess is a great alternative.
        shutil.move(source_path, final_destination)
        
        media.status = "Transferred"
        print(f"  -> Success: Moved file to '{final_destination}'")
        
        # 4. Update the log on success
        move_log[str(source_path)] = {
            "destination": str(final_destination),
            "status": "Transferred"
        }
        _write_to_move_log(move_log)

    except Exception as e:
        media.status = "Error (Move)"
        media.error_message = f"Failed to move file: {e}"
        print(f"  -> Error: {media.error_message}")

def _get_final_destination_path(media: MediaFile) -> Path | None:
    """
    Constructs the final, renamed path for a media file based on its type.
    
    Returns:
        A Path object for the final destination, or None if an error occurs.
    """
    try:
        media_type = getattr(media, 'media_type')
        title = getattr(media, 'title')
        
        if media_type == "movie":
            return MOVIE_DESTINATION_BASE / f"{title}{media.destination_path.suffix}"
            
        elif media_type == "tv":
            season = getattr(media, 'season')
            episode = getattr(media, 'episode')
            season_folder = f"Season {season:02d}"
            # e.g., "The Expanse S01E01.mp4"
            file_name = f"{title} S{season:02d}E{episode:02d}{media.destination_path.suffix}"
            return TV_SHOW_DESTINATION_BASE / title / season_folder / file_name
        else:
            media.error_message = f"Unknown media_type: '{media_type}'"
            return None

    except AttributeError as e:
        media.status = "Error (Move)"
        media.error_message = f"Missing required attribute for move: {e}"
        print(f"Error: Cannot determine destination for '{media.filename}'. {media.error_message}")
        return None

# Example Usage:
if __name__ == "__main__":
    from models import SubtitleTrack, ConversionSettings # For creating test objects
    
    print("--- Running transfer module in test mode (Dry Run) ---")
    
    # 1. Setup mock environment
    staging_dir = Path("./__converted_output__")
    staging_dir.mkdir(exist_ok=True)
    
    # 2. Create mock MediaFile objects as they would be after conversion
    
    # --- MOVIE SCENARIO ---
    movie_file = MediaFile(source_path=Path("dummy.mkv"))
    movie_file.output_filename = "Dune Part Two (2024).mp4"
    movie_file.destination_path = staging_dir / movie_file.output_filename
    movie_file.destination_path.touch() # Create dummy file
    movie_file.status = "Converted"
    # Add the extra attributes needed for moving
    setattr(movie_file, "media_type", "movie")
    setattr(movie_file, "title", "Dune Part Two (2024)")
    
    # --- TV SHOW SCENARIO ---
    tv_file = MediaFile(source_path=Path("dummy.mkv"))
    tv_file.output_filename = "Shogun.S01E05.mp4"
    tv_file.destination_path = staging_dir / tv_file.output_filename
    tv_file.destination_path.touch() # Create dummy file
    tv_file.status = "Converted"
    # Add the extra attributes
    setattr(tv_file, "media_type", "tv")
    setattr(tv_file, "title", "Shōgun (2024)")
    setattr(tv_file, "season", 1)
    setattr(tv_file, "episode", 5)

    # --- FAILED CONVERSION SCENARIO ---
    failed_file = MediaFile(source_path=Path("dummy.mkv"))
    failed_file.status = "Error" # Should be skipped by the mover

    # 3. Run the batch move
    batch_list = [movie_file, tv_file, failed_file]
    move_batch(batch_list, dry_run=True) # DRY RUN IS ON
    
    # 4. Print final statuses
    print("\n--- Final Statuses after Move ---")
    for m in batch_list:
        print(f"File: {m.filename}, Status: {m.status}")
        if m.error_message:
            print(f"  -> Message: {m.error_message}")

    # 5. Cleanup
    if MOVE_LOG_FILE.exists():
        MOVE_LOG_FILE.unlink()
    for f in staging_dir.glob("*"): f.unlink()
    staging_dir.rmdir()
