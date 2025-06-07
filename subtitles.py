import subprocess
import json

def scan_subtitles(file_path: Path):
    try:
        result = subprocess.run(
            ["C:/Program Files/MKVToolNix/mkvmerge.exe", "-J", str(file_path)],
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8"
        )
        data = json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"❌ mkvmerge failed: {e.stderr.strip()}")
        return
    except json.JSONDecodeError as e:
        print(f"❌ Failed to parse mkvmerge JSON: {e}")
        return
    except FileNotFoundError:
        print("❌ mkvmerge is not installed or not in PATH.")
        return

    print(f"\n🎯 Subtitle Track Summary for: {file_path.name}")
    print("-" * 60)

    subtitle_tracks = [t for t in data.get("tracks", []) if t.get("type") == "subtitles"]

    if not subtitle_tracks:
        print("⚠️  No subtitle tracks found.")
        return

    for track in subtitle_tracks:
        track_id = track.get("id", "?")
        props = track.get("properties", {})
        lang = props.get("language", "und")
        forced = props.get("forced_track", False)
        codec = props.get("codec_id", "unknown")
        track_name = props.get("track_name", "")

        status = "🔥 Forced" if forced else "💬 Optional"
        print(f"ID {track_id}: {status} | Lang: {lang.upper():3} | Codec: {codec:15} | Name: {track_name}")

from pathlib import Path
if __name__ == "__main__":
    import os

    base_dirs = [Path("E:/Movies"), Path("E:/TVShows")]

    mkv_files = []
    for base in base_dirs:
        for root, _, files in os.walk(base):
            for file in files:
                if file.lower().endswith(".mkv"):
                    mkv_files.append(Path(root) / file)

    if not mkv_files:
        print("No MKV files found in the specified directories.")
    else:
        for mkv_file in mkv_files:
            scan_subtitles(mkv_file)
