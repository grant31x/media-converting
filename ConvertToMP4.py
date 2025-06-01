import os
import subprocess
import json
from pathlib import Path
from tqdm import tqdm
import logging
from datetime import datetime

# Configuration
FFMPEG_PATH = r"C:\Programs2\ffmpeg\ffmpeg_essentials_build\bin\ffmpeg.exe"
VIDEO_FOLDERS = [Path("Z:/Movies"), Path("Z:/TV Shows"), Path("I:/Movies")]
SUPPORTED_EXTS = ['.mp4', '.mkv']
CONVERSION_LOG = Path("D:/Python/conversion_log.json")
LOG_FILE = Path("D:/Python/convert_to_mp4.log")

# Logging (file log has no emojis)
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Load or initialize conversion log
if CONVERSION_LOG.exists():
    with open(CONVERSION_LOG, 'r') as f:
        converted = json.load(f)
else:
    converted = {}

def save_log():
    with open(CONVERSION_LOG, 'w') as f:
        json.dump(converted, f, indent=4)

def get_audio_codec(file_path):
    try:
        result = subprocess.run(
            [FFMPEG_PATH, "-i", str(file_path)],
            stderr=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            text=True
        )
        lines = result.stderr.splitlines()
        for line in lines:
            if "Audio:" in line:
                return line.split("Audio:")[1].split(",")[0].strip()
    except Exception as e:
        logging.error(f"Failed to detect audio codec for {file_path}: {e}")
    return "unknown"

def convert_audio_only(input_file, output_file):
    command = [
        FFMPEG_PATH,
        "-i", str(input_file),
        "-c:v", "copy",
        "-c:a", "aac",
        "-strict", "experimental",
        str(output_file)
    ]
    return run_ffmpeg(command, input_file)

def convert_full(input_file, output_file):
    command = [
        FFMPEG_PATH,
        "-i", str(input_file),
        "-c:v", "libx264",
        "-crf", "18",
        "-preset", "slow",
        "-c:a", "aac",
        str(output_file)
    ]
    return run_ffmpeg(command, input_file)

def run_ffmpeg(command, input_file):
    try:
        subprocess.run(command, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to convert: {input_file}")
        logging.error(f"Conversion failed for {input_file}: {e}")
        return False

def process_file(file_path):
    if not file_path.exists() or not file_path.is_file():
        print(f"⚠️  Skipping missing or invalid file: {file_path}")
        return "skipped"

    if str(file_path) in converted:
        return "skipped"

    ext = file_path.suffix.lower()
    output_path = file_path.with_suffix(".mp4")
    temp_path = file_path.parent / f"temp_{file_path.stem}.mp4"

    if ext == '.mkv':
        print(f"🎬 Converting MKV to MP4: {file_path.name}")
        success = convert_full(file_path, temp_path)
    elif ext == '.mp4':
        audio_codec = get_audio_codec(file_path)
        if "aac" in audio_codec:
            return "skipped"
        print(f"🔁 Converting audio in MP4: {file_path.name}")
        success = convert_audio_only(file_path, temp_path)
    else:
        return "skipped"

    if success:
        temp_path.replace(output_path)
        converted[str(file_path)] = datetime.now().isoformat()
        logging.info(f"Converted: {file_path}")
        return "converted"
    else:
        return "failed"

def main():
    all_files = []
    for folder in VIDEO_FOLDERS:
        if not folder.exists():
            continue
        for file in folder.rglob("*"):
            if file.suffix.lower() in SUPPORTED_EXTS:
                all_files.append(file)

    converted_count = skipped_count = failed_count = 0

    for file_path in tqdm(all_files, desc="🔍 Converting Files"):
        result = process_file(file_path)
        if result == "converted":
            converted_count += 1
        elif result == "skipped":
            skipped_count += 1
        elif result == "failed":
            failed_count += 1

    save_log()

    print("\n✅ Summary:")
    print(f"• Converted: {converted_count}")
    print(f"• Skipped: {skipped_count}")
    print(f"• Failed: {failed_count}")

if __name__ == "__main__":
    main()