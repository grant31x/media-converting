# dashboard.py
# Version: 2.2
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
        super().__init__(parent); self.config_handler = config_handler; self.setWindowTitle("Settings"); self.setMinimumWidth(500); self.layout = QVBoxLayout(self)
        conv_group = QGroupBox("Conversion Settings"); conv_layout = QVBoxLayout(); self.nvenc_checkbox = QCheckBox("Use NVIDIA NVENC Hardware Acceleration"); self.two_pass_checkbox = QCheckBox("Use Smart 2-Pass Encoding (for quality and size control)"); self.delete_source_checkbox = QCheckBox("Delete original file after successful conversion")
        crf_layout = QHBoxLayout(); crf_layout.addWidget(QLabel("Video Quality (CRF, lower is better):")); self.crf_spinbox = QSpinBox(); self.crf_spinbox.setRange(0, 51); crf_layout.addWidget(self.crf_spinbox)
        conv_layout.addWidget(self.nvenc_checkbox); conv_layout.addWidget(self.two_pass_checkbox); conv_layout.addWidget(self.delete_source_checkbox); conv_layout.addLayout(crf_layout); conv_group.setLayout(conv_layout); self.layout.addWidget(conv_group)
        self.layout.addWidget(QLabel("Default Output Directory:")); output_dir_layout = QHBoxLayout(); self.output_dir_edit = QLineEdit(); self.browse_output_btn = QPushButton("Browse..."); output_dir_layout.addWidget(self.output_dir_edit); output_dir_layout.addWidget(self.browse_output_btn); self.layout.addLayout(output_dir_layout)
        self.dir_list_widget = QListWidget(); self.layout.addWidget(QLabel("Scan Directories:")); self.layout.addWidget(self.dir_list_widget); btn_layout = QHBoxLayout(); self.add_btn = QPushButton("Add Scan Directory..."); self.remove_btn = QPushButton("Remove Selected"); btn_layout.addWidget(self.add_btn); btn_layout.addWidget(self.remove_btn); self.layout.addLayout(btn_layout)
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel); self.layout.addWidget(self.button_box)
        self.browse_output_btn.clicked.connect(lambda: self.browse_directory(self.output_dir_edit)); self.add_btn.clicked.connect(self.add_scan_directory); self.remove_btn.clicked.connect(lambda: self.dir_list_widget.takeItem(self.dir_list_widget.currentRow())); self.button_box.accepted.connect(self.save_and_accept); self.button_box.rejected.connect(self.reject); self.load_settings()
    def load_settings(self):
        self.nvenc_checkbox.setChecked(self.config_handler.get_setting("use_nvenc", True)); self.two_pass_checkbox.setChecked(self.config_handler.get_setting("use_two_pass", True)); self.delete_source_checkbox.setChecked(self.config_handler.get_setting("delete_source_on_success", False)); self.crf_spinbox.setValue(self.config_handler.get_setting("crf_value", 23)); self.output_dir_edit.setText(self.config_handler.get_setting("output_directory"))
        self.dir_list_widget.clear(); self.dir_list_widget.addItems(self.config_handler.get_setting("scan_directories", []))
    def browse_directory(self, line_edit: QLineEdit):
        if folder := QFileDialog.getExistingDirectory(self, "Select Directory"): line_edit.setText(folder)
    def add_scan_directory(self):
        if folder := QFileDialog.getExistingDirectory(self, "Select Scan Directory"): self.dir_list_widget.addItem(folder)
    def save_and_accept(self):
        self.config_handler.set_setting("use_nvenc", self.nvenc_checkbox.isChecked()); self.config_handler.set_setting("use_two_pass", self.two_pass_checkbox.isChecked()); self.config_handler.set_setting("delete_source_on_success", self.delete_source_checkbox.isChecked()); self.config_handler.set_setting("crf_value", self.crf_spinbox.value()); self.config_handler.set_setting("output_directory", self.output_dir_edit.text())
        self.config_handler.set_setting("scan_directories", [self.dir_list_widget.item(i).text() for i in range(self.dir_list_widget.count())]); self.config_handler.save_config(); self.accept()

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
    track_modified = pyqtSignal() 
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
        if success: self.track_modified.emit(); self.accept()
        else: QMessageBox.critical(self, "Error", "Failed to modify the MKV file. Check the console for details."); self.delete_button.setEnabled(True)
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
        super().__init__(); self.media_file = media_file; self.dashboard_ref = dashboard_ref; self.setObjectName("MediaFileItemWidget") 
        main_layout = QVBoxLayout(self); main_layout.setContentsMargins(5, 5, 5, 5)
        header_layout = QHBoxLayout(); self.filename_label = QLabel(); self.status_label = QLabel()
        header_layout.addWidget(self.filename_label); header_layout.addStretch(); header_layout.addWidget(self.status_label)
        main_layout.addLayout(header_layout)
        self.stack = QStackedWidget(); main_layout.addWidget(self.stack)
        self._create_selection_view(); self._create_summary_view(); self._create_metadata_editor_view()
        self.refresh_state()
        
    def _create_selection_view(self):
        widget = QWidget()
        controls_layout = QHBoxLayout(widget)
        
        # FIX: Remove the QGroupBox for a more compact layout
        burn_in_layout = QVBoxLayout()
        burn_in_layout.addWidget(QLabel("<b>Burn-in Subtitle:</b>"))
        self.burn_combo = QComboBox()
        burn_in_layout.addWidget(self.burn_combo)
        burn_in_layout.addStretch() # Pushes the combo box to the top, keeping the layout tight
        
        soft_copy_group = QGroupBox("Copy Subtitles (Softsub)")
        self.soft_copy_layout = QVBoxLayout()
        soft_copy_group.setLayout(self.soft_copy_layout)

        controls_layout.addLayout(burn_in_layout, 1) # Give it a stretch factor of 1
        controls_layout.addWidget(soft_copy_group, 2) # Give the copy box more horizontal space
        self.stack.addWidget(widget)

    def _create_summary_view(self):
        widget = QWidget(); summary_layout = QHBoxLayout(widget)
        self.orig_size_label, self.new_size_label, self.size_change_label, self.audio_details_label, self.subs_details_label = QLabel(), QLabel(), QLabel(), QLabel(), QLabel()
        for label in [self.orig_size_label, self.new_size_label, self.size_change_label, self.audio_details_label, self.subs_details_label]:
            summary_layout.addWidget(label); summary_layout.addStretch()
        self.stack.addWidget(widget)
    def _create_metadata_editor_view(self):
        widget = QWidget(); main_editor_layout = QVBoxLayout(widget)
        metadata_group = QGroupBox("Metadata"); editor_layout = QHBoxLayout(); 
        self.title_edit, self.season_edit, self.episode_edit = QLineEdit(), QSpinBox(), QSpinBox()
        self.media_type_combo = QComboBox(); self.media_type_combo.addItems(["Movie", "TV Show"])
        editor_layout.addWidget(QLabel("Title:")); editor_layout.addWidget(self.title_edit, 1); editor_layout.addWidget(QLabel("Type:")); editor_layout.addWidget(self.media_type_combo)
        editor_layout.addWidget(QLabel("Season:")); editor_layout.addWidget(self.season_edit); editor_layout.addWidget(QLabel("Episode:")); editor_layout.addWidget(self.episode_edit)
        metadata_group.setLayout(editor_layout); main_editor_layout.addWidget(metadata_group)
        preview_group = QGroupBox("Conversion Plan Preview"); preview_layout = QVBoxLayout()
        self.preview_display = QTextEdit(); self.preview_display.setReadOnly(True); self.preview_display.setMinimumHeight(150)
        self.generate_preview_btn = QPushButton("Generate/Update Preview"); self.generate_preview_btn.clicked.connect(self.show_conversion_preview)
        preview_layout.addWidget(self.preview_display); preview_layout.addWidget(self.generate_preview_btn, 0, Qt.AlignmentFlag.AlignRight)
        preview_group.setLayout(preview_layout); main_editor_layout.addWidget(preview_group)
        self.stack.addWidget(widget)
    def show_conversion_preview(self):
        self.update_media_file_from_ui(); settings = self.dashboard_ref.get_current_settings()
        preview_text = self.media_file.generate_preview(settings); self.preview_display.setText(preview_text)
    def refresh_state(self):
        new_title = getattr(self.media_file, 'title', self.media_file.filename); self.filename_label.setText(f"<b>{new_title}</b>"); self.status_label.setText(f"Status: {self.media_file.status}")
        # The checkbox has been removed, so this line is no longer needed.
        # self.basic_conv_checkbox.setChecked(self.media_file.use_basic_conversion) 
        if getattr(self.media_file, 'is_editing_metadata', False):
            self.title_edit.setText(getattr(self.media_file, 'title', self.media_file.source_path.stem)); self.media_type_combo.setCurrentText(getattr(self.media_file, 'media_type', 'Movie'))
            self.season_edit.setValue(getattr(self.media_file, 'season', 0)); self.episode_edit.setValue(getattr(self.media_file, 'episode', 0)); self.stack.setCurrentIndex(2)
        elif self.media_file.status in ["Converted", "Transferred", "Skipped (Exists)", "Converted (Basic)"]:
            self.orig_size_label.setText(f"Original: {self.media_file.original_size_gb:.2f} GB"); self.new_size_label.setText(f"Converted: {self.media_file.converted_size_gb:.2f} GB")
            self.size_change_label.setText(f"Change: {self.media_file.size_change_percent:+.2f}%"); self.audio_details_label.setText(f"Audio: {getattr(self.media_file, 'audio_conversion_details', 'N/A')}")
            burned_sub = next((s.title or f"Track {s.index}" for s in self.media_file.subtitle_tracks if s.action == 'burn'), "None")
            copied_subs = ", ".join([s.title or f"Track {s.index}" for s in self.media_file.subtitle_tracks if s.action == 'copy']) or "None"
            self.subs_details_label.setText(f"Subs Burned: {burned_sub} | Copied: {copied_subs}"); self.stack.setCurrentIndex(1)
        else:
            self.populate_selection_controls(); self.stack.setCurrentIndex(0)
    def populate_selection_controls(self):
        self.burn_combo.clear(); self.burn_combo.addItem("None", None)
        for track in self.media_file.subtitle_tracks:
            self.burn_combo.addItem(track.get_display_name(), track)
            if self.media_file.burned_subtitle and self.media_file.burned_subtitle.index == track.index: self.burn_combo.setCurrentIndex(self.burn_combo.count() - 1)
        while True:
            child = self.soft_copy_layout.takeAt(0)
            if not child: break
            if child.widget(): child.widget().deleteLater()
        self.soft_copy_checkboxes: list[QCheckBox] = []
        for track in self.media_file.subtitle_tracks:
            if track.is_text_based: cb = QCheckBox(track.get_display_name()); cb.setProperty("track", track); self.soft_copy_checkboxes.append(cb); self.soft_copy_layout.addWidget(cb)
    def update_media_file_from_ui(self):
        # Auto-classification replaces the manual checkbox
        self.media_file.use_basic_conversion = (self.media_file.classify() == 'remux')
        if self.stack.currentIndex() == 0:
            selected_burn_track = self.burn_combo.currentData(); self.media_file.burned_subtitle = selected_burn_track;
            for track in self.media_file.subtitle_tracks: track.action = "ignore"
            if selected_burn_track: selected_burn_track.action = "burn"
            for cb in self.soft_copy_checkboxes:
                track_data = cb.property("track")
                if cb.isChecked() and track_data:
                    if not (selected_burn_track and selected_burn_track.index == track_data.index): track_data.action = "copy"
        elif self.stack.currentIndex() == 2:
            setattr(self.media_file, 'title', self.title_edit.text()); setattr(self.media_file, 'media_type', self.media_type_combo.currentText())
            setattr(self.media_file, 'season', self.season_edit.value()); setattr(self.media_file, 'episode', self.episode_edit.value())

class Dashboard(QWidget):
    def __init__(self):
        super().__init__(); self.setWindowTitle("Media Conversion Dashboard"); self.setGeometry(100, 100, 1200, 800)
        self.media_files_data: List[MediaFile] = []; self.thread = None; self.worker = None; self.is_editing_mode = False
        self.config_handler = ConfigHandler(); self.layout = QVBoxLayout(self)
        top_controls = QHBoxLayout(); self.scan_config_button = QPushButton("Scan Configured", clicked=self.scan_configured_folders)
        self.scan_custom_button = QPushButton("Scan Custom...", clicked=self.scan_custom_folder); self.settings_button = QPushButton("Settings", clicked=self.open_settings)
        top_controls.addWidget(self.scan_config_button); top_controls.addWidget(self.scan_custom_button); top_controls.addStretch(); top_controls.addWidget(self.settings_button); self.layout.addLayout(top_controls)
        self.file_list = QListWidget(); self.file_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.file_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); self.file_list.customContextMenuRequested.connect(self.show_context_menu)
        self.layout.addWidget(self.file_list, 1)
        self.bottom_button_stack = QStackedWidget(); self._create_normal_buttons(); self._create_edit_mode_buttons()
        self.layout.addWidget(self.bottom_button_stack)
        self.status_bar = QStatusBar(); self.layout.addWidget(self.status_bar); self.status_bar.showMessage("Ready.")
    def _create_normal_buttons(self):
        normal_widget = QWidget(); bottom_controls = QHBoxLayout(normal_widget)
        self.progress_bar = QProgressBar(); self.progress_bar.setVisible(False)
        self.convert_button = QPushButton("Convert Selected", clicked=self.start_conversion)
        self.edit_metadata_button = QPushButton("Edit Metadata", clicked=self.enter_edit_mode)
        self.transfer_button = QPushButton("Transfer Converted", clicked=self.start_transfer)
        self.cancel_button = QPushButton("Cancel", clicked=self.cancel_task); self.cancel_button.setEnabled(False) 
        bottom_controls.addWidget(self.progress_bar, 1); bottom_controls.addWidget(self.convert_button)
        bottom_controls.addWidget(self.edit_metadata_button); bottom_controls.addWidget(self.transfer_button); bottom_controls.addWidget(self.cancel_button)
        self.bottom_button_stack.addWidget(normal_widget)
    def _create_edit_mode_buttons(self):
        edit_widget = QWidget(); edit_controls = QHBoxLayout(edit_widget)
        edit_controls.addStretch(); self.save_metadata_button = QPushButton("Save Metadata", clicked=self.save_metadata)
        self.cancel_edit_button = QPushButton("Cancel Edit", clicked=self.exit_edit_mode)
        edit_controls.addWidget(self.save_metadata_button); edit_controls.addWidget(self.cancel_edit_button)
        self.bottom_button_stack.addWidget(edit_widget)
    def _run_task(self, task_function: Callable, on_finish: Callable, *args, **kwargs):
        self.set_buttons_enabled(False); self.status_bar.showMessage(f"Running {task_function.__name__}...")
        self.thread = QThread(); self.worker = Worker(task_function, *args, **kwargs); self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run); self.worker.progress.connect(self.update_progress); self.worker.finished.connect(on_finish); self.worker.error.connect(self.on_task_error)
        self.worker.finished.connect(self.thread.quit); self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater); self.thread.finished.connect(lambda: self.set_buttons_enabled(True))
        self.thread.start()
    def set_buttons_enabled(self, enabled: bool):
        is_editing = self.bottom_button_stack.currentIndex() == 1
        self.scan_config_button.setEnabled(enabled and not is_editing); self.scan_custom_button.setEnabled(enabled and not is_editing)
        self.settings_button.setEnabled(enabled and not is_editing); self.convert_button.setEnabled(enabled and not is_editing)
        self.edit_metadata_button.setEnabled(enabled and not is_editing); self.transfer_button.setEnabled(enabled and not is_editing)
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
        items = self.file_list.selectedItems() or [self.file_list.item(i) for i in range(self.file_list.count())]
        return [self.file_list.itemWidget(item).media_file for item in items]
    def _run_combined_conversion(self, files: List[MediaFile], settings: ConversionSettings, progress_callback: Callable):
        for f in files: f.use_basic_conversion = (f.classify() == 'remux')
        basic_files = [f for f in files if f.use_basic_conversion]
        advanced_files = [f for f in files if not f.use_basic_conversion]
        if basic_files:
            for file in basic_files: basic_convert.run_basic_conversion(file, settings)
        if advanced_files:
            convert.convert_batch(advanced_files, settings, progress_callback)
        return files
    def start_conversion(self):
        files = self.get_selected_media_files();
        if not files: self.show_message("No Files", "No files to convert."); return
        for f in files: self.file_list.itemWidget(self.find_list_item(f)).update_media_file_from_ui()
        settings = self.get_current_settings()
        try: settings.output_directory.mkdir(parents=True, exist_ok=True)
        except Exception as e: self.show_message("Error", f"Could not create output directory.\n{e}"); return
        self.progress_bar.setFormat("%p%") 
        self._run_task(self._run_combined_conversion, self.on_action_finished, files=files, settings=settings)
    def get_current_settings(self) -> ConversionSettings:
        return ConversionSettings(
            output_directory=Path(self.config_handler.get_setting("output_directory")), use_nvenc=self.config_handler.get_setting("use_nvenc"),
            crf=self.config_handler.get_setting("crf_value"), delete_source_on_success=self.config_handler.get_setting("delete_source_on_success"),
            use_two_pass=self.config_handler.get_setting("use_two_pass"))
    def enter_edit_mode(self):
        files_to_edit = self.get_selected_media_files();
        if not files_to_edit: self.show_message("No Selection", "Select files to edit metadata for."); return
        self.is_editing_mode = True; self.bottom_button_stack.setCurrentIndex(1)
        for f in files_to_edit: setattr(f, 'is_editing_metadata', True)
        self.refresh_ui()
    def save_metadata(self):
        for f in self.get_selected_media_files():
            self.file_list.itemWidget(self.find_list_item(f)).update_media_file_from_ui()
            setattr(f, 'is_editing_metadata', False)
        self.exit_edit_mode()
    def exit_edit_mode(self):
        self.is_editing_mode = False
        for f in self.get_selected_media_files(): setattr(f, 'is_editing_metadata', False)
        self.bottom_button_stack.setCurrentIndex(0)
        self.refresh_ui()
    def start_transfer(self):
        files_to_move = [mf for mf in self.media_files_data if mf.status in ["Converted", "Converted (Basic)"]];
        if not files_to_move: self.show_message("No Files", "No successfully converted files to transfer."); return
        for f in files_to_move:
            if not hasattr(f, 'media_type'):
                setattr(f, 'media_type', "TV Show" if re.search(r'[sS]\d{2}[eE]\d{2}', f.filename) else "Movie"); setattr(f, 'title', f.source_path.stem)
                if f.media_type == "TV Show":
                    if match := re.search(r'[sS](\d{2})[eE](\d{2})', f.filename): setattr(f, 'season', int(match.group(1))); setattr(f, 'episode', int(match.group(2)))
            setattr(f, 'is_editing_metadata', False)
        self.refresh_ui(); self._run_task(robocopy.move_batch, self.on_action_finished, files_to_move)
    def on_action_finished(self, result: List[MediaFile]):
        self.refresh_ui(); self.status_bar.showMessage("Task finished successfully.")
    def find_list_item(self, media_file: MediaFile) -> QListWidgetItem | None:
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == media_file: return item
        return None
    def refresh_ui(self):
        for i in range(self.file_list.count()): widget = self.file_list.itemWidget(self.file_list.item(i)); widget.refresh_state()
    def on_task_error(self, error: Tuple):
        self.status_bar.showMessage(f"Error occurred: {error[1]}", 10000); advice = "\n\nAdvice: Missing output directory?" if "No such file or directory" in str(error[1]) else ""
        self.show_message("Error", f"Task failed:\n{error[1]}{advice}"); print(error[2])
    def show_message(self, title: str, message: str):
        msg_box = QMessageBox(self); msg_box.setWindowTitle(title); msg_box.setText(message); msg_box.exec()
    def show_context_menu(self, position):
        item = self.file_list.itemAt(position)
        if not item: return
        media_file = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu()
        preview_action = menu.addAction("Preview Subtitle Snippet...")
        edit_subs_action = menu.addAction("Edit/Remove Subtitles...")
        action = menu.exec(self.file_list.mapToGlobal(position))
        if action == preview_action:
            SubtitlePreviewDialog(media_file, self).exec()
        elif action == edit_subs_action:
            dialog = SubtitleEditorDialog(media_file, self)
            dialog.track_modified.connect(lambda: self.refresh_list_item(item))
            dialog.exec()
    def refresh_list_item(self, item: QListWidgetItem):
        widget = self.file_list.itemWidget(item)
        if widget:
            new_media_file_state = subtitlesmkv.scan_file(widget.media_file.source_path)
            for i, mf in enumerate(self.media_files_data):
                if mf.source_path == new_media_file_state.source_path:
                    self.media_files_data[i] = new_media_file_state
                    break
            item.setData(Qt.ItemDataRole.UserRole, new_media_file_state)
            widget.media_file = new_media_file_state
            widget.refresh_state()

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
