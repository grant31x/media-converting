# file_handler.py
# Updated to use a list of path mappings for flexible transfers.

import shutil
import json
from pathlib import Path
import logging
from datetime import datetime
from typing import List, Callable, Dict

from models import MediaFile

LOG_FILE = Path("./move_log.json")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def read_move_log() -> dict:
    if not LOG_FILE.exists():
        return {}
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}

def write_move_log(log_data: dict):
    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=4)
    except IOError as e:
        logging.error(f"Could not write to log file: {e}")

def move_converted_files(
    media_files: List[MediaFile], 
    path_mappings: List[Dict[str, str]],
    dry_run: bool = False,
    progress_callback: Callable = None
):
    """
    Moves files based on a list of source-to-destination mappings.
    """
    move_log = read_move_log()
    total_files = len(media_files)
    
    for i, media in enumerate(media_files):
        converted_file_path = media.destination_path
        
        if progress_callback:
            percent = int(((i + 1) / total_files) * 100)
            progress_callback(percent, f"Moving file {i+1} of {total_files}: {converted_file_path.name}")
        
        if not converted_file_path or not converted_file_path.exists():
            logging.warning(f"Skipping '{media.filename}' - converted file not found at '{converted_file_path}'.")
            continue

        # Find the correct destination from the mappings
        final_destination_path = None
        source_root_for_cleanup = None
        for mapping in path_mappings:
            source_root = Path(mapping["source"])
            
            # FIXED: Check if the file's parent is the source root OR a subdirectory of the source root.
            if media.source_path.parent == source_root or source_root in media.source_path.parents:
                final_destination_path = Path(mapping["destination"]) / converted_file_path.name
                source_root_for_cleanup = source_root
                break
        
        if not final_destination_path:
            logging.error(f"No valid path mapping found for source '{media.source_path}'. Skipping.")
            continue
        
        try:
            if dry_run:
                print(f"[DRY RUN] Would move: '{converted_file_path}' -> '{final_destination_path}'")
                media.status = "Transferred (Dry Run)"
                continue

            final_destination_path.parent.mkdir(parents=True, exist_ok=True)
            
            logging.info(f"Moving '{converted_file_path.name}' to '{final_destination_path}'...")
            shutil.move(str(converted_file_path), str(final_destination_path))
            
            media.status = "Transferred"
            logging.info(f"Successfully moved '{final_destination_path.name}'.")
            move_log[str(media.source_path)] = {
                "final_destination": str(final_destination_path),
                "status": "Moved",
                "timestamp": datetime.now().isoformat()
            }
            
            original_parent_dir = media.source_path.parent
            if not media.source_path.exists() and original_parent_dir.exists():
                if original_parent_dir != source_root_for_cleanup:
                    if not any(original_parent_dir.iterdir()):
                        logging.info(f"Source folder '{original_parent_dir}' is empty. Deleting.")
                        original_parent_dir.rmdir()

        except Exception as e:
            media.status = "Transfer Error"
            media.error_message = str(e)
            logging.error(f"Failed to move '{converted_file_path.name}': {e}")
            move_log[str(media.source_path)] = {
                "final_destination": str(final_destination_path),
                "status": "Failed",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
        finally:
            write_move_log(move_log)

    logging.info("--- File transfer process complete. ---")
    return media_files