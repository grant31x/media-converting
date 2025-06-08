# convert.py
# This module handles the video conversion process using FFmpeg with smart audio handling.

import subprocess
import shlex
import sys
import re
import logging
from pathlib import Path
from typing import List, Tuple, Callable, Optional

from models import MediaFile, SubtitleTrack, ConversionSettings
from subtitlesmkv import verify_subtitle_language_is_english

def _get_media_duration(file_path: Path) -> float:
    # ... (function remains the same)
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True); return float(result.stdout.strip())

def _time_to_seconds(time_str: str) -> float:
    # ... (function remains the same)
    try:
        parts = time_str.split(':'); return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except (ValueError, IndexError): return 0.0

def _run_ffmpeg_with_progress(command: List[str], duration: float, progress_callback: Callable, stop_check: Callable[[], bool]):
    # ... (function remains the same)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', bufsize=1)
    full_output = [];
    for line in iter(process.stdout.readline, ""):
        full_output.append(line)
        if stop_check(): process.terminate(); process.wait(); raise InterruptedError("Process cancelled by user.")
        if 'time=' in line:
            if match := re.search(r"time=(\d{2}:\d{2}:\d{2}\.\d{2})", line):
                progress = min(100, int((_time_to_seconds(match.group(1)) / duration) * 100)); progress_callback(progress, f"{progress}%")
    process.wait()
    if process.returncode != 0: raise subprocess.CalledProcessError(returncode=process.returncode, cmd=command, output=''.join(full_output))

def convert_batch(media_files: List[MediaFile], settings: ConversionSettings, progress_callback: Optional[Callable] = None, stop_check: Callable[[], bool] = lambda: False):
    # ... (function remains the same)
    for i, media in enumerate(media_files):
        if stop_check(): break
        if _should_skip_conversion(media): continue
        def file_progress_update(percent, status):
            if progress_callback: progress_callback(percent, f"File {i+1}/{len(media_files)}: {media.filename} - {status}")
        convert_media_file(media, settings, file_progress_update, stop_check)
    return media_files

def _should_skip_conversion(media: MediaFile) -> bool:
    # ... (function remains the same)
    if not media.needs_conversion: return True
    final_output_path = media.source_path.with_suffix('.mp4')
    if final_output_path.exists(): media.status = "Skipped (Exists)"; return True
    return False

def convert_media_file(media: MediaFile, settings: ConversionSettings, progress_callback: Callable, stop_check: Callable):
    # ... (function remains the same)
    media.status = "Preparing"; final_output_path = media.source_path.with_suffix(".mp4"); temp_output_path = media.source_path.with_suffix(".temp.mp4"); media.destination_path = final_output_path
    if media.source_path.exists(): media.original_size_gb = media.source_path.stat().st_size / (1024**3)
    if media.burned_subtitle and not verify_subtitle_language_is_english(media.source_path, media.burned_subtitle.index): media.burned_subtitle = None
    temp_output_path.unlink(missing_ok=True); pass_log_file = temp_output_path.with_suffix('.log')
    try:
        duration = _get_media_duration(media.source_path); use_two_pass = settings.use_two_pass and media.burned_subtitle
        commands_to_run = []
        if use_two_pass:
            commands_to_run.append(_build_ffmpeg_command(media, settings, temp_output_path, 1, str(pass_log_file)))
            commands_to_run.append(_build_ffmpeg_command(media, settings, temp_output_path, 2, str(pass_log_file)))
        else:
            commands_to_run.append(_build_ffmpeg_command(media, settings, temp_output_path, 0, ""))
        for i, cmd in enumerate(commands_to_run):
            if stop_check(): raise InterruptedError("Conversion cancelled by user.")
            pass_str = f"Pass {i+1}/{len(commands_to_run)}" if len(commands_to_run) > 1 else "Encoding..."
            progress_callback(0, pass_str); _run_ffmpeg_with_progress(cmd, duration, lambda p, s: progress_callback(p, f"{pass_str} - {s}"), stop_check)
        temp_output_path.rename(final_output_path); media.status = "Converted"
        media.converted_size_gb = final_output_path.stat().st_size / (1024**3)
        if settings.delete_source_on_success: media.source_path.unlink()
    except Exception as e:
        media.status = "Error"; media.error_message = f"Conversion failed: {getattr(e, 'output', str(e))}"
    finally:
        if temp_output_path.exists(): temp_output_path.unlink()
        if pass_log_file.exists(): pass_log_file.unlink()
        if Path(f"{pass_log_file}-0.log.mbtree").exists(): Path(f"{pass_log_file}-0.log.mbtree").unlink()

def _build_ffmpeg_command(media: MediaFile, settings: ConversionSettings, output_path: Path, pass_num: int, pass_log_prefix: str) -> List[str]:
    """Builds FFmpeg command for a specific pass with smart audio handling."""
    command = ["ffmpeg", "-y", "-i", str(media.source_path)]
    if media.burned_subtitle:
        subtitle_file_path = str(media.source_path).replace('\\', '/').replace(':', '\\:')
        command.extend(["-vf", f"subtitles='{subtitle_file_path}':stream_index={media.burned_subtitle.ffmpeg_index}"])
        command.extend(["-c:v", "hevc_nvenc", "-preset", "p7", "-cq", "20", "-qmin", "0", "-rc:v", "vbr_hq"])
        if pass_num > 0: command.extend(["-pass", str(pass_num), "-passlogfile", pass_log_prefix])
    else:
        command.extend(["-c:v", "copy"])

    if pass_num == 1:
        command.extend(["-an", "-f", "null", "NUL" if sys.platform == "win32" else "/dev/null"])
    else:
        # --- NEW: Smart Audio Logic ---
        compatible_codecs = ['aac', 'ac3', 'eac3']
        if media.audio_codec and media.audio_codec.lower() in compatible_codecs and media.audio_channels >= 6:
            command.extend(["-c:a", "copy"])
            setattr(media, 'audio_conversion_details', f"Copied {media.audio_codec.upper()} {media.audio_channels}ch")
        else:
            command.extend(["-c:a", "ac3", "-b:a", "640k"])
            setattr(media, 'audio_conversion_details', f"Converted to AC3 640k")

        for i, sub in enumerate(s for s in media.subtitle_tracks if s.action == 'copy'):
            command.extend(["-map", f"0:s:{sub.ffmpeg_index}", f"-c:s:{i}", "mov_text"])
        
        command.extend(["-map", "0:v", "-map", "0:a"])
        command.append(str(output_path))
    return command
