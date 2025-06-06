import subprocess
import json
from pathlib import Path
import os

# Configuration
source_dir = Path("Z:/Test")
destination_dir = Path("E:/Movies")
log_file = Path("move_log.json")

# Robocopy options
robocopy_options = ["/MOV", "/NFL", "/NDL", "/NJH", "/NJS", "/NP"]

def load_log():
    if log_file.exists():
        with open(log_file, "r") as f:
            return json.load(f)
    return {}

def save_log(log_data):
    with open(log_file, "w") as f:
        json.dump(log_data, f, indent=4)

def move_all():
    log_data = load_log()

    for item in source_dir.iterdir():
        name = item.name

        if log_data.get(name) == "moved":
            print(f"⏩ Already moved: {name}")
            continue

        if not item.exists():
            print(f"⚠️ Not found: {name}")
            log_data[name] = "not_found"
            continue

        try:
            if item.is_dir():
                print(f"📁 Moving folder: {name}")
                result = subprocess.run(
                    ["robocopy", str(item), str(destination_dir / name)] + robocopy_options,
                    capture_output=True,
                    text=True
                )
            else:
                print(f"📄 Moving file: {name}")
                result = subprocess.run(
                    ["robocopy", str(source_dir), str(destination_dir), name] + robocopy_options,
                    capture_output=True,
                    text=True
                )

            if result.returncode <= 7:
                print(f"✅ Moved: {name}")
                log_data[name] = "moved"
            else:
                print(f"❌ Robocopy error on: {name}")
                print(result.stdout)
                print(result.stderr)
                log_data[name] = f"error_code_{result.returncode}"

        except Exception as e:
            print(f"❌ Exception moving {name}: {e}")
            log_data[name] = "exception"

        save_log(log_data)

if __name__ == "__main__":
    move_all()
