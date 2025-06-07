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
