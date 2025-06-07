# models.py
# This file defines the data structures for the media conversion tool.

import sys
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Literal

# Define custom types for clarity and type hinting
SubtitleAction = Literal["burn", "copy", "ignore"]

@dataclass
class SubtitleTrack:
    """Represents a single subtitle track within a media file."""
    index: int
    ffmpeg_index: Optional[int] = None
    language: str = "und"
    title: Optional[str] = None
    codec: Optional[str] = None
    is_default: bool = False
    is_forced: bool = False
    action: SubtitleAction = "ignore" 

    def get_display_name(self) -> str:
        """Generates a user-friendly name for the subtitle track."""
        parts = [f"Track {self.index}"]
        if self.ffmpeg_index is not None: parts.append(f"(s:{self.ffmpeg_index})")
        parts.append(f"({self.language})")
        if self.title: parts.append(f"'{self.title}'")
        if self.is_forced: parts.append("[FORCED]")
        if self.is_default: parts.append("[DEFAULT]")
        return " - ".join(parts)

@dataclass
class MediaFile:
    """Represents a single media file to be processed."""
    source_path: Path
    filename: str = field(init=False)
    output_filename: str = field(init=False)
    destination_path: Optional[Path] = None
    created_time: Optional[float] = None
    modified_time: Optional[float] = None
    subtitle_tracks: List[SubtitleTrack] = field(default_factory=list)
    burned_subtitle: Optional[SubtitleTrack] = None
    status: str = "Pending"
    error_message: Optional[str] = None
    has_forced_subtitles: bool = field(init=False, default=False)
    needs_conversion: bool = True
    original_size_mb: float = 0.0
    converted_size_mb: float = 0.0

    def __post_init__(self):
        """Set dynamic fields after the object is initialized, including filename cleaning."""
        self.filename = self.source_path.name
        cleaned_stem = re.sub(r'[\[\]]', '', self.source_path.stem)
        self.output_filename = f"{cleaned_stem.strip()}.mp4"
        self.update_flags()

    def update_flags(self):
        """Recalculates flags based on the current state of subtitle_tracks."""
        self.has_forced_subtitles = any(track.is_forced for track in self.subtitle_tracks)
        
    def __str__(self) -> str:
        return f"{self.filename} ({len(self.subtitle_tracks)} subs) → {self.output_filename}"

    @property
    def size_change_percent(self) -> float:
        """Calculates the percentage change in file size after conversion."""
        if not self.original_size_mb or not self.converted_size_mb: return 0.0
        return ((self.converted_size_mb - self.original_size_mb) / self.original_size_mb) * 100

@dataclass
class ConversionSettings:
    """Stores global settings for the conversion process."""
    use_nvenc: bool = True
    video_codec: str = "hevc_nvenc"
    audio_codec: str = "aac"
    audio_bitrate: str = "320k"
    preset: str = "p7"
    crf: int = 23
    output_directory: Path = Path("./converted")
    dry_run: bool = False
    # FIX: Added the missing field to match the settings UI
    delete_source_on_success: bool = False
