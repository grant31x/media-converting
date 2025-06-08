# robocopy.py
# This script provides a robust way to move .mp4 files from source drives
# to a destination, preserving the directory structure using Robocopy.

import subprocess
import json
import sys
from pathlib import Path
import logging
import argparse
from datetime import datetime

# --- Platform-specific subprocess creation flags ---
if sys.platform == "win32":
    CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW
else:
    CREATE_NO_WINDOW = 0

SOURCE_FOLDERS = [Path("E:/Movies"), Path("E:/TV Shows")]
DESTINATION_BASE = Path("Z:/")
LOG_FILE = Path("./robocopy_log.json")
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

def move_all_mp4s(source_base: Path, dest_base: Path, dry_run: bool = False):
    logging.info(f"Scanning for .mp4 files in '{source_base}'...")
    mp4_files = list(source_base.rglob("*.mp4"))
    if not mp4_files:
        logging.info(f"No .mp4 files found in '{source_base}'.")
        return
    logging.info(f"Found {len(mp4_files)} .mp4 files. Preparing to move...")
    move_log = read_move_log()
    for source_path in mp4_files:
        try:
            relative_path = source_path.relative_to(source_base)
            dest_path = dest_base / source_base.name / relative_path
            if str(source_path) in move_log and move_log[str(source_path)].get("status") == "Moved":
                logging.info(f"Skipping logged file: {source_path.name}")
                continue
            if dest_path.exists():
                if dest_path.stat().st_size == source_path.stat().st_size:
                    logging.warning(f"Skipping '{source_path.name}' (file exists at destination with same size).")
                    continue
                else:
                    logging.warning(f"Destination file '{dest_path.name}' exists but sizes differ. It will be overwritten.")
            if dry_run:
                print(f"[DRY RUN] Would move: '{source_path}' -> '{dest_path}'")
                continue
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            source_dir = str(source_path.parent)
            dest_dir = str(dest_path.parent)
            file_name = source_path.name
            command = ["robocopy", source_dir, dest_dir, file_name, "/MOVE", "/E", "/J", "/R:1", "/W:1"]
            logging.info(f"Moving '{file_name}'...")
            result = subprocess.run(command, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
            if result.returncode >= 8:
                raise subprocess.CalledProcessError(result.returncode, command, output=result.stdout, stderr=result.stderr)
            logging.info(f"Successfully moved '{dest_path.name}'")
            move_log[str(source_path)] = {"destination": str(dest_path), "status": "Moved", "timestamp": datetime.now().isoformat()}
        except FileNotFoundError:
            logging.error("robocopy.exe not found. Is it in your system's PATH?")
            break
        except Exception as e:
            logging.error(f"Failed to move '{source_path.name}': {e}")
            move_log[str(source_path)] = {"destination": str(dest_path), "status": "Failed", "error": str(e), "timestamp": datetime.now().isoformat()}
        finally:
            write_move_log(move_log)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Move .mp4 files using Robocopy while preserving directory structure.")
    parser.add_argument("--dry-run", action="store_true", help="Simulate the move without actually moving any files.")
    args = parser.parse_args()
    if args.dry_run:
        print("--- RUNNING IN DRY-RUN MODE ---")
    for folder in SOURCE_FOLDERS:
        move_all_mp4s(folder, DESTINATION_BASE, dry_run=args.dry_run)
    print("--- File transfer process complete. ---")