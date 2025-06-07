# models.py
# This file defines the data structures for the media conversion tool.

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Literal

# Define custom types for clarity and type hinting
SubtitleAction = Literal["burn", "copy", "ignore"]

@dataclass
class SubtitleTrack:
    """
    Represents a single subtitle track within a media file.
    """
    index: int  # Original index from the source file (e.g., from mkvmerge)
    ffmpeg_index: Optional[int] = None # FFmpeg's specific subtitle stream index (e.g., 0, 1, 2 for s:0, s:1, s:2)
    language: str = "und"  # Undetermined language code as default
    title: Optional[str] = None
    codec: Optional[str] = None
    is_default: bool = False
    is_forced: bool = False
    
    # User-defined action for this subtitle track
    action: SubtitleAction = "ignore" 

    def get_display_name(self) -> str:
        """Generates a user-friendly name for the subtitle track."""
        parts = [f"Track {self.index}"]
        if self.ffmpeg_index is not None:
            parts.append(f"(s:{self.ffmpeg_index})")
            
        parts.append(f"({self.language})")
        
        if self.title:
            parts.append(f"'{self.title}'")
        if self.is_forced:
            parts.append("[FORCED]")
        if self.is_default:
            parts.append("[DEFAULT]")
        return " - ".join(parts)

@dataclass
class MediaFile:
    """
    Represents a single media file to be processed.
    """
    source_path: Path
    
    # Core file properties
    filename: str = field(init=False)
    output_filename: str = field(init=False)
    destination_path: Optional[Path] = None
    
    # Optional file system timestamps
    created_time: Optional[float] = None
    modified_time: Optional[float] = None
    
    # Subtitle information
    subtitle_tracks: List[SubtitleTrack] = field(default_factory=list)
    burned_subtitle: Optional[SubtitleTrack] = None
    
    # Status tracking & GUI flags
    status: str = "Pending"  # e.g., "Pending", "Scanning", "Ready", "Converting", "Done", "Error"
    error_message: Optional[str] = None
    has_forced_subtitles: bool = field(init=False, default=False)
    needs_conversion: bool = True
    
    # Post-conversion info
    original_size_mb: float = 0.0
    converted_size_mb: float = 0.0

    def __post_init__(self):
        """Set dynamic fields after the object is initialized."""
        self.filename = self.source_path.name
        self.output_filename = self.source_path.with_suffix(".mp4").name
        # Note: has_forced_subtitles is based on initial state.
        # Call update_flags() if subtitle_tracks are modified after instantiation.
        self.update_flags()

    def update_flags(self):
        """Recalculates flags based on the current state of subtitle_tracks."""
        self.has_forced_subtitles = any(track.is_forced for track in self.subtitle_tracks)
        
    def __str__(self) -> str:
        """Provides a user-friendly string representation of the media file."""
        return f"{self.filename} ({len(self.subtitle_tracks)} subs) → {self.output_filename}"

    @property
    def size_change_percent(self) -> float:
        """Calculates the percentage change in file size after conversion."""
        if not self.original_size_mb or not self.converted_size_mb:
            return 0.0
        return ((self.converted_size_mb - self.original_size_mb) / self.original_size_mb) * 100

@dataclass
class ConversionSettings:
    """
    Stores global settings for the conversion process.
    """
    use_nvenc: bool = True
    video_codec: str = "hevc_nvenc"  # or "h264_nvenc", "libx264"
    audio_codec: str = "aac"
    audio_bitrate: str = "320k"
    preset: str = "p7"  # NVENC preset, e.g., p1 (fastest) to p7 (best quality)
    crf: int = 23  # Constant Rate Factor for software encoding (like libx264)
    output_directory: Path = Path("./converted")
    dry_run: bool = False # If True, only print commands, don't execute

# Example Usage:
if __name__ == "__main__":
    # This block demonstrates how to use the updated models.
    # In the actual application, these objects will be created by the GUI and processing modules.

    # 1. Create a media file object
    mkv_path = Path("E:/Movies/My Awesome Movie (2023)/My Awesome Movie.mkv")
    media_file = MediaFile(source_path=mkv_path)
    
    # 2. Populate it with subtitle tracks (this would come from ffprobe)
    # Note the new ffmpeg_index field, which corresponds to the subtitle stream index (s:0, s:1, etc.)
    sub1 = SubtitleTrack(index=2, ffmpeg_index=0, language="eng", title="Full Subtitles", codec="SubRip/SRT")
    sub2 = SubtitleTrack(index=3, ffmpeg_index=1, language="eng", title="Forced Only", codec="SubRip/SRT", is_forced=True)
    sub3 = SubtitleTrack(index=4, ffmpeg_index=2, language="spa", title="Español", codec="SubRip/SRT")
    
    media_file.subtitle_tracks.extend([sub1, sub2, sub3])
    # After adding tracks, it's good practice to update the flags.
    media_file.update_flags()
    
    # 3. Application logic would auto-select the forced track for burn-in
    for sub in media_file.subtitle_tracks:
        if sub.is_forced and sub.language == "eng":
            sub.action = "burn"
            media_file.burned_subtitle = sub  # Track the burned-in subtitle
            print(f"Auto-selected for burn-in: {sub.get_display_name()}")
            break
            
    # User might decide to copy the Spanish subtitles as well
    sub3.action = "copy"
    
    print("\n--- Media File State ---")
    print(f"String representation: {media_file}")
    print(f"Source: {media_file.source_path}")
    print(f"Has forced subtitles flag: {media_file.has_forced_subtitles}")
    print(f"Needs conversion flag: {media_file.needs_conversion}")
    if media_file.burned_subtitle:
        print(f"Subtitle to burn: {media_file.burned_subtitle.get_display_name()}")

    print("\nSubtitle Actions:")
    for sub in media_file.subtitle_tracks:
        print(f"  - {sub.get_display_name()}: {sub.action.upper()}")

    # 4. Define conversion settings
    settings = ConversionSettings(
        output_directory=Path("Z:/Movies/"),
        use_nvenc=True,
        video_codec="hevc_nvenc"
    )
    
    print("\n--- Conversion Settings ---")
    print(f"Output Directory: {settings.output_directory}")
    print(f"Using NVENC: {settings.use_nvenc}")
    print(f"Video Codec: {settings.video_codec}")
