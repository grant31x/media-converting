import re
import subprocess
import logging
from pathlib import Path
from tqdm import tqdm
import os
import json
import shutil
import argparse
from typing import Tuple, List

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Configuration
DRY_RUN = True  # If True, simulate actions without modifying files
EXTRACT_SUBTITLES = False  # Default toggle for extracting .srt subtitles
FFMPEG_PATH = r"C:\\Programs2\\ffmpeg\\ffmpeg_essentials_build\\bin\\ffmpeg.exe"
FFPROBE_PATH = r"C:\\Programs2\\ffmpeg\\ffmpeg_essentials_build\\bin\\ffprobe.exe"
DEFAULT_SOURCE_FOLDERS = [Path(r"Z:\\Movies"), Path(r"Z:\\TV Shows")]
LOG_FILE = Path("D:/Python/Logs/conversion_log.json")

print(f"\U0001f9ea Expected log file path: {LOG_FILE}")

def clean_media_name(name: str) -> str:
    name = re.sub(r"\.(mp4|mkv|avi|wmv|flv|mov|srt|sub)$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\b(\d{3,4}p|4K|8K|BluRay|WEBRip|ELiTE|HDRip|HEVC|x264|AAC5|Asiimov|DDP5|10Bit|YIFY|1080p.BrRip.x|REPACK|BONE|RARBG|YTS)\b", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[\[\(].*?[\]\)]", "", name)
    name = re.sub(r"[_\-.,]+", " ", name)
    return name.strip()

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

def analyze_subtitles(file_path: Path) -> Tuple[bool, List[str]]:
    try:
        result = subprocess.run(
            [FFPROBE_PATH, "-v", "error", "-select_streams", "s", "-show_entries", "stream=index,codec_name", "-of", "json", str(file_path)],
            capture_output=True, text=True, check=True
        )
        streams = json.loads(result.stdout).get("streams", [])
        codecs = [s.get("codec_name", "") for s in streams]
        compatible = any(c in {"mov_text", "subrip", "tx3g"} for c in codecs)
        return compatible, codecs
    except Exception as e:
        logging.warning(f"⚠️ Failed to probe subtitles for {file_path}: {e}")
        return False, []

def extract_srt_subtitles(input_file: Path):
    try:
        result = subprocess.run(
            [FFPROBE_PATH, "-v", "error", "-select_streams", "s", "-show_entries", "stream=index,codec_name", "-of", "json", str(input_file)],
            capture_output=True, text=True, check=True
        )
        streams = json.loads(result.stdout).get("streams", [])
        for stream in streams:
            codec = stream.get("codec_name", "")
            index = stream.get("index")
            if codec in {"subrip", "mov_text"}:
                srt_file = input_file.with_suffix(".srt")
                cmd = [FFMPEG_PATH, "-i", str(input_file), "-map", f"0:s:{index}", srt_file.name]
                subprocess.run(cmd, check=True, cwd=str(input_file.parent))
                logging.info(f"📝 Extracted subtitle to: {srt_file}")
    except Exception as e:
        logging.warning(f"⚠️ Failed to extract subtitle from {input_file.name}: {e}")

def convert_to_aac(input_file: Path, output_file: Path, extract_subs: bool = False) -> bool:
    subtitle_supported, subtitle_codecs = analyze_subtitles(input_file)
    command = [
        FFMPEG_PATH, "-i", str(input_file), "-map", "0",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "384k"
    ]
    if subtitle_supported:
        command += ["-c:s", "copy"]
    else:
        command += ["-sn"]
    command.append(str(output_file))

    if not subtitle_supported and subtitle_codecs:
        logging.warning(f"⚠️ {input_file.name} has incompatible subtitles: {', '.join(subtitle_codecs)}")

    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if extract_subs:
            extract_srt_subtitles(input_file)
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"❌ Failed to convert {input_file.name}: {e}")
        return False

def process_mkv_files(source_folder: Path, extract_subs: bool):
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
        if convert_to_aac(input_file, output_file, extract_subs):
            try:
                input_file.unlink()
            except Exception as e:
                logging.error(f"Failed to delete {input_file}: {e}")

def process_mp4_audio_fix(source_folder: Path, extract_subs: bool):
    mp4_files = [p for p in source_folder.rglob("*.mp4") if p.is_file() and not p.name.startswith("._")]
    print(f"🔍 Checking .mp4 audio codecs in: {source_folder} ({len(mp4_files)} files)")
    for mp4_file in tqdm(mp4_files, desc=f"Scanning MP4 - {source_folder.name}"):
        file_key = str(mp4_file)
        if file_key in conversion_log and conversion_log[file_key].get("status") in {"converted", "skipped"}:
            continue
        codec = get_audio_codec(mp4_file)
        subtitle_supported, subtitle_codecs = analyze_subtitles(mp4_file)
        subtitle_status = "included" if subtitle_supported else f"skipped ({', '.join(subtitle_codecs)})"
        if codec == "aac":
            if not DRY_RUN:
                print(f"✅ Already AAC: {mp4_file.name}")
            conversion_log[file_key] = {"status": "skipped", "original_audio": "aac", "subtitles": subtitle_status}
            continue
        print(f"🔁 Converting to AAC: {mp4_file.name} (was: {codec})")
        temp_file = mp4_file.with_suffix(".temp.mp4")
        if convert_to_aac(mp4_file, temp_file, extract_subs):
            try:
                mp4_file.unlink()
                shutil.move(str(temp_file), str(mp4_file))
                conversion_log[file_key] = {
                    "status": "converted", "original_audio": codec, "converted_to": "aac", "subtitles": subtitle_status
                }
                logging.info(f"✅ Replaced {mp4_file.name} with AAC version")
            except Exception as e:
                logging.error(f"Error replacing file {mp4_file.name}: {e}")
        else:
            if temp_file.exists():
                temp_file.unlink()
            conversion_log[file_key] = {
                "status": "error", "original_audio": codec, "error": "conversion failed", "subtitles": subtitle_status
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
    print("📊 Conversion Summary:")
    print(f"✅ Converted: {converted}")
    print(f"⏩ Skipped (already AAC): {skipped}")
    print(f"❌ Failed: {failed}")
    conversion_log["__status__"] = "completed"
    save_log()

def rename_and_folderize(mp4_path: Path, srt_path: Path = None) -> Path:
    new_name = clean_media_name(mp4_path.stem) + mp4_path.suffix
    new_mp4_path = mp4_path.with_name(new_name)
    if not DRY_RUN:
        mp4_path.rename(new_mp4_path)
    if EXTRACT_SUBTITLES and srt_path and not DRY_RUN:
        new_srt_path = srt_path.with_name(clean_media_name(mp4_path.stem) + ".srt")
        srt_path.rename(new_srt_path)
        folder = new_mp4_path.with_suffix("")
        folder.mkdir(exist_ok=True)
        shutil.move(str(new_mp4_path), str(folder / new_mp4_path.name))
        shutil.move(str(new_srt_path), str(folder / new_srt_path.name))
        return folder / new_mp4_path.name
    return new_mp4_path

def is_log_complete():
    return conversion_log.get("__status__") == "completed"

def parse_args():
    parser = argparse.ArgumentParser(description="Convert videos to AAC and detect compatible subtitles.")
    parser.add_argument("--folders", nargs="+", help="Folders to process. If none, uses defaults.")
    parser.add_argument("--extract-subs", action="store_true", help="Extract compatible subtitles to .srt files")
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()
    if args.extract_subs:
        EXTRACT_SUBTITLES = True
    if is_log_complete():
        print("✅ Conversion already marked as completed. Exiting.")
        exit(0)

    folders = [Path(f) for f in args.folders] if args.folders else DEFAULT_SOURCE_FOLDERS
    for folder in folders:
        process_mkv_files(folder, extract_subs=EXTRACT_SUBTITLES)
        process_mp4_audio_fix(folder, extract_subs=EXTRACT_SUBTITLES)
        remove_dot_underscore_files(folder)
        remove_empty_folders(folder)
    save_log()
    print_summary()
