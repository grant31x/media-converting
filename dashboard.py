# dashboard.py
# Version: 3.0
# This is the main PyQt6 GUI for the media conversion tool. It orchestrates the scanning,
# user selection, conversion, and file transfer processes by calling the other backend modules.

import sys
import json
import re
import inspect
from pathlib import Path
from typing import List, Callable, Tuple, Dict, Any

from PyQt6.QtCore import QObject, QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QFileDialog, QFrame, QHBoxLayout, QComboBox, QCheckBox, QGroupBox,
    QMessageBox, QDialog, QDialogButtonBox, QLineEdit, QStackedWidget,
    QStatusBar, QSpinBox, QTextEdit, QMenu, QProgressBar
)

from models import MediaFile, SubtitleTrack, ConversionSettings
import subtitlesmkv
import convert
import robocopy
import basic_convert
import mkv_modifier

# --- Dialog for Renaming Files ---
class RenameDialog(QDialog):
    def __init__(self, current_filename: str, current_title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Rename File")
        self.layout = QVBoxLayout(self)

        self.layout.addWidget(QLabel("Output Filename:"))
        self.filename_edit = QLineEdit(current_filename)
        self.layout.addWidget(self.filename_edit)

        self.layout.addWidget(QLabel("Metadata Title (Optional):"))
        self.title_edit = QLineEdit(current_title)
        self.layout.addWidget(self.title_edit)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.layout.addWidget(self.button_box)

    def get_names(self) -> Tuple[str, str] | None:
        if self.exec() == QDialog.DialogCode.Accepted:
            return self.filename_edit.text(), self.title_edit.text()
        return None

# --- Main Application Classes ---
class ConfigHandler:
    def __init__(self, config_path: str = "config.json"):
        self.config_path = Path(config_path); self.config: Dict[str, Any] = {}; self.default_config = {"scan_directories": ["E:/Movies", "E:/TV Shows"], "output_directory": "./converted", "use_nvenc": True, "delete_source_on_success": False, "crf_value": 23, "use_two_pass": True}; self.load_config()
    def load_config(self):
        if not self.config_path.exists(): self.config = self.default_config
        else:
            try:
                with open(self.config_path, "r", encoding="utf-8") as f: self.config = self.default_config | json.load(f)
            except (json.JSONDecodeError, IOError): self.config = self.default_config
        self.save_config()
    def save_config(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f: json.dump(self.config, f, indent=4)
        except IOError as e: print(f"Error saving config file: {e}")
    def get_setting(self, key: str, default: Any = None) -> Any: return self.config.get(key, default)
    def set_setting(self, key: str, value: Any): self.config[key] = value

class SettingsWindow(QDialog):
    def __init__(self, config_handler: ConfigHandler, parent=None):
        super().__init__(parent)
        self.config_handler = config_handler
        self.setWindowTitle("Settings")
        self.setMinimumWidth(550)
        self.layout = QVBoxLayout(self)

        conv_group = QGroupBox("Conversion Settings")
        conv_layout = QVBoxLayout()

        # NVENC Checkbox
        self.nvenc_checkbox = QCheckBox("Enable GPU Encoding (NVIDIA NVENC)")
        self.nvenc_checkbox.setToolTip("Faster and efficient—uses your graphics card instead of the CPU.")
        conv_layout.addWidget(self.nvenc_checkbox)

        # 2-Pass Checkbox
        self.two_pass_checkbox = QCheckBox("Enable 2-Pass Mode (slower, better file size)")
        self.two_pass_checkbox.setToolTip("Runs two scans over the file to optimize video quality and compression.")
        conv_layout.addWidget(self.two_pass_checkbox)

        # Delete Source Checkbox
        self.delete_source_checkbox = QCheckBox("Delete Original File After Conversion")
        self.delete_source_checkbox.setToolTip("⚠️ This action is permanent and cannot be undone.")
        conv_layout.addWidget(self.delete_source_checkbox)

        # Quality Level Field
        quality_layout = QHBoxLayout()
        quality_label = QLabel("Target Quality Level (lower = better quality):")
        quality_label.setToolTip(
            "Controls video compression strength. Lower = higher quality, larger file.\n"
            "Recommended: 18–22.\n"
            "Used for both CPU (CRF) and GPU (CQ) encoding."
        )
        quality_layout.addWidget(quality_label)
        self.quality_spinbox = QSpinBox()
        self.quality_spinbox.setRange(0, 51)
        quality_layout.addWidget(self.quality_spinbox)
        conv_layout.addLayout(quality_layout)
        
        conv_group.setLayout(conv_layout)
        self.layout.addWidget(conv_group)

        # Directory Settings
        self.layout.addWidget(QLabel("Default Output Directory:"))
        output_dir_layout = QHBoxLayout()
        self.output_dir_edit = QLineEdit()
        self.browse_output_btn = QPushButton("Browse...")
        output_dir_layout.addWidget(self.output_dir_edit)
        output_dir_layout.addWidget(self.browse_output_btn)
        self.layout.addLayout(output_dir_layout)
        
        self.dir_list_widget = QListWidget()
        self.layout.addWidget(QLabel("Scan Directories:"))
        self.layout.addWidget(self.dir_list_widget)
        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("Add Scan Directory...")
        self.remove_btn = QPushButton("Remove Selected")
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.remove_btn)
        self.layout.addLayout(btn_layout)

        # Save/Cancel Buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.layout.addWidget(self.button_box)

        # Connect signals
        self.browse_output_btn.clicked.connect(lambda: self.browse_directory(self.output_dir_edit))
        self.add_btn.clicked.connect(self.add_scan_directory)
        self.remove_btn.clicked.connect(lambda: self.dir_list_widget.takeItem(self.dir_list_widget.currentRow()))
        self.button_box.accepted.connect(self.save_and_accept)
        self.button_box.rejected.connect(self.reject)
        
        self.load_settings()

    def load_settings(self):
        self.nvenc_checkbox.setChecked(self.config_handler.get_setting("use_nvenc", True))
        self.two_pass_checkbox.setChecked(self.config_handler.get_setting("use_two_pass", True))
        self.delete_source_checkbox.setChecked(self.config_handler.get_setting("delete_source_on_success", False))
        self.quality_spinbox.setValue(self.config_handler.get_setting("crf_value", 23))
        self.output_dir_edit.setText(self.config_handler.get_setting("output_directory"))
        self.dir_list_widget.clear()
        self.dir_list_widget.addItems(self.config_handler.get_setting("scan_directories", []))

    def browse_directory(self, line_edit: QLineEdit):
        if folder := QFileDialog.getExistingDirectory(self, "Select Directory"):
            line_edit.setText(folder)

    def add_scan_directory(self):
        if folder := QFileDialog.getExistingDirectory(self, "Select Scan Directory"):
            self.dir_list_widget.addItem(folder)

    def save_and_accept(self):
        self.config_handler.set_setting("use_nvenc", self.nvenc_checkbox.isChecked())
        self.config_handler.set_setting("use_two_pass", self.two_pass_checkbox.isChecked())
        self.config_handler.set_setting("delete_source_on_success", self.delete_source_checkbox.isChecked())
        self.config_handler.set_setting("crf_value", self.quality_spinbox.value())
        self.config_handler.set_setting("output_directory", self.output_dir_edit.text())
        self.config_handler.set_setting("scan_directories", [self.dir_list_widget.item(i).text() for i in range(self.dir_list_widget.count())])
        self.config_handler.save_config()
        self.accept()

class SubtitlePreviewDialog(QDialog):
    def __init__(self, media_file: MediaFile, parent=None):
        super().__init__(parent); self.media_file = media_file; self.setWindowTitle(f"Subtitle Preview - {media_file.filename}"); self.setMinimumSize(600, 400); self.layout = QVBoxLayout(self)
        controls_layout = QHBoxLayout(); controls_layout.addWidget(QLabel("Select Track to Preview:")); self.track_combo = QComboBox()
        for track in self.media_file.subtitle_tracks:
            if track.is_text_based: self.track_combo.addItem(track.get_display_name(), track)
        controls_layout.addWidget(self.track_combo, 1); self.preview_btn = QPushButton("Get Preview & Detect Language"); controls_layout.addWidget(self.preview_btn); self.layout.addLayout(controls_layout)
        self.info_layout = QHBoxLayout(); self.detected_lang_label = QLabel("Detected Language: N/A"); self.warning_label = QLabel(); self.warning_label.setStyleSheet("color: #f1c40f; font-weight: bold;")
        self.info_layout.addWidget(self.detected_lang_label); self.info_layout.addStretch(); self.info_layout.addWidget(self.warning_label); self.layout.addLayout(self.info_layout)
        self.snippet_display = QTextEdit(); self.snippet_display.setReadOnly(True); self.layout.addWidget(self.snippet_display)
        self.close_btn = QPushButton("Close"); self.layout.addWidget(self.close_btn)
        self.preview_btn.clicked.connect(self.run_preview); self.close_btn.clicked.connect(self.accept)
    def run_preview(self):
        selected_track = self.track_combo.currentData();
        if not selected_track: return
        self.selected_track = selected_track; self.snippet_display.setText(f"Extracting snippet for track {self.selected_track.index}...");
        self.worker = Worker(subtitlesmkv.get_subtitle_details, self.media_file.source_path, self.selected_track.index)
        self.thread = QThread(); self.worker.moveToThread(self.thread); self.thread.started.connect(self.worker.run); self.worker.finished.connect(self.on_preview_finished); self.thread.start()
    def on_preview_finished(self, result: Tuple[str, str]):
        snippet, detected_lang = result; self.snippet_display.setText(snippet); self.detected_lang_label.setText(f"Detected Language: <b>{detected_lang.upper()}</b>")
        metadata_lang_code = self.selected_track.language[:2]
        if metadata_lang_code and detected_lang != "unknown" and metadata_lang_code != detected_lang: self.warning_label.setText("⚠️ Language Mismatch!")
        else: self.warning_label.setText("")
        self.thread.quit()

class SubtitleEditorDialog(QDialog):
    track_modified = pyqtSignal(object)
    def __init__(self, media_file: MediaFile, parent=None):
        super().__init__(parent); self.media_file = media_file; self.setWindowTitle(f"Edit/Remove Subtitles - {media_file.filename}"); self.setMinimumSize(600, 400); self.layout = QVBoxLayout(self)
        self.track_list = QListWidget(); self.track_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection); self.layout.addWidget(self.track_list)
        self.delete_button = QPushButton("Permanently Remove Selected Track(s)"); self.close_button = QPushButton("Close")
        btn_layout = QHBoxLayout(); btn_layout.addStretch(); btn_layout.addWidget(self.delete_button); btn_layout.addWidget(self.close_button); self.layout.addLayout(btn_layout)
        self.delete_button.clicked.connect(self.delete_tracks); self.close_button.clicked.connect(self.accept); self.populate_tracks()
    def populate_tracks(self):
        self.track_list.clear()
        for track in self.media_file.subtitle_tracks:
            item = QListWidgetItem(f"Track {track.index}: {track.get_display_name()}"); item.setData(Qt.ItemDataRole.UserRole, track); self.track_list.addItem(item)
    def delete_tracks(self):
        selected_items = self.track_list.selectedItems()
        if not selected_items: QMessageBox.warning(self, "No Selection", "Please select one or more subtitle tracks to remove."); return
        tracks_to_delete = [item.data(Qt.ItemDataRole.UserRole) for item in selected_items]
        track_ids_to_delete = [t.index for t in tracks_to_delete]; track_list_str = "\n".join([f"- {t.get_display_name()}" for t in tracks_to_delete])
        reply = QMessageBox.question(self, "Confirm Track Removal", f"Are you sure you want to permanently REMOVE the following tracks?\n\n{track_list_str}\n\nThis will rewrite the MKV file and cannot be undone.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.worker = Worker(mkv_modifier.remove_subtitle_tracks, self.media_file.source_path, track_ids_to_delete)
            self.thread = QThread(); self.worker.moveToThread(self.thread); self.worker.finished.connect(self.on_delete_finished); self.thread.started.connect(self.worker.run); self.thread.start(); self.delete_button.setEnabled(False)
    def on_delete_finished(self, success: bool):
        if success:
            self.track_modified.emit(self.parent())
            self.accept()
        else:
            QMessageBox.critical(self, "Error", "Failed to modify the MKV file. Check the console for details.")
            self.delete_button.setEnabled(True)
        self.thread.quit()

class Worker(QObject):
    finished = pyqtSignal(object); error = pyqtSignal(tuple); progress = pyqtSignal(int, str)
    def __init__(self, fn: Callable, *args, **kwargs):
        super().__init__(); self.fn, self.args, self.kwargs = fn, args, kwargs
    def run(self):
        try:
            if 'progress_callback' in inspect.signature(self.fn).parameters: self.kwargs['progress_callback'] = lambda p, s: self.progress.emit(p, s)
            result = self.fn(*self.args, **self.kwargs); self.finished.emit(result)
        except Exception as e: import traceback; self.error.emit((type(e), e, traceback.format_exc()))

class MediaFileItemWidget(QFrame):
    def __init__(self, media_file: MediaFile, dashboard_ref: 'Dashboard'):
        super().__init__()
        self.media_file = media_file
        self.dashboard_ref = dashboard_ref
        self.setObjectName("MediaFileItemWidget")
        self.soft_copy_checkboxes: list[QCheckBox] = []
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        header_layout = QHBoxLayout()
        self.filename_label = QLabel()
        self.status_label = QLabel()
        header_layout.addWidget(self.filename_label)
        header_layout.addStretch()
        header_layout.addWidget(self.status_label)
        main_layout.addLayout(header_layout)
        self.stack = QStackedWidget()
        main_layout.addWidget(self.stack)
        self._create_selection_view()
        self._create_summary_view()
        self._create_metadata_editor_view()
        self.refresh_state()

    def _create_selection_view(self):
        widget = QWidget()
        controls_layout = QHBoxLayout(widget)
        info_group = QGroupBox("Source Info")
        info_layout = QVBoxLayout()
        self.metadata_video_label = QLabel("Video: N/A")
        self.metadata_audio_label = QLabel("Audio: N/A")
        self.metadata_size_label = QLabel("Size: 0.00 GB")
        self.remux_checkbox = QCheckBox("Use Fast Remux (Copy)")
        info_layout.addWidget(self.metadata_video_label)
        info_layout.addWidget(self.metadata_audio_label)
        info_layout.addWidget(self.metadata_size_label)
        info_layout.addSpacing(10)
        info_layout.addWidget(self.remux_checkbox)
        info_group.setLayout(info_layout)
        tools_group = QGroupBox("Tools")
        tools_layout = QVBoxLayout()
        self.rename_btn = QPushButton("✏️ Rename File...")
        self.preview_sub_btn = QPushButton("🔍 Preview Snippet...")
        self.edit_sub_btn = QPushButton("✂️ Edit/Remove Tracks...")
        tools_layout.addWidget(self.rename_btn)
        tools_layout.addWidget(self.preview_sub_btn)
        tools_layout.addWidget(self.edit_sub_btn)
        tools_group.setLayout(tools_layout)
        selection_group = QGroupBox("Subtitle Selection")
        selection_layout = QVBoxLayout()
        burn_in_layout = QVBoxLayout()
        burn_in_layout.addWidget(QLabel("<b>Burn-in Subtitle:</b>"))
        self.burn_combo = QComboBox()
        burn_in_layout.addWidget(self.burn_combo)
        self.soft_copy_layout = QVBoxLayout()
        self.soft_copy_layout.setContentsMargins(0, 5, 0, 0)
        self.soft_copy_layout.addWidget(QLabel("<b>Copy Subtitles (Softsub):</b>"))
        selection_layout.addLayout(burn_in_layout)
        selection_layout.addLayout(self.soft_copy_layout)
        selection_group.setLayout(selection_layout)
        profile_group = QGroupBox("📊 Conversion Profile")
        profile_layout = QVBoxLayout()
        self.profile_video_label = QLabel("Video: N/A")
        self.profile_audio_label = QLabel("Audio: N/A")
        self.profile_burn_label = QLabel("Burn-in: None")
        self.profile_copy_label = QLabel("Copy Subs: None")
        profile_layout.addWidget(self.profile_video_label)
        profile_layout.addWidget(self.profile_audio_label)
        profile_layout.addWidget(self.profile_burn_label)
        profile_layout.addWidget(self.profile_copy_label)
        profile_group.setLayout(profile_layout)
        controls_layout.addWidget(info_group)
        controls_layout.addWidget(tools_group)
        controls_layout.addWidget(selection_group, 1)
        controls_layout.addWidget(profile_group, 1)
        self.stack.addWidget(widget)
        self.burn_combo.currentIndexChanged.connect(self.update_conversion_profile_summary)
        self.remux_checkbox.stateChanged.connect(self.update_conversion_profile_summary)
        self.rename_btn.clicked.connect(self.open_rename_dialog)
        self.preview_sub_btn.clicked.connect(self.open_subtitle_preview)
        self.edit_sub_btn.clicked.connect(self.open_subtitle_editor)

    def open_rename_dialog(self):
        dialog = RenameDialog(self.media_file.output_filename, getattr(self.media_file, 'title', self.media_file.source_path.stem), self)
        if names := dialog.get_names():
            self.media_file.output_filename, self.media_file.title = names
            self.refresh_state()

    def open_subtitle_preview(self):
        dialog = SubtitlePreviewDialog(self.media_file, self)
        dialog.exec()

    def open_subtitle_editor(self):
        dialog = SubtitleEditorDialog(self.media_file, self)
        dialog.track_modified.connect(self.dashboard_ref.refresh_list_item_by_widget)
        dialog.exec()

    def _create_summary_view(self):
        widget = QWidget(); summary_layout = QHBoxLayout(widget)
        self.orig_size_label, self.new_size_label, self.size_change_label, self.audio_details_label, self.subs_details_label = QLabel(), QLabel(), QLabel(), QLabel(), QLabel()
        for label in [self.orig_size_label, self.new_size_label, self.size_change_label, self.audio_details_label, self.subs_details_label]:
            summary_layout.addWidget(label); summary_layout.addStretch()
        self.stack.addWidget(widget)

    def _create_metadata_editor_view(self):
        widget = QWidget()
        main_editor_layout = QVBoxLayout(widget)
        preview_group = QGroupBox("Conversion Plan Preview")
        preview_layout = QVBoxLayout()
        self.preview_display = QTextEdit()
        self.preview_display.setReadOnly(True)
        self.preview_display.setMinimumHeight(150)
        preview_layout.addWidget(self.preview_display)
        self.back_to_controls_btn = QPushButton("Back to Controls")
        self.back_to_controls_btn.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        preview_layout.addWidget(self.back_to_controls_btn, 0, Qt.AlignmentFlag.AlignRight)
        preview_group.setLayout(preview_layout)
        main_editor_layout.addWidget(preview_group)
        self.stack.addWidget(widget)

    def show_conversion_preview(self, switch_to_view=True):
        self.update_media_file_from_ui()
        settings = self.dashboard_ref.get_current_settings()
        preview_text = self.media_file.generate_preview(settings)
        self.preview_display.setText(preview_text)
        if switch_to_view:
            self.stack.setCurrentIndex(2)

    def refresh_state(self):
        new_title = getattr(self.media_file, 'title', self.media_file.filename)
        self.filename_label.setText(f"<b>{new_title}</b> → <i>{self.media_file.output_filename}</i>")
        self.status_label.setText(f"Status: {self.media_file.status}")
        
        if self.media_file.status in ["Converted", "Transferred", "Skipped (Exists)", "Converted (Basic)"]:
            self.orig_size_label.setText(f"Original: {self.media_file.original_size_gb:.2f} GB"); self.new_size_label.setText(f"Converted: {self.media_file.converted_size_gb:.2f} GB")
            self.size_change_label.setText(f"Change: {self.media_file.size_change_percent:+.2f}%"); self.audio_details_label.setText(f"Audio: {getattr(self.media_file, 'audio_conversion_details', 'N/A')}")
            burned_sub = next((s.title or f"Track {s.index}" for s in self.media_file.subtitle_tracks if s.action == 'burn'), "None")
            copied_subs = ", ".join([s.title or f"Track {s.index}" for s in self.media_file.subtitle_tracks if s.action == 'copy']) or "None"
            self.subs_details_label.setText(f"Subs Burned: {burned_sub} | Copied: {copied_subs}"); self.stack.setCurrentIndex(1)
        else:
            self.metadata_video_label.setText(f"Video: {self.media_file.video_codec}, {self.media_file.video_width}p")
            self.metadata_audio_label.setText(f"Audio: {self.media_file.audio_codec}, {self.media_file.audio_channels}ch")
            self.metadata_size_label.setText(f"Size: {self.media_file.original_size_gb:.2f} GB")
            self.populate_selection_controls()
            self.update_conversion_profile_summary()
            self.stack.setCurrentIndex(0)

    def populate_selection_controls(self):
        self.burn_combo.blockSignals(True)
        self.burn_combo.clear(); self.burn_combo.addItem("None", None)
        for track in self.media_file.subtitle_tracks:
            self.burn_combo.addItem(track.get_display_name(), track)
            if self.media_file.burned_subtitle and self.media_file.burned_subtitle.index == track.index: self.burn_combo.setCurrentIndex(self.burn_combo.count() - 1)
        self.burn_combo.blockSignals(False)
        
        while self.soft_copy_layout.count() > 1:
            child = self.soft_copy_layout.takeAt(1)
            if child.widget(): child.widget().deleteLater()
        
        self.soft_copy_checkboxes = []
        
        for track in self.media_file.subtitle_tracks:
            if track.is_text_based:
                cb = QCheckBox(track.get_display_name()); cb.setProperty("track", track);
                cb.stateChanged.connect(self.update_conversion_profile_summary)
                self.soft_copy_checkboxes.append(cb); self.soft_copy_layout.addWidget(cb)

    def update_conversion_profile_summary(self):
        settings = self.dashboard_ref.get_current_settings()
        video_action = "Copy (Remux)"
        if self.remux_checkbox.isChecked():
            video_action = "Copy (Fast Remux)"
        elif self.burn_combo.currentData() is not None:
             video_action = f"Re-encode to {settings.video_codec.upper()}"
        self.profile_video_label.setText(f"Video: {video_action}")

        compatible_audio = ['aac', 'ac3', 'eac3']
        if self.remux_checkbox.isChecked() or (self.media_file.audio_codec and self.media_file.audio_codec.lower() in compatible_audio):
             audio_action = f"Copy existing {self.media_file.audio_codec.upper()}"
        else:
            audio_action = f"Re-encode to {settings.audio_codec.upper()}"
        self.profile_audio_label.setText(f"Audio: {audio_action}")

        burned_track = self.burn_combo.currentData()
        self.profile_burn_label.setText(f"Burn-in: {burned_track.get_display_name() if burned_track else 'None'}")
        
        copied_subs = [cb.text() for cb in self.soft_copy_checkboxes if cb.isChecked()]
        self.profile_copy_label.setText(f"Copy Subs: {len(copied_subs)} track(s)")

    def update_media_file_from_ui(self):
        if self.remux_checkbox.isChecked():
            self.media_file.use_basic_conversion = True
        else:
            self.media_file.use_basic_conversion = (self.media_file.classify() == 'remux')

        selected_burn_track = self.burn_combo.currentData(); self.media_file.burned_subtitle = selected_burn_track;
        for track in self.media_file.subtitle_tracks: track.action = "ignore"
        if selected_burn_track: selected_burn_track.action = "burn"
        for cb in self.soft_copy_checkboxes:
            track_data = cb.property("track")
            if cb.isChecked() and track_data:
                if not (selected_burn_track and selected_burn_track.index == track_data.index): track_data.action = "copy"

class Dashboard(QWidget):
    def __init__(self):
        super().__init__(); self.setWindowTitle("Media Conversion Dashboard"); self.setGeometry(100, 100, 1400, 800)
        self.media_files_data: List[MediaFile] = []; self.thread = None; self.worker = None
        self.config_handler = ConfigHandler(); self.layout = QVBoxLayout(self)
        top_controls = QHBoxLayout(); self.scan_config_button = QPushButton("Scan Configured", clicked=self.scan_configured_folders)
        self.scan_custom_button = QPushButton("Scan Custom...", clicked=self.scan_custom_folder); self.settings_button = QPushButton("Settings", clicked=self.open_settings)
        top_controls.addWidget(self.scan_config_button); top_controls.addWidget(self.scan_custom_button); top_controls.addStretch(); top_controls.addWidget(self.settings_button); self.layout.addLayout(top_controls)
        self.file_list = QListWidget(); self.file_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.layout.addWidget(self.file_list, 1)
        self.bottom_button_stack = QStackedWidget(); self._create_normal_buttons()
        self.layout.addWidget(self.bottom_button_stack)
        self.status_bar = QStatusBar(); self.layout.addWidget(self.status_bar); self.status_bar.showMessage("Ready.")

    def _create_normal_buttons(self):
        normal_widget = QWidget(); bottom_controls = QHBoxLayout(normal_widget)
        self.progress_bar = QProgressBar(); self.progress_bar.setVisible(False)
        self.preview_plan_button = QPushButton("🎛️ Preview Conversion Plan", clicked=self.show_conversion_plan_preview)
        self.convert_button = QPushButton("Convert Selected", clicked=self.start_conversion)
        self.transfer_button = QPushButton("Transfer Converted", clicked=self.start_transfer)
        self.cancel_button = QPushButton("Cancel", clicked=self.cancel_task); self.cancel_button.setEnabled(False)
        bottom_controls.addWidget(self.progress_bar, 1)
        bottom_controls.addWidget(self.preview_plan_button)
        bottom_controls.addWidget(self.convert_button)
        bottom_controls.addWidget(self.transfer_button); bottom_controls.addWidget(self.cancel_button)
        self.bottom_button_stack.addWidget(normal_widget)

    def _run_task(self, task_function: Callable, on_finish: Callable, *args, **kwargs):
        self.set_buttons_enabled(False); self.status_bar.showMessage(f"Running {task_function.__name__}...")
        self.thread = QThread(); self.worker = Worker(task_function, *args, **kwargs); self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run); self.worker.progress.connect(self.update_progress); self.worker.finished.connect(on_finish); self.worker.error.connect(self.on_task_error)
        self.worker.finished.connect(self.thread.quit); self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater); self.thread.finished.connect(lambda: self.set_buttons_enabled(True))
        self.thread.start()

    def set_buttons_enabled(self, enabled: bool):
        self.scan_config_button.setEnabled(enabled); self.scan_custom_button.setEnabled(enabled)
        self.settings_button.setEnabled(enabled); self.convert_button.setEnabled(enabled)
        self.preview_plan_button.setEnabled(enabled)
        self.transfer_button.setEnabled(enabled)
        self.progress_bar.setVisible(not enabled); self.cancel_button.setEnabled(not enabled)

    def update_progress(self, percent: int, status: str):
        self.progress_bar.setFormat(f"{status} - %p%"); self.progress_bar.setValue(percent)
    def cancel_task(self):
        if self.worker: self.status_bar.showMessage("Cancellation requested...")
    def open_settings(self): SettingsWindow(self.config_handler, self).exec()
    def _scan_multiple_dirs(self, dir_paths: List[Path]) -> List[MediaFile]:
        return [mf for dir_path in dir_paths for mf in subtitlesmkv.scan_directory(dir_path)]
    def scan_configured_folders(self):
        if not (dirs := self.config_handler.get_setting("scan_directories")): self.show_message("No Directories", "Add scan directories in Settings."); return
        self._run_task(self._scan_multiple_dirs, self.on_scan_finished, [Path(d) for d in dirs])
    def scan_custom_folder(self):
        if folder := QFileDialog.getExistingDirectory(self, "Select Folder"): self._run_task(self._scan_multiple_dirs, self.on_scan_finished, [Path(folder)])
    def on_scan_finished(self, result: List[MediaFile]):
        self.media_files_data = result; self.populate_file_list(); self.status_bar.showMessage(f"Scan complete. Found {len(result)} files.")
    def populate_file_list(self):
        self.file_list.clear()
        for media_file in self.media_files_data:
            item_widget = MediaFileItemWidget(media_file, self); list_item = QListWidgetItem(self.file_list)
            list_item.setData(Qt.ItemDataRole.UserRole, media_file); list_item.setSizeHint(item_widget.sizeHint())
            self.file_list.addItem(list_item); self.file_list.setItemWidget(list_item, item_widget)
    def get_selected_media_files(self) -> List[MediaFile]:
        selected_items = self.file_list.selectedItems()
        if not selected_items:
             return [self.file_list.itemWidget(self.file_list.item(i)).media_file for i in range(self.file_list.count())]
        return [self.file_list.itemWidget(item).media_file for item in selected_items]

    def _run_combined_conversion(self, files: List[MediaFile], settings: ConversionSettings, progress_callback: Callable):
        for f in files:
            self.file_list.itemWidget(self.find_list_item(f)).update_media_file_from_ui()
        
        basic_files = [f for f in files if f.use_basic_conversion]
        advanced_files = [f for f in files if not f.use_basic_conversion]

        if basic_files:
            basic_convert.run_batch_basic_conversion(basic_files, settings)
        
        if advanced_files:
            convert.convert_batch(advanced_files, settings, progress_callback)
        return files

    def start_conversion(self):
        files = self.get_selected_media_files();
        if not files: self.show_message("No Files", "No files to convert."); return
        settings = self.get_current_settings()
        try: settings.output_directory.mkdir(parents=True, exist_ok=True)
        except Exception as e: self.show_message("Error", f"Could not create output directory.\n{e}"); return
        self.progress_bar.setFormat("%p%")
        self._run_task(self._run_combined_conversion, self.on_action_finished, files=files, settings=settings)

    def show_conversion_plan_preview(self):
        selected_items = self.file_list.selectedItems()
        if not selected_items:
            self.show_message("No File Selected", "Please select a file to preview its conversion plan.")
            return
        widget = self.file_list.itemWidget(selected_items[0])
        if widget:
            widget.show_conversion_preview(switch_to_view=True)

    def get_current_settings(self) -> ConversionSettings:
        return ConversionSettings(
            output_directory=Path(self.config_handler.get_setting("output_directory")), use_nvenc=self.config_handler.get_setting("use_nvenc"),
            crf=self.config_handler.get_setting("crf_value"), delete_source_on_success=self.config_handler.get_setting("delete_source_on_success"),
            use_two_pass=self.config_handler.get_setting("use_two_pass"))

    def start_transfer(self):
        files_to_move = [mf for mf in self.media_files_data if mf.status in ["Converted", "Converted (Basic)"]];
        if not files_to_move: self.show_message("No Files", "No successfully converted files to transfer."); return
        self._run_task(robocopy.move_all_mp4s, self.on_action_finished, files_to_move)

    def on_action_finished(self, result: List[MediaFile]):
        self.refresh_ui(); self.status_bar.showMessage("Task finished successfully.")

    def find_list_item(self, media_file: MediaFile) -> QListWidgetItem | None:
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == media_file: return item
        return None

    def refresh_ui(self):
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            widget = self.file_list.itemWidget(item)
            if widget:
                widget.refresh_state()

    def refresh_list_item_by_widget(self, widget: MediaFileItemWidget):
        if not widget: return
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if self.file_list.itemWidget(item) == widget:
                self.refresh_list_item(item)
                break

    def refresh_list_item(self, item: QListWidgetItem):
        widget = self.file_list.itemWidget(item)
        if widget:
            new_media_file_state = subtitlesmkv.scan_file(widget.media_file.source_path)
            for i, mf in enumerate(self.media_files_data):
                if mf.source_path == new_media_file_state.source_path:
                    new_media_file_state.output_filename = mf.output_filename
                    new_media_file_state.title = getattr(mf, 'title', None)
                    self.media_files_data[i] = new_media_file_state
                    break
            item.setData(Qt.ItemDataRole.UserRole, new_media_file_state)
            widget.media_file = new_media_file_state
            widget.refresh_state()

    def on_task_error(self, error: Tuple):
        self.status_bar.showMessage(f"Error occurred: {error[1]}", 10000); advice = "\n\nAdvice: Missing output directory?" if "No such file or directory" in str(error[1]) else ""
        self.show_message("Error", f"Task failed:\n{error[1]}{advice}"); print(error[2])
    def show_message(self, title: str, message: str):
        msg_box = QMessageBox(self); msg_box.setWindowTitle(title); msg_box.setText(message); msg_box.exec()

if __name__ == "__main__":
    app = QApplication(sys.argv)

    try:
        style_file = Path("styles.qss")
        if not style_file.exists():
            style_file = Path("styles.css")

        if style_file.exists():
            with open(style_file, "r") as f: app.setStyleSheet(f.read())
        else:
            app.setStyle("Fusion")
    except Exception as e:
        print(f"Could not load stylesheet: {e}"); app.setStyle("Fusion")

    dashboard = Dashboard()
    dashboard.show()
    sys.exit(app.exec())