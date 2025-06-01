import os
import subprocess
import json
from pathlib import Path
from tqdm import tqdm
import logging
from datetime import datetime
import re

# Configuration
FFMPEG_PATH = r"C:\Programs2\ffmpeg\ffmpeg_essentials_build\bin\ffmpeg.exe"
VIDEO_FOLDERS = [Path("Z:/Movies"), Path("Z:/TV Shows"), Path("I:/Movies")]
CLEANUP_FOLDERS = [Path("Z:/Movies"), Path("I:/Movies")]
SUPPORTED_EXTS = ['.mp4', '.mkv']
CONVERSION_LOG = Path("D:/Python/conversion_log.json")
LOG_FILE = Path("D:/Python/convert_to_mp4.log")
UNWANTED_TERMS = [
    'x264', 'x265', '1080p', '720p', 'WEBRip', 'BluRay', 'YTS', 'AAC5.1',
    'H264', 'H265', 'BRRip', 'HDRip', 'EXTENDED', 'REMASTERED', 'UNRATED'
]
dry_run = True

# Logging
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

def clean_filename(file_path):
    original_name = file_path.name
    cleaned_name = original_name
    for term in UNWANTED_TERMS:
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        cleaned_name = pattern.sub('', cleaned_name)
    cleaned_name = re.sub(r'\s{2,}', ' ', cleaned_name).strip().replace(' .', '.')
    if cleaned_name != original_name:
        new_path = file_path.with_name(cleaned_name)
        if not dry_run:
            file_path.rename(new_path)
        return new_path
    return file_path

def get_codecs(file_path):
    try:
        result = subprocess.run(
            [FFMPEG_PATH, "-i", str(file_path)],
            stderr=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            text=True
        )
        stderr = result.stderr.lower()
        video_codec = audio_codec = "unknown"
        for line in stderr.splitlines():
            if "video:" in line and video_codec == "unknown":
                video_codec = line.split("video:")[1].split(",")[0].strip()
            if "audio:" in line and audio_codec == "unknown":
                audio_codec = line.split("audio:")[1].split(",")[0].strip()
        return video_codec, audio_codec
    except Exception as e:
        logging.error(f"Codec detection failed for {file_path}: {e}")
        return "unknown", "unknown"

def convert_remux(input_file, output_file):
    command = [FFMPEG_PATH, "-i", str(input_file), "-c", "copy", str(output_file)]
    return run_ffmpeg(command, input_file)

def convert_audio_only(input_file, output_file):
    command = [FFMPEG_PATH, "-i", str(input_file), "-c:v", "copy", "-c:a", "aac", "-strict", "experimental", str(output_file)]
    return run_ffmpeg(command, input_file)

def convert_full(input_file, output_file):
    command = [FFMPEG_PATH, "-i", str(input_file), "-c:v", "libx264", "-crf", "18", "-preset", "slow", "-c:a", "aac", str(output_file)]
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
        print(f"⚠️ Skipping missing or invalid file: {file_path}")
        return "skipped"

    cleaned_path = clean_filename(file_path)
    if str(cleaned_path) in converted:
        return "skipped"

    ext = cleaned_path.suffix.lower()
    output_path = cleaned_path.with_suffix(".mp4")
    temp_path = cleaned_path.parent / f"temp_{cleaned_path.stem}.mp4"
    video_codec, audio_codec = get_codecs(cleaned_path)

    if dry_run:
        if ext == '.mkv':
            if "h264" in video_codec and "aac" in audio_codec:
                print(f"📼 [Dry Run] Would remux to MP4: {cleaned_path.name}")
            else:
                print(f"🎬 [Dry Run] Would convert MKV: {cleaned_path.name} (Video: {video_codec}, Audio: {audio_codec})")
        elif ext == '.mp4':
            if "aac" in audio_codec:
                print(f"⏩ [Dry Run] Skipping (AAC): {cleaned_path.name}")
                return "skipped"
            print(f"🔁 [Dry Run] Would fix audio in MP4: {cleaned_path.name} (Audio: {audio_codec} → aac)")
        return "dry_run"

    if ext == '.mkv':
        if "h264" in video_codec and "aac" in audio_codec:
            print(f"📼 Remuxing to MP4: {cleaned_path.name}")
            success = convert_remux(cleaned_path, temp_path)
        else:
            print(f"🎬 Converting MKV: {cleaned_path.name}")
            success = convert_full(cleaned_path, temp_path)
    elif ext == '.mp4':
        if "aac" in audio_codec:
            return "skipped"
        print(f"🔁 Fixing audio in MP4: {cleaned_path.name}")
        success = convert_audio_only(cleaned_path, temp_path)
    else:
        return "skipped"

    if success:
        temp_path.replace(output_path)
        converted[str(cleaned_path)] = datetime.now().isoformat()
        logging.info(f"Converted: {cleaned_path}")
        return "converted"
    else:
        return "failed"

def delete_empty_folders():
    for folder in CLEANUP_FOLDERS:
        for root, dirs, files in os.walk(folder, topdown=False):
            if not dirs and not files:
                try:
                    os.rmdir(root)
                    print(f"🗑️ Deleted empty folder: {root}")
                    logging.info(f"Deleted empty folder: {root}")
                except Exception as e:
                    logging.error(f"Failed to delete folder {root}: {e}")

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
    delete_empty_folders()

    print("\n✅ Summary:")
    print(f"• Converted: {converted_count}")
    print(f"• Skipped: {skipped_count}")
    print(f"• Failed: {failed_count}")

if __name__ == "__main__":
    main()