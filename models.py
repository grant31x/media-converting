# models.py
# Version: 2.1
# This file defines the data structures for the media conversion tool.

import sys
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Literal

SubtitleAction = Literal["burn", "copy", "ignore"]

@dataclass
class SubtitleTrack:
    """Represents a single subtitle track within a media file."""
    index: int; ffmpeg_index: Optional[int] = None; language: str = "und"; title: Optional[str] = None
    codec: Optional[str] = None; is_default: bool = False; is_forced: bool = False
    is_text_based: bool = False; action: SubtitleAction = "ignore" 

    def get_display_name(self) -> str:
        parts = [f"Track {self.index}", f"({self.language})"];
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
    
    # Metadata fields
    container: str = "N/A"
    video_codec: Optional[str] = None
    video_width: int = 0
    video_fps: float = 0.0
    audio_codec: Optional[str] = None
    audio_channels: int = 0
    
    # NEW: Fields for storing metadata
    title: str = ""
    year: Optional[int] = None
    comment: Optional[str] = None
    
    subtitle_tracks: List[SubtitleTrack] = field(default_factory=list)
    burned_subtitle: Optional[SubtitleTrack] = None
    status: str = "Pending"; error_message: Optional[str] = None
    has_forced_subtitles: bool = field(init=False, default=False); needs_conversion: bool = True
    original_size_gb: float = 0.0; converted_size_gb: float = 0.0
    use_basic_conversion: bool = False

    def __post_init__(self):
        self.filename = self.source_path.name
        self.title = self.source_path.stem  # Default title is the source filename without extension
        self.output_filename = f"{self.title}.mp4" # Default output name
        self.update_flags()

    def update_flags(self):
        self.has_forced_subtitles = any(track.is_forced for track in self.subtitle_tracks)
        
    def generate_filename_from_template(self, template: str) -> str:
        """Generates a filename from a template string and the file's metadata."""
        if not template:
            return f"{self.title}.mp4"
            
        replacements = {
            "title": self.title or self.source_path.stem,
            "year": str(self.year or ""),
            "width": str(self.video_width),
            "fps": str(round(self.video_fps or 0)),
        }
        
        # Basic placeholder replacement
        for key, value in replacements.items():
            template = template.replace(f"{{{key}}}", value)
            
        # Clean up invalid filename characters
        invalid_chars = r'[\\/:"*?<>|]'
        cleaned_name = re.sub(invalid_chars, '', template).strip()
        
        return f"{cleaned_name}.mp4"

    def classify(self) -> str:
        """Determines if a file should be remuxed or fully converted."""
        if self.burned_subtitle: return "convert"
        compatible_audio = ['aac', 'ac3', 'eac3']
        if self.audio_codec and self.audio_codec.lower() not in compatible_audio: return "convert"
        compatible_video = ['h264', 'hevc']
        if self.video_codec and not any(c in self.video_codec.lower() for c in compatible_video): return "convert"
        return "remux"

    def generate_preview(self, settings: 'ConversionSettings') -> str:
        """Generates a detailed, human-readable summary of the planned conversion."""
        plan = []
        plan.append("--- SOURCE FILE METADATA ---")
        plan.append(f"  Container: {self.container}")
        plan.append(f"  Size: {self.original_size_gb:.2f} GB")
        plan.append(f"  Video: {self.video_codec}, {self.video_width}p, {self.video_fps:.2f} fps")
        plan.append(f"  Audio: {self.audio_codec}, {self.audio_channels} channels")
        plan.append("\n--- PLANNED CONVERSION ---")

        conversion_type = self.classify()
        plan.append(f"  Operation Type: {'Fast Remux' if conversion_type == 'remux' else 'Full Re-encode'}")

        # Video Plan
        if self.burned_subtitle:
            video_plan = f"Re-encode to {settings.video_codec.upper()}"
            if settings.use_two_pass:
                video_plan += " (2-Pass)"
        else:
            video_plan = "Copy (remux)"
        plan.append(f"  Video Action: {video_plan}")

        # Audio Plan
        compatible_audio = ['aac', 'ac3', 'eac3']
        if self.audio_codec and self.audio_codec.lower() in compatible_audio and self.audio_channels >= 6:
            audio_plan = f"Copy existing {self.audio_codec.upper()} stream"
        else:
            audio_plan = f"Re-encode to {settings.audio_codec.upper()} at {settings.audio_bitrate}"
        plan.append(f"  Audio Action: {audio_plan}")

        # Subtitle Plan
        burned = self.burned_subtitle.get_display_name() if self.burned_subtitle else "None"
        plan.append(f"  Subtitles to Burn: {burned}")
        
        copied = [s.get_display_name() for s in self.subtitle_tracks if s.action == 'copy']
        plan.append(f"  Subtitles to Copy: {', '.join(copied) if copied else 'None'}")
        
        plan.append("\n--- OUTPUT ---")
        plan.append(f"  Container: .mp4")
        plan.append(f"  Output Path: {self.source_path.with_name(self.output_filename)}")
        plan.append(f"  Embedded Title: {self.title or 'N/A'}")
        plan.append(f"  Embedded Year: {self.year or 'N/A'}")
        
        return "\n".join(plan)

    def __str__(self) -> str:
        return f"{self.filename} ({len(self.subtitle_tracks)} subs) → {self.output_filename}"

    @property
    def size_change_percent(self) -> float:
        if not self.original_size_gb or not self.converted_size_gb: return 0.0
        return ((self.converted_size_gb - self.original_size_gb) / self.original_size_gb) * 100

@dataclass
class ConversionSettings:
    """Stores global settings for the conversion process."""
    use_nvenc: bool = True; use_two_pass: bool = True; video_codec: str = "hevc_nvenc"
    audio_codec: str = "ac3"; audio_bitrate: str = "640k"; preset: str = "p7"
    crf: int = 23; output_directory: Path = Path("./converted"); dry_run: bool = False
    delete_source_on_success: bool = False
    filename_template: str = "{title} ({year}) - {width}p" # NEW
    scannable_file_types: List[str] = field(default_factory=lambda: [".mkv"]) # NEW