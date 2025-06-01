import subprocess
import json
from pathlib import Path

FFMPEG_PATH = Path("C:/Programs2/ffmpeg/ffmpeg_essentials_build/bin/ffmpeg.exe")
FFPROBE_PATH = Path("C:/Programs2/ffmpeg/ffmpeg_essentials_build/bin/ffprobe.exe")

# Path to the directory you want to scan
TARGET_DIR = Path("/Users/grant31/mnt/networkdrive/Movies")
OUTPUT_DIR = TARGET_DIR.parent / "Converted_Movies"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Acceptable codecs
VIDEO_OK = "h264"
AUDIO_OK = "aac"
CONTAINER_OK = ".mp4"

def get_streams(file_path):
    try:
        cmd = [
            str(FFPROBE_PATH), "-v", "error",
            "-show_entries", "stream=codec_type,codec_name",
            "-of", "json", str(file_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(result.stdout).get("streams", [])
    except subprocess.CalledProcessError:
        return None

def convert_file(file_path, dest_path):
    print(f"🔄 Converting: {file_path.name}")
    try:
        subprocess.run([
            str(FFMPEG_PATH), "-i", str(file_path),
            "-c:v", "libx264", "-crf", "23", "-preset", "medium",
            "-c:a", "aac", "-b:a", "160k",
            "-movflags", "+faststart",
            str(dest_path)
        ], check=True)
        print(f"✅ Converted: {dest_path.name}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Conversion failed: {file_path.name} — {e}")

def process_files():
    files_to_convert = []
    all_files = list(TARGET_DIR.rglob("*.mp4"))

    # First pass to determine which files need conversion
    for file_path in all_files:
        if file_path.name.startswith("._"):
            continue

        streams = get_streams(file_path)
        if streams is None:
            continue

        video_codec = next((s["codec_name"] for s in streams if s["codec_type"] == "video"), None)
        audio_codec = next((s["codec_name"] for s in streams if s["codec_type"] == "audio"), None)

        if video_codec != VIDEO_OK or audio_codec != AUDIO_OK:
            files_to_convert.append(file_path)

    print(f"\n📦 Total to be converted: {len(files_to_convert)}\n")

    # Second pass to print and process files
    for idx, file_path in enumerate(files_to_convert, 1):
        dest_path = OUTPUT_DIR / file_path.name
        print(f"🔄 [{idx}/{len(files_to_convert)}] Converting: {file_path.name} — 0%")  # Placeholder
        convert_file(file_path, dest_path)

if __name__ == "__main__":
    process_files()