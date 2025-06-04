import os
import subprocess
import logging
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from collections import defaultdict

# Configuration
FFMPEG_PATH = r"C:\\Programs2\\ffmpeg\\ffmpeg_essentials_build\\bin\\ffmpeg.exe"
BASE_FOLDERS = [Path(r"Z:\\Movies"), Path(r"Z:\\TV Shows"), Path(r"I:\\Movies")]
VALID_EXTENSIONS = [".mp4", ".mkv"]
TARGET_AUDIO_CODEC = "aac"
TARGET_VIDEO_CODEC = "h264"
DRY_RUN = False  # Set to True for dry-run mode

# Resume support log
STATE_LOG = Path("conversion_state.json")
PROCESSED_FILES = set()
if STATE_LOG.exists():
    try:
        with open(STATE_LOG, "r") as f:
            PROCESSED_FILES = set(json.load(f))
    except Exception:
        PROCESSED_FILES = set()

# Logging
LOG_FILE = Path("conversion_log.txt")
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# Filename cleanup terms
CLEANUP_TERMS = [
    "1080p", "720p", "BluRay", "x264", "YTS", "BRRip", "WEBRip", "WEB-DL",
    "HDRip", "DVDRip", "AAC", "5.1", "H264", "H265", "HEVC"
]

def clean_filename(file_path):
    name = file_path.stem
    for term in CLEANUP_TERMS:
        name = name.replace(term, "")
    cleaned_name = "_".join(name.split()).strip("_") + file_path.suffix
    cleaned_path = file_path.with_name(cleaned_name)
    if cleaned_path != file_path:
        try:
            file_path.rename(cleaned_path)
        except Exception as e:
            logging.warning(f"Could not rename {file_path.name} to {cleaned_path.name}: {e}")
    return cleaned_path

def get_codecs(file_path):
    try:
        ffprobe_path = FFMPEG_PATH.replace("ffmpeg.exe", "ffprobe.exe")
        video_result = subprocess.run(
            [ffprobe_path, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name", "-of", "default=noprint_wrappers=1:nokey=1",
             str(file_path)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        video_codec = video_result.stdout.strip() or "unknown"

        audio_result = subprocess.run(
            [ffprobe_path, "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_name", "-of", "default=noprint_wrappers=1:nokey=1",
             str(file_path)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        audio_codec = audio_result.stdout.strip() or "unknown"

        return video_codec, audio_codec
    except Exception as e:
        logging.error(f"ffprobe codec detection failed for {file_path}: {e}")
        return "unknown", "unknown"

def convert_file(file_path):
    new_file = file_path.with_suffix(".mp4")
    temp_file = new_file.with_name(file_path.stem + "_convert.mp4")
    command = [
        FFMPEG_PATH,
        "-i", str(file_path),
        "-map", "0",
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "18",
        "-c:a", "aac",
        "-b:a", "192k",
        "-c:s", "copy",
        str(temp_file)
    ]
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if temp_file.exists() and temp_file.stat().st_size > 1_000_000:
            file_path.unlink()
            temp_file.rename(file_path)
            logging.info(f"✅ Replaced {file_path.name} with converted MP4")
            return "converted"
        else:
            logging.error(f"⚠️ Conversion output invalid or too small for {file_path.name}")
            return "failed"
    except subprocess.CalledProcessError as e:
        logging.error(f"❌ Failed to convert {file_path.name}: {e}")
        return "failed"

def fix_audio(file_path):
    temp_file = file_path.with_name(file_path.stem + "_audiofix" + file_path.suffix)
    command = [
        FFMPEG_PATH,
        "-i", str(file_path),
        "-map", "0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-c:s", "copy",
        str(temp_file)
    ]
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if temp_file.exists() and temp_file.stat().st_size > 1_000_000:
            file_path.unlink()
            temp_file.rename(file_path)
            logging.info(f"✅ Replaced {file_path.name} with AAC audio version")
            return "audio-fixed"
        else:
            logging.error(f"⚠️ Audio fix output invalid or too small for {file_path.name}")
            return "failed"
    except subprocess.CalledProcessError as e:
        logging.error(f"❌ Failed to fix audio in {file_path.name}: {e}")
        return "failed"

def process_file(file_path):
    if not file_path.exists() or file_path.suffix.lower() not in VALID_EXTENSIONS:
        return "skipped"

    file_id = str(file_path.resolve())
    if file_id in PROCESSED_FILES:
        return "skipped"

    cleaned_path = clean_filename(file_path)
    video_codec, audio_codec = get_codecs(cleaned_path)

    if DRY_RUN:
        if cleaned_path.suffix.lower() == ".mp4" and audio_codec != TARGET_AUDIO_CODEC:
            print(f"🔁 [Dry Run] Would fix audio in MP4: {cleaned_path.name} (Audio: {audio_codec} → aac)")
        elif cleaned_path.suffix.lower() == ".mkv":
            print(f"🔁 [Dry Run] Would convert MKV: {cleaned_path.name} (Video: {video_codec} → h264, Audio: {audio_codec} → aac)")
        return "dry-run"

    if cleaned_path.suffix.lower() == ".mp4" and audio_codec != TARGET_AUDIO_CODEC:
        tqdm.write(f"🔧 Fixing audio: {cleaned_path.name} (Audio: {audio_codec} → aac)")
        result = fix_audio(cleaned_path)
    elif cleaned_path.suffix.lower() == ".mkv":
        tqdm.write(f"🔧 Converting: {cleaned_path.name} (Video: {video_codec} → h264, Audio: {audio_codec} → aac)")
        result = convert_file(cleaned_path)
    else:
        return "skipped"

    if result in ["converted", "audio-fixed"]:
        PROCESSED_FILES.add(file_id)
        with open(STATE_LOG, "w") as f:
            json.dump(sorted(PROCESSED_FILES), f, indent=2)

    return result

def remove_empty_dirs(folder: Path):
    for dirpath, _, _ in os.walk(folder, topdown=False):
        dir_ = Path(dirpath)
        if not any(dir_.iterdir()):
            try:
                dir_.rmdir()
                logging.info(f"🧹 Removed empty folder: {dir_}")
            except Exception as e:
                logging.warning(f"⚠️ Could not remove folder {dir_}: {e}")

def summarize_results(counts):
    print("\n📊 Summary:")
    print(f"   🔄 Dry-run conversions: {counts['dry-run']}")
    print(f"   ✅ Converted files: {counts['converted']}")
    print(f"   🎧 Audio fixed: {counts['audio-fixed']}")
    print(f"   ⏭️ Skipped: {counts['skipped']}")
    print(f"   ❌ Failed: {counts['failed']}")

def main():
    all_files = []
    for base in BASE_FOLDERS:
        for ext in VALID_EXTENSIONS:
            all_files.extend(base.rglob(f"*{ext}"))

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(process_file, f): f for f in all_files}
        counts = defaultdict(int)
        for future in tqdm(as_completed(futures), total=len(futures), desc="Scanning Media"):
            result = future.result()
            counts[result] += 1

    summarize_results(counts)

    for folder in [Path(r"Z:\\Movies"), Path(r"I:\\Movies")]:
        remove_empty_dirs(folder)

if __name__ == "__main__":
    main()
    print("✅ Dry run completed." if DRY_RUN else "✅ Conversion run completed.")