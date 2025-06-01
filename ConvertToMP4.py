import subprocess
import logging
from pathlib import Path
from tqdm import tqdm
import json
import shutil
from uuid import uuid4
from concurrent.futures import ProcessPoolExecutor
import argparse
import sys

# Global CLI options (populated via argparse)
ARGS = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("conversion_debug.log", encoding="utf-8"),
        logging.StreamHandler(stream=open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1))
    ]
)

LOG_FILE = Path("D:/Python/conversion_log.json")
conversion_log = {}

DEFAULT_FOLDERS = [Path(r"Z:/Movies"), Path(r"Z:/TV Shows"), Path(r"I:/Movies")]
DEFAULT_FFMPEG = Path(r"C:/Programs2/ffmpeg/ffmpeg_essentials_build/bin/ffmpeg.exe")
DEFAULT_FFPROBE = Path(r"C:/Programs2/ffmpeg/ffmpeg_essentials_build/bin/ffprobe.exe")

def notify(msg: str, important: bool = True):
    if ARGS.verbose or important:
        tqdm.write(msg)

def save_log():
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(conversion_log, f, indent=4)
        notify(f"📄 Saved conversion log to: {LOG_FILE}")
        logging.info(f"Saved conversion log to: {LOG_FILE}")
    except Exception as e:
        logging.error(f"Failed to write conversion log: {e}")

def load_log():
    global conversion_log
    if LOG_FILE.exists():
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                conversion_log = json.load(f)
        except Exception as e:
            logging.error(f"Failed to load conversion log: {e}")
            conversion_log = {}
    else:
        conversion_log = {}

def get_codec(file_path: Path, ffprobe_path: Path, stream_type: str = "a") -> str:
    try:
        result = subprocess.run(
            [str(ffprobe_path), "-v", "error", f"-select_streams", f"{stream_type}:0",
             "-show_entries", "stream=codec_name", "-of", "json", str(file_path)],
            capture_output=True,
            text=True,
            check=True
        )
        info = json.loads(result.stdout)
        return info["streams"][0]["codec_name"]
    except Exception as e:
        logging.error(f"Error getting {stream_type} codec for {file_path}: {e}")
        return "unknown"

def transcode_to_aac(input_file: Path, output_file: Path, ffmpeg_path: Path) -> tuple[Path, bool, str]:
    cmd = [
        str(ffmpeg_path),
        "-i", str(input_file),
        "-c:v", ARGS.video_codec,
        "-preset", "medium",
        "-crf", "23",
        "-c:a", ARGS.audio_codec,
        "-b:a", ARGS.audio_bitrate,
        str(output_file)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    success = result.returncode == 0
    return output_file, success, result.stderr if not success else ""

def find_files_to_convert(folder: Path, ffprobe_path: Path):
    to_convert = []
    for file in folder.rglob("*"):
        if file.suffix.lower() not in [".mkv", ".mp4"] or file.name.startswith("._") or not file.is_file():
            continue
        file_key = str(file)
        if file_key in conversion_log and conversion_log[file_key].get("status") in {"converted", "skipped"}:
            continue

        audio_codec = get_codec(file, ffprobe_path, "a")
        video_codec = get_codec(file, ffprobe_path, "v")
        output_file = file.with_suffix(".mp4")

        if file.suffix.lower() == ".mkv":
            to_convert.append((file, output_file))  # Always convert mkv to mp4
        elif file.suffix.lower() == ".mp4":
            if audio_codec != ARGS.audio_codec or video_codec not in ["hevc", "h264"]:
                to_convert.append((file, file))  # In-place fix

    return to_convert

def convert_worker(task):
    input_file, output_file = task
    file_key = str(output_file)
    conversion_log[file_key] = {"status": "converting"}
    output_file, success, error_msg = transcode_to_aac(input_file, output_file, ARGS.ffmpeg)
    if success and output_file.exists() and output_file.stat().st_size > 0:
        if input_file.suffix.lower() == ".mkv":
            try:
                input_file.unlink()
            except Exception as e:
                logging.error(f"Delete fail: {input_file} - {e}")
        conversion_log[file_key] = {
            "status": "converted",
            "converted_to": ARGS.audio_codec
        }
    else:
        conversion_log[file_key] = {
            "status": "error",
            "error": error_msg or "Conversion failed"
        }
    return output_file.name, success

def flatten_folder(root_folder: Path):
    for file in root_folder.rglob("*"):
        if file.is_file() and file.suffix.lower() in {".mp4", ".mkv"} and file.parent != root_folder:
            new_path = root_folder / f"{file.stem}_{uuid4().hex[:6]}{file.suffix}"
            shutil.move(str(file), str(new_path))
            tqdm.write(f"📁 Moved {file} to {new_path}")
            logging.info(f"Moved {file} to {new_path}")

def remove_empty_folders(folder: Path):
    for path in sorted(folder.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            try:
                path.rmdir()
                logging.info(f"Removed empty folder: {path}")
            except Exception as e:
                logging.error(f"Failed to remove folder: {path} - {e}")

def prompt_user_confirmation(tasks):
    if not tasks:
        print("✅ No files need conversion.")
        return False
    print(f"🔎 {len(tasks)} file(s) need conversion:")
    for src, dst in tasks:
        print(f" - {src} → {dst}")
    response = input("Proceed with conversion? [y/N]: ").strip().lower()
    return response == "y"

def parse_args():
    parser = argparse.ArgumentParser(description="Convert video files to AAC audio format.")
    parser.add_argument("--folders", nargs="+", type=Path, default=DEFAULT_FOLDERS, help="Source folders to scan")
    parser.add_argument("--ffmpeg", type=Path, default=DEFAULT_FFMPEG, help="Path to ffmpeg.exe")
    parser.add_argument("--ffprobe", type=Path, default=DEFAULT_FFPROBE, help="Path to ffprobe.exe")
    parser.add_argument("--audio-bitrate", default="384k", help="Bitrate for AAC audio")
    parser.add_argument("--audio-codec", default="aac", help="Audio codec")
    parser.add_argument("--video-codec", default="libx264", help="Video codec")
    parser.add_argument("--workers", type=int, default=1, help="Number of parallel workers")
    parser.add_argument("--verbose", action="store_true", help="Show verbose output")
    parser.add_argument("--flatten", action="store_true", help="Flatten folders")
    parser.add_argument("--dry-run", action="store_true", help="Preview and confirm before conversion")
    return parser.parse_args()

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
    print(f"⏩ Skipped: {skipped}")
    print(f"❌ Failed: {failed}")

def main():
    global ARGS
    ARGS = parse_args()

    if not ARGS.ffmpeg.exists() or not ARGS.ffprobe.exists():
        print("❌ FFmpeg or FFprobe path is invalid.")
        sys.exit(1)

    load_log()
    all_tasks = []

    for folder in ARGS.folders:
        if not folder.exists():
            notify(f"⏭️ Skipping missing folder: {folder}")
            continue
        notify(f"📂 Scanning {folder}")
        all_tasks.extend(find_files_to_convert(folder, ARGS.ffprobe))

    if ARGS.dry_run:
        if not prompt_user_confirmation(all_tasks):
            print("🚫 Conversion cancelled.")
            return

    for i, task in enumerate(all_tasks, 1):
        name, _ = task
        notify(f"🔁 Starting conversion: {name.name}")
        name, success = convert_worker(task)
        notify(f"{'✅' if success else '❌'} Finished: {name} ({i}/{len(all_tasks)})")

    if ARGS.flatten:
        for folder in ARGS.folders:
            if "movies" in str(folder).lower():
                flatten_folder(folder)
                remove_empty_folders(folder)

    save_log()
    print_summary()

if __name__ == "__main__":
    main()