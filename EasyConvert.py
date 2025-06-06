import re
import subprocess
import logging
from pathlib import Path
from tqdm import tqdm
import os
import json
import shutil

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Configuration
FFMPEG_PATH = r"C:\\Programs2\\ffmpeg\\ffmpeg_essentials_build\\bin\\ffmpeg.exe"
FFPROBE_PATH = r"C:\\Programs2\\ffmpeg\\ffmpeg_essentials_build\\bin\\ffprobe.exe"
SOURCE_FOLDERS = [Path(r"Z:\\Movies"), Path(r"Z:\\TV Shows")]
LOG_FILE = Path("D:/Python/conversion_log.json")

# 🧪 Print where the log file should be written
print(f"🧪 Expected log file path: {LOG_FILE}")

# Load previous log if exists
if LOG_FILE.exists():
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            conversion_log = json.load(f)
    except Exception as e:
        logging.error(f"❌ Failed to load conversion log: {e}")
        conversion_log = {}
else:
    conversion_log = {}

def save_log():
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(conversion_log, f, indent=4)
        logging.info(f"📄 Saved conversion log to: {LOG_FILE}")
    except Exception as e:
        logging.error(f"❌ Failed to write conversion log: {e}")

def get_audio_codec(file_path: Path) -> str:
    try:
        result = subprocess.run(
            [FFPROBE_PATH, "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_name", "-of", "json", str(file_path)],
            capture_output=True,
            text=True,
            check=True
        )
        info = json.loads(result.stdout)
        return info["streams"][0]["codec_name"]
    except Exception as e:
        logging.error(f"Error getting audio codec for {file_path}: {e}")
        return "unknown"

def convert_to_aac(input_file: Path, output_file: Path) -> bool:
    try:
        subprocess.run(
            [
                FFMPEG_PATH,
                "-i", str(input_file),
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "384k",
                str(output_file)
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"❌ Failed to convert {input_file.name}: {e}")
        return False

def process_mkv_files(source_folder: Path):
    mkv_files = [p for p in source_folder.rglob("*.mkv") if p.is_file() and not p.name.startswith("._")]
    if not mkv_files:
        print(f"📂 No MKV files found in {source_folder}")
        return

    print(f"🚀 Converting MKV files in: {source_folder} ({len(mkv_files)} files)")
    for input_file in tqdm(mkv_files, desc=f"Processing MKV - {source_folder.name}"):
        output_file = input_file.with_suffix(".mp4")
        if output_file.exists():
            codec = get_audio_codec(output_file)
            if codec == "aac":
                print(f"⚠️  Skipping (already .mp4 with AAC): {output_file.name}")
                continue
            else:
                print(f"🔁 Re-converting (bad audio codec: {codec}): {output_file.name}")

        if convert_to_aac(input_file, output_file):
            try:
                input_file.unlink()
            except Exception as e:
                logging.error(f"Failed to delete {input_file}: {e}")

def process_mp4_audio_fix(source_folder: Path):
    mp4_files = [p for p in source_folder.rglob("*.mp4") if p.is_file() and not p.name.startswith("._")]
    print(f"🔍 Checking .mp4 audio codecs in: {source_folder} ({len(mp4_files)} files)")

    for mp4_file in tqdm(mp4_files, desc=f"Scanning MP4 - {source_folder.name}"):
        file_key = str(mp4_file)

        # ✅ Skip if already logged as good
        if file_key in conversion_log and conversion_log[file_key].get("status") in {"converted", "skipped"}:
            continue

        codec = get_audio_codec(mp4_file)
        if codec == "aac":
            print(f"✅ Already AAC: {mp4_file.name}")
            conversion_log[file_key] = {
                "status": "skipped",
                "original_audio": "aac"
            }
            continue

        print(f"🔁 Converting to AAC: {mp4_file.name} (was: {codec})")
        temp_file = mp4_file.with_suffix(".temp.mp4")

        if convert_to_aac(mp4_file, temp_file):
            try:
                mp4_file.unlink()
                shutil.move(str(temp_file), str(mp4_file))
                conversion_log[file_key] = {
                    "status": "converted",
                    "original_audio": codec,
                    "converted_to": "aac"
                }
                logging.info(f"✅ Replaced {mp4_file.name} with AAC version")
            except Exception as e:
                logging.error(f"Error replacing file {mp4_file.name}: {e}")
                conversion_log[file_key] = {
                    "status": "error",
                    "original_audio": codec,
                    "error": str(e)
                }
        else:
            if temp_file.exists():
                temp_file.unlink()
            conversion_log[file_key] = {
                "status": "error",
                "original_audio": codec,
                "error": "conversion failed"
            }

        save_log()

def remove_empty_folders(folder: Path):
    for path in sorted(folder.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            try:
                path.rmdir()
                logging.info(f"Removed empty folder: {path}")
            except Exception as e:
                logging.error(f"Failed to remove folder: {path} - {e}")

def remove_dot_underscore_files(folder: Path):
    for p in folder.rglob("._*"):
        try:
            p.unlink()
            logging.info(f"🗑️  Deleted macOS metadata file: {p}")
        except Exception as e:
            logging.error(f"Failed to delete metadata file: {p} - {e}")

def print_summary():
    converted = skipped = failed = 0
    for entry in conversion_log.values():
        status = entry.get("status")
        if status == "converted":
            converted += 1
        elif status == "skipped":
            skipped += 1
        elif status == "error":
            failed += 1

    print("\n📊 Conversion Summary:")
    print(f"✅ Converted: {converted}")
    print(f"⏩ Skipped (already AAC): {skipped}")
    print(f"❌ Failed: {failed}")


if __name__ == "__main__":
    for folder in SOURCE_FOLDERS:
        process_mkv_files(folder)
        process_mp4_audio_fix(folder)
        remove_dot_underscore_files(folder)
        remove_empty_folders(folder)
    save_log()
    print_summary()

