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

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Configuration
DRY_RUN = False
EXTRACT_SUBTITLES = False
MAX_WORKERS = 3
FFMPEG_PATH = r"C:\\Programs2\\ffmpeg\\ffmpeg_essentials_build\\bin\\ffmpeg.exe"
FFPROBE_PATH = r"C:\\Programs2\\ffmpeg\\ffmpeg_essentials_build\\bin\\ffprobe.exe"
DEFAULT_SOURCE_FOLDERS = [Path(r"E:\\Movies_downloaded")]
LOG_FILE = Path("D:/Python/Logs/conversion_log.json")

print(f"📄 Log file: {LOG_FILE}")

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
        logging.info(f"✅ Saved conversion log to: {LOG_FILE}")
    except Exception as e:
        logging.error(f"❌ Failed to write conversion log: {e}")

def get_audio_codec(file_path: Path) -> str:
    try:
        result = subprocess.run([
            FFPROBE_PATH, "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=codec_name", "-of", "json", str(file_path)
        ], capture_output=True, text=True, check=True)
        info = json.loads(result.stdout)
        return info["streams"][0]["codec_name"]
    except Exception as e:
        logging.error(f"Error getting audio codec for {file_path}: {e}")
        return "unknown"

def get_video_codec(file_path: Path) -> str:
    try:
        result = subprocess.run([
            FFPROBE_PATH, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name", "-of", "json", str(file_path)
        ], capture_output=True, text=True, check=True)
        info = json.loads(result.stdout)
        return info["streams"][0]["codec_name"]
    except Exception as e:
        logging.error(f"Error getting video codec for {file_path}: {e}")
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
            lang = tags.get("language", "")
            title = tags.get("title", "").lower()
            is_forced = tags.get("forced") == "1"
            if lang == "eng" and codec != "pgs":
                if is_forced and forced_idx == -1:
                    forced_idx = stream["index"]
                elif "forced" in title and forced_idx == -1:
                    forced_idx = stream["index"]
                    fallback_forced = True
                elif full_idx == -1:
                    full_idx = stream["index"]
    except Exception as e:
        logging.warning(f"⚠️ Failed to find subtitle streams for {file_path.name}: {e}")
    return forced_idx, full_idx, fallback_forced

def is_valid_media(file_path: Path) -> bool:
    try:
        subprocess.run([
            FFPROBE_PATH, "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False

def convert_to_aac(input_file: Path, output_file: Path, extract_subs: bool = False) -> bool:
    if not is_valid_media(input_file):
        logging.error(f"🚫 Invalid media file: {input_file}")
        return False

    video_codec = get_video_codec(input_file)
    audio_codec = get_audio_codec(input_file)
    forced_index, full_index, is_fallback = get_subtitle_indices(input_file)

    print(f"🎮 {input_file.name} → {output_file.name}")
    print(f"🎷 Audio: {'copy' if audio_codec == 'aac' else 're-encode to AAC'}")
    print(f"📝 Subtitles: {'burned-in fallback' if is_fallback else ('burned-in forced' if forced_index >= 0 else 'none')} + {'soft full CC' if full_index >= 0 else 'no CC'}")

    if DRY_RUN:
        print("🧪 Dry run mode. Skipping conversion.")
        return True

    temp_file = input_file.with_suffix(".temp.mp4")
    command = [FFMPEG_PATH, "-y", "-i", str(input_file)]
    map_args = ["-map", "0:v:0"]

    if forced_index >= 0:
        # Correct escaping for FFmpeg: use forward slashes and escape the colon in the drive letter
        input_path_ffmpeg = str(input_file).replace("\\", "/")
        if ":" in input_path_ffmpeg:
            input_path_ffmpeg = input_path_ffmpeg.replace(":", "\\:")
        subtitle_filter = f"subtitles='{input_path_ffmpeg}':si={forced_index}:force_style='FontName=Arial'"
        print(f"🧪 Subtitle filter: {subtitle_filter}")

        command += ["-vf", subtitle_filter]
        command += ["-c:v", "libx264", "-crf", "23", "-preset", "veryfast"]
    else:
        if video_codec == "h264":
            command += ["-c:v", "copy"]
        else:
            command += ["-c:v", "libx264", "-crf", "23", "-preset", "veryfast"]

    if audio_codec == "aac":
        command += ["-c:a", "copy"]
    else:
        command += ["-c:a", "aac", "-b:a", "384k"]

    map_args += ["-map", "0:a:0"]

    if full_index >= 0 and full_index != forced_index:
        map_args += ["-map", f"0:s:{full_index}"]
        command += ["-scodec:s", "mov_text"]

    command += map_args
    command.append(str(temp_file))

    try:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        shutil.move(str(temp_file), str(output_file))
        input_file.unlink()
        logging.info(f"✅ Finished and deleted: {input_file.name}")
        return True

    except subprocess.CalledProcessError as e:
        logging.error(f"❌ FFmpeg failed: {e}\n\nCommand: {' '.join(command)}\n\nStderr: {e.stderr.decode(errors='ignore') if e.stderr else 'N/A'}")
        if temp_file.exists():
            temp_file.unlink()
        return False

def convert_wrapper(mkv_file: Path) -> Tuple[Path, bool]:
    output_file = mkv_file.with_suffix(".mp4")
    success = convert_to_aac(mkv_file, output_file, extract_subs=EXTRACT_SUBTITLES)
    return mkv_file, success

def main():
    folders = DEFAULT_SOURCE_FOLDERS
    for folder in folders:
        mkv_files = list(folder.rglob("*.mkv"))
        print(f"🚀 Converting MKV files in: {folder} ({len(mkv_files)} files)")

        start = datetime.now()
        results = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(convert_wrapper, mkv): mkv for mkv in mkv_files}
            for i, future in enumerate(tqdm(as_completed(futures), total=len(futures), desc=f"Processing MKV Files - {folder.name}", dynamic_ncols=True)):
                mkv_file, success = future.result()
                conversion_log[str(mkv_file)] = "converted" if success else "error"
                results.append((mkv_file, success))
                save_log()

        elapsed = datetime.now() - start
        print(f"⏱️ All conversions completed in {elapsed}")

if __name__ == "__main__":
    main()