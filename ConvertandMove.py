import re
import subprocess
import logging
from pathlib import Path
from tqdm import tqdm
import os
import json
import shutil
from typing import Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# Configuration
DRY_RUN = True
EXTRACT_SUBTITLES = False
MAX_WORKERS = 3
LOGGING_ENABLED = False
FFMPEG_PATH = r"C:\\Programs2\\ffmpeg\\ffmpeg_essentials_build\\bin\\ffmpeg.exe"
FFPROBE_PATH = r"C:\\Programs2\\ffmpeg\\ffmpeg_essentials_build\\bin\\ffprobe.exe"
LOG_FILE = Path("D:/Python/Logs/conversion_log.json")

SOURCE_MOVIES = Path("E:/Movies")
SOURCE_TV = Path("E:/TV Shows")
DEST_MOVIES = Path("Z:/Movies")
DEST_TV = Path("Z:/TV Shows")

# Filename cleanup terms
CLEANUP_TERMS = [
    "1080p", "720p", "BluRay", "x264", "YTS", "BRRip", "WEBRip", "WEB-DL",
    "HDRip", "DVDRip", "AAC", "5.1", "H264", "H265", "HEVC"
]

if LOGGING_ENABLED:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

conversion_log = {}

def save_log():
    if not LOGGING_ENABLED:
        return
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(conversion_log, f, indent=4)
    except Exception as e:
        logging.error(f"❌ Failed to write conversion log: {e}")

def get_audio_codec(file_path: Path) -> str:
    try:
        result = subprocess.run([
            FFPROBE_PATH, "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=codec_name", "-of", "json", str(file_path)
        ], capture_output=True, text=True, check=True)
        return json.loads(result.stdout)["streams"][0]["codec_name"]
    except Exception as e:
        if LOGGING_ENABLED:
            logging.warning(f"⚠️ Audio codec error: {e}")
        return "unknown"

def get_video_codec(file_path: Path) -> str:
    try:
        result = subprocess.run([
            FFPROBE_PATH, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name", "-of", "json", str(file_path)
        ], capture_output=True, text=True, check=True)
        return json.loads(result.stdout)["streams"][0]["codec_name"]
    except Exception as e:
        if LOGGING_ENABLED:
            logging.warning(f"⚠️ Video codec error: {e}")
        return "unknown"

def get_subtitle_indices(file_path: Path) -> Tuple[int, int, bool]:
    forced_idx = -1
    full_idx = -1
    fallback_forced = False
    try:
        result = subprocess.run([
            FFPROBE_PATH, "-v", "error", "-select_streams", "s",
            "-show_entries", "stream=index:stream_tags=language,title,forced:stream=codec_name", "-of", "json", str(file_path)
        ], capture_output=True, text=True, check=True)
        streams = json.loads(result.stdout).get("streams", [])
        for stream in streams:
            tags = stream.get("tags", {})
            codec = stream.get("codec_name", "")
            lang = tags.get("language", "").lower()
            title = tags.get("title", "").lower()
            is_forced = tags.get("forced") == "1"

            if codec in ["pgs", "hdmv_pgs_subtitle"]:
                continue

            if lang == "eng":
                if is_forced and forced_idx == -1:
                    forced_idx = stream["index"]
                elif "forced" in title and forced_idx == -1:
                    forced_idx = stream["index"]
                    fallback_forced = True
                elif full_idx == -1:
                    full_idx = stream["index"]
    except Exception as e:
        if LOGGING_ENABLED:
            logging.warning(f"⚠️ Subtitle parsing failed for {file_path.name}: {e}")
    return forced_idx, full_idx, fallback_forced

def clean_filename(file_path: Path) -> Path:
    name = file_path.stem
    for term in CLEANUP_TERMS:
        name = name.replace(term, "")
    cleaned_name = "_".join(name.split()).strip("_") + file_path.suffix
    cleaned_path = file_path.with_name(cleaned_name)
    if cleaned_path != file_path:
        try:
            file_path.rename(cleaned_path)
        except Exception as e:
            if LOGGING_ENABLED:
                logging.warning(f"⚠️ Could not rename {file_path.name} to {cleaned_path.name}: {e}")
    return cleaned_path

def convert_to_mp4(input_file: Path) -> bool:
    input_file = clean_filename(input_file)

    output_file = input_file.with_suffix(".mp4")
    if output_file.exists():
        print(f"⏭️ Already converted: {output_file.name}")
        return True

    video_codec = get_video_codec(input_file)
    audio_codec = get_audio_codec(input_file)
    forced_index, full_index, is_fallback = get_subtitle_indices(input_file)

    print(f"🎮 {input_file.name} → {output_file.name}")
    print(f"🎷 Audio: {'copy' if audio_codec == 'aac' else 'AAC re-encode'}")
    print(f"📝 Subtitles: {'burned-in fallback' if is_fallback else ('burned-in forced' if forced_index >= 0 else 'none')} + {'soft full CC' if full_index >= 0 else 'no CC'}")

    if DRY_RUN:
        return True

    temp_file = input_file.with_suffix(".temp.mp4")
    command = [FFMPEG_PATH, "-y", "-i", str(input_file)]
    if forced_index >= 0:
        input_ffmpeg_path = str(input_file).replace("\\", "/").replace(":", "\\:")
        subtitle_filter = f"subtitles='{input_ffmpeg_path}':si={forced_index}:force_style='FontName=Arial'"
        command += ["-vf", subtitle_filter, "-c:v", "libx264", "-crf", "23", "-preset", "veryfast"]
    else:
        command += ["-c:v", "copy"] if video_codec == "h264" else ["-c:v", "libx264", "-crf", "23", "-preset", "veryfast"]

    command += ["-c:a", "copy"] if audio_codec == "aac" else ["-c:a", "aac", "-b:a", "384k"]
    command += ["-map", "0:v:0", "-map", "0:a:0"]
    if full_index >= 0 and full_index != forced_index:
        command += ["-map", f"0:s:{full_index}", "-scodec:s", "mov_text"]
    command.append(str(temp_file))

    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.move(str(temp_file), str(output_file))
        input_file.unlink()
        return True
    except Exception as e:
        if LOGGING_ENABLED:
            logging.error(f"❌ FFmpeg failed: {e}")
        if temp_file.exists():
            temp_file.unlink()
        return False

def move_file(src, dest):
    if DRY_RUN:
        print(f"🧪 DRY-RUN MOVE: {src} → {dest}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))

def flatten_and_clean_movies():
    for mp4_file in SOURCE_MOVIES.rglob("*.mp4"):
        dest_file = DEST_MOVIES / mp4_file.name
        move_file(mp4_file, dest_file)

    for dirpath, _, _ in os.walk(SOURCE_MOVIES, topdown=False):
        if not os.listdir(dirpath):
            try:
                if not DRY_RUN:
                    os.rmdir(dirpath)
                print(f"🧹 Removed empty folder: {dirpath}")
            except Exception:
                pass

def preserve_structure_tv():
    for mp4_file in SOURCE_TV.rglob("*.mp4"):
        rel_path = mp4_file.relative_to(SOURCE_TV)
        dest_path = DEST_TV / rel_path
        move_file(mp4_file, dest_path)

def convert_all():
    all_files = list(SOURCE_MOVIES.rglob("*.mkv")) + list(SOURCE_TV.rglob("*.mkv"))
    print(f"🎞️ Found {len(all_files)} MKV files to convert.")
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(convert_to_mp4, f): f for f in all_files}
        for future in tqdm(as_completed(futures), total=len(futures), desc="Converting", dynamic_ncols=True):
            f = futures[future]
            success = future.result()
            if LOGGING_ENABLED:
                conversion_log[str(f)] = "converted" if success else "error"
            results.append(success)
            save_log()
    print(f"📊 Converted: {results.count(True)} | ❌ Failed: {results.count(False)}")

def main():
    convert_all()
    flatten_and_clean_movies()
    preserve_structure_tv()

if __name__ == "__main__":
    main()
