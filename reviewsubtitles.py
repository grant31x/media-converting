import subprocess
from pathlib import Path

# Path to mkvextract executable
MKVEXTRACT_PATH = r"C:\Program Files\MKVToolNix\mkvextract.exe"

# Path to the MKV file
mkv_file = Path(r"E:\Movies\Dune.Part.Two.2024.2160p.4K.mkv")
track_id = 2  # Track number for forced English
output_srt = mkv_file.with_name(f"{mkv_file.stem}_track{track_id}.srt")

# Build the mkvextract command with full path
cmd = [
    MKVEXTRACT_PATH,
    "tracks",
    str(mkv_file),
    f"{track_id}:{output_srt}"
]

try:
    subprocess.run(cmd, check=True)
    print(f"✅ Extracted subtitle track {track_id} to: {output_srt}")
except subprocess.CalledProcessError as e:
    print("❌ Extraction failed:", e)
