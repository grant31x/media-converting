# dashboard.py
# This is the main PyQt6 GUI for the media conversion tool.

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
    QStatusBar, QSpinBox
)

# Assumed to be in other files, included here for self-containment
from models import MediaFile, SubtitleTrack, ConversionSettings
import subtitlesmkv
import convert
import robocopy

# ==============================================================================
# In a real project, this class would be in: /utils/config.py
# ==============================================================================
class ConfigHandler:
    """Handles loading and saving application settings to a JSON file."""
    def __init__(self, config_path: str = "config.json"):
        self.config_path = Path(config_path)
        self.config: Dict[str, Any] = {}
        self.default_config = {
            "scan_directories": ["E:/Movies", "E:/TV Shows"],
            "output_directory": "./converted",
            "use_nvenc": True,
            "delete_source_on_success": False,
            "crf_value": 23
        }
        self.load_config()

    def load_config(self):
        if not self.config_path.exists():
            self.config = self.default_config
        else:
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self.config = self.default_config | json.load(f)
            except (json.JSONDecodeError, IOError):
                self.config = self.default_config
        self.save_config()

    def save_config(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4)
        except IOError as e: print(f"Error saving config file: {e}")

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def set_setting(self, key: str, value: Any):
        self.config[key] = value

# ==============================================================================
# In a real project, this class would be in: settings_window.py
# ==============================================================================
class SettingsWindow(QDialog):
    """A dialog window for managing application settings."""
    def __init__(self, config_handler: ConfigHandler, parent=None):
        super().__init__(parent)
        self.config_handler = config_handler
        self.setWindowTitle("Settings")
        self.setMinimumWidth(500)
        self.layout = QVBoxLayout(self)

        conv_group = QGroupBox("Conversion Settings")
        conv_layout = QVBoxLayout()
        self.nvenc_checkbox = QCheckBox("Use NVIDIA NVENC Hardware Acceleration")
        self.delete_source_checkbox = QCheckBox("Delete original file after successful conversion")
        crf_layout = QHBoxLayout()
        crf_layout.addWidget(QLabel("Video Quality (CRF, lower is better):"))
        self.crf_spinbox = QSpinBox()
        self.crf_spinbox.setRange(0, 51)
        crf_layout.addWidget(self.crf_spinbox)
        conv_layout.addWidget(self.nvenc_checkbox)
        conv_layout.addWidget(self.delete_source_checkbox)
        conv_layout.addLayout(crf_layout)
        conv_group.setLayout(conv_layout)
        self.layout.addWidget(conv_group)

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
        btn_layout.addWidget(self.add_btn); btn_layout.addWidget(self.remove_btn)
        self.layout.addLayout(btn_layout)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.layout.addWidget(self.button_box)

        self.browse_output_btn.clicked.connect(lambda: self.browse_directory(self.output_dir_edit))
        self.add_btn.clicked.connect(self.add_scan_directory)
        self.remove_btn.clicked.connect(lambda: self.dir_list_widget.takeItem(self.dir_list_widget.currentRow()))
        self.button_box.accepted.connect(self.save_and_accept)
        self.button_box.rejected.connect(self.reject)
        self.load_settings()

    def load_settings(self):
        self.nvenc_checkbox.setChecked(self.config_handler.get_setting("use_nvenc", True))
        self.delete_source_checkbox.setChecked(self.config_handler.get_setting("delete_source_on_success", False))
        self.crf_spinbox.setValue(self.config_handler.get_setting("crf_value", 23))
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
        self.config_handler.set_setting("delete_source_on_success", self.delete_source_checkbox.isChecked())
        self.config_handler.set_setting("crf_value", self.crf_spinbox.value())
        self.config_handler.set_setting("output_directory", self.output_dir_edit.text())
        self.config_handler.set_setting("scan_directories", [self.dir_list_widget.item(i).text() for i in range(self.dir_list_widget.count())])
        self.config_handler.save_config()
        self.accept()

# REBUILT Worker class for simplicity and robustness
class Worker(QObject):
    finished = pyqtSignal(object)
    error = pyqtSignal(tuple)

    def __init__(self, fn: Callable, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.finished.emit(result)
        except Exception as e:
            import traceback
            self.error.emit((type(e), e, traceback.format_exc()))

class MediaFileItemWidget(QFrame):
    def __init__(self, media_file: MediaFile):
        super().__init__()
        self.media_file = media_file
        self.setFrameShape(QFrame.Shape.StyledPanel)
        main_layout = QVBoxLayout(self); main_layout.setContentsMargins(5, 5, 5, 5)
        header_layout = QHBoxLayout()
        self.filename_label = QLabel(f"<b>{self.media_file.filename}</b>")
        self.status_label = QLabel()
        header_layout.addWidget(self.filename_label); header_layout.addStretch(); header_layout.addWidget(self.status_label)
        main_layout.addLayout(header_layout)
        self.stack = QStackedWidget(); main_layout.addWidget(self.stack)
        self._create_selection_view()
        self._create_summary_view()
        self._create_metadata_editor_view()
        self.refresh_state()

    def _create_selection_view(self):
        widget = QWidget(); controls_layout = QHBoxLayout(widget)
        burn_group = QGroupBox("Burn-in Subtitle"); burn_layout = QVBoxLayout(); self.burn_combo = QComboBox()
        burn_layout.addWidget(self.burn_combo); burn_group.setLayout(burn_layout)
        soft_copy_group = QGroupBox("Copy Subtitles"); self.soft_copy_layout = QVBoxLayout()
        soft_copy_group.setLayout(self.soft_copy_layout)
        controls_layout.addWidget(burn_group); controls_layout.addWidget(soft_copy_group)
        self.stack.addWidget(widget)

    def _create_summary_view(self):
        widget = QWidget(); summary_layout = QHBoxLayout(widget)
        self.orig_size_label = QLabel(); self.new_size_label = QLabel()
        self.size_change_label = QLabel(); self.audio_details_label = QLabel()
        self.subs_details_label = QLabel()
        for label in [self.orig_size_label, self.new_size_label, self.size_change_label, self.audio_details_label, self.subs_details_label]:
            summary_layout.addWidget(label); summary_layout.addStretch()
        self.stack.addWidget(widget)

    def _create_metadata_editor_view(self):
        widget = QWidget(); editor_layout = QHBoxLayout(widget)
        self.title_edit = QLineEdit(); self.season_edit = QSpinBox(); self.episode_edit = QSpinBox()
        self.media_type_combo = QComboBox(); self.media_type_combo.addItems(["Movie", "TV Show"])
        editor_layout.addWidget(QLabel("Title:")); editor_layout.addWidget(self.title_edit, 1)
        editor_layout.addWidget(QLabel("Type:")); editor_layout.addWidget(self.media_type_combo)
        editor_layout.addWidget(QLabel("S:")); editor_layout.addWidget(self.season_edit)
        editor_layout.addWidget(QLabel("E:")); editor_layout.addWidget(self.episode_edit)
        self.stack.addWidget(widget)

    def refresh_state(self):
        self.status_label.setText(f"Status: {self.media_file.status}")
        if getattr(self.media_file, 'is_editing_metadata', False):
            self.title_edit.setText(getattr(self.media_file, 'title', self.media_file.source_path.stem))
            self.media_type_combo.setCurrentText(getattr(self.media_file, 'media_type', 'Movie'))
            self.season_edit.setValue(getattr(self.media_file, 'season', 0))
            self.episode_edit.setValue(getattr(self.media_file, 'episode', 0))
            self.stack.setCurrentIndex(2)
        elif self.media_file.status in ["Converted", "Transferred", "Skipped (Exists)"]:
            self.orig_size_label.setText(f"Original: {self.media_file.original_size_mb:.2f} MB")
            self.new_size_label.setText(f"Converted: {self.media_file.converted_size_mb:.2f} MB")
            self.size_change_label.setText(f"Change: {self.media_file.size_change_percent:+.2f}%")
            self.audio_details_label.setText(f"Audio: {getattr(self.media_file, 'audio_conversion_details', 'N/A')}")
            burned_sub = next((s.title or f"Track {s.index}" for s in self.media_file.subtitle_tracks if s.action == 'burn'), "None")
            copied_subs = ", ".join([s.title or f"Track {s.index}" for s in self.media_file.subtitle_tracks if s.action == 'copy']) or "None"
            self.subs_details_label.setText(f"Subs Burned: {burned_sub} | Copied: {copied_subs}")
            self.stack.setCurrentIndex(1)
        else:
            # FIX: Always populate controls when in the selection view
            self.populate_selection_controls()
            self.stack.setCurrentIndex(0)

    def populate_selection_controls(self):
        self.burn_combo.clear(); self.burn_combo.addItem("None", None)
        for track in self.media_file.subtitle_tracks:
            self.burn_combo.addItem(track.get_display_name(), track)
            if self.media_file.burned_subtitle and self.media_file.burned_subtitle.index == track.index:
                self.burn_combo.setCurrentIndex(self.burn_combo.count() - 1)
        while self.soft_copy_layout.count():
            if (child := self.soft_copy_layout.takeAt(0)).widget(): child.widget().deleteLater()
        self.soft_copy_checkboxes: list[QCheckBox] = []
        for track in self.media_file.subtitle_tracks:
            if track.codec and track.codec.lower() in ['subrip', 'srt', 'ass', 'mov_text', 'ssa']:
                cb = QCheckBox(track.get_display_name()); cb.setProperty("track", track)
                self.soft_copy_checkboxes.append(cb); self.soft_copy_layout.addWidget(cb)

    def update_media_file_from_ui(self):
        if self.stack.currentIndex() == 0:
            selected_burn_track = self.burn_combo.currentData()
            self.media_file.burned_subtitle = selected_burn_track
            for track in self.media_file.subtitle_tracks: track.action = "ignore"
            if selected_burn_track: selected_burn_track.action = "burn"
            for cb in self.soft_copy_checkboxes:
                if cb.isChecked() and (track := cb.property("track")):
                    if not (selected_burn_track and selected_burn_track.index == track.index):
                        track.action = "copy"
        elif self.stack.currentIndex() == 2:
            setattr(self.media_file, 'title', self.title_edit.text())
            setattr(self.media_file, 'media_type', self.media_type_combo.currentText())
            setattr(self.media_file, 'season', self.season_edit.value())
            setattr(self.media_file, 'episode', self.episode_edit.value())

class Dashboard(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Media Conversion Dashboard"); self.setGeometry(100, 100, 1000, 800)
        self.media_files_data: List[MediaFile] = []; self.thread = None; self.worker = None
        self.config_handler = ConfigHandler()
        self.layout = QVBoxLayout(self)

        top_controls = QHBoxLayout()
        top_controls.addWidget(QPushButton("Scan Configured", clicked=self.scan_configured_folders))
        top_controls.addWidget(QPushButton("Scan Custom...", clicked=self.scan_custom_folder))
        top_controls.addStretch()
        top_controls.addWidget(QPushButton("Settings", clicked=self.open_settings))
        self.layout.addLayout(top_controls)

        self.file_list = QListWidget(); self.file_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.layout.addWidget(self.file_list, 1)

        bottom_controls = QHBoxLayout()
        self.status_bar = QStatusBar(); self.status_bar.showMessage("Ready.")
        self.convert_button = QPushButton("Convert Selected", clicked=self.start_conversion)
        self.edit_metadata_button = QPushButton("Edit Metadata", clicked=self.toggle_metadata_edit)
        self.transfer_button = QPushButton("Transfer Converted", clicked=self.start_transfer)
        self.cancel_button = QPushButton("Cancel"); self.cancel_button.setEnabled(False) # Temporarily disabled
        bottom_controls.addWidget(self.status_bar, 1)
        bottom_controls.addWidget(self.convert_button)
        bottom_controls.addWidget(self.edit_metadata_button)
        bottom_controls.addWidget(self.transfer_button)
        bottom_controls.addWidget(self.cancel_button)
        self.layout.addLayout(bottom_controls)

    def _run_task(self, task_function: Callable, on_finish: Callable, *args, **kwargs):
        self.set_buttons_enabled(False)
        self.status_bar.showMessage(f"Running {task_function.__name__}...")
        self.thread = QThread()
        self.worker = Worker(task_function, *args, **kwargs)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(on_finish)
        self.worker.error.connect(self.on_task_error)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(lambda: self.set_buttons_enabled(True))
        self.thread.start()

    def set_buttons_enabled(self, enabled: bool):
        for btn in [self.convert_button, self.edit_metadata_button, self.transfer_button, self.findChild(QPushButton, "Scan Configured"), self.findChild(QPushButton, "Scan Custom...")]:
             if btn: btn.setEnabled(enabled)
        self.cancel_button.setEnabled(False)

    def open_settings(self):
        SettingsWindow(self.config_handler, self).exec()
    
    def _scan_multiple_dirs(self, dir_paths: List[Path]) -> List[MediaFile]:
        """Wrapper to scan multiple directories."""
        all_files = []
        for dir_path in dir_paths:
            all_files.extend(subtitlesmkv.scan_directory(dir_path))
        return all_files

    def scan_configured_folders(self):
        if not (dirs := self.config_handler.get_setting("scan_directories")):
            self.show_message("No Directories", "Add scan directories in Settings.")
            return
        dir_paths = [Path(d) for d in dirs]
        self._run_task(self._scan_multiple_dirs, self.on_scan_finished, dir_paths)

    def scan_custom_folder(self):
        if folder := QFileDialog.getExistingDirectory(self, "Select Folder"):
            dir_paths = [Path(folder)]
            self._run_task(self._scan_multiple_dirs, self.on_scan_finished, dir_paths)

    def on_scan_finished(self, result: List[MediaFile]):
        self.media_files_data = result
        self.populate_file_list()
        self.status_bar.showMessage(f"Scan complete. Found {len(result)} files.")

    def populate_file_list(self):
        self.file_list.clear()
        for media_file in self.media_files_data:
            item_widget = MediaFileItemWidget(media_file)
            list_item = QListWidgetItem(self.file_list)
            list_item.setData(Qt.ItemDataRole.UserRole, media_file)
            list_item.setSizeHint(item_widget.sizeHint())
            self.file_list.addItem(list_item)
            self.file_list.setItemWidget(list_item, item_widget)
            
    def get_selected_media_files(self) -> List[MediaFile]:
        items = self.file_list.selectedItems() or [self.file_list.item(i) for i in range(self.file_list.count())]
        return [self.file_list.itemWidget(item).media_file for item in items]

    def start_conversion(self):
        files = self.get_selected_media_files()
        if not files:
            self.show_message("No Files", "No files to convert.")
            return
        for f in files:
            self.file_list.itemWidget(self.find_list_item(f)).update_media_file_from_ui()
        
        settings = ConversionSettings(
            output_directory=Path(self.config_handler.get_setting("output_directory")),
            use_nvenc=self.config_handler.get_setting("use_nvenc"),
            crf=self.config_handler.get_setting("crf_value"),
            delete_source_on_success=self.config_handler.get_setting("delete_source_on_success")
        )
        try:
            settings.output_directory.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.show_message("Error", f"Could not create output directory.\n{e}")
            return
        self._run_task(convert.convert_batch, self.on_action_finished, files, settings)

    def toggle_metadata_edit(self):
        files_to_edit = self.get_selected_media_files()
        if not files_to_edit:
            self.show_message("No Selection", "Select files to edit metadata for.")
            return
        is_entering_edit_mode = not getattr(files_to_edit[0], 'is_editing_metadata', False)
        for f in files_to_edit:
            if not is_entering_edit_mode:
                self.file_list.itemWidget(self.find_list_item(f)).update_media_file_from_ui()
            setattr(f, 'is_editing_metadata', is_entering_edit_mode)
        self.refresh_ui()

    def start_transfer(self):
        files_to_move = [mf for mf in self.media_files_data if mf.status == "Converted"]
        if not files_to_move:
            self.show_message("No Files", "No successfully converted files to transfer.")
            return
        for f in files_to_move:
            setattr(f, 'is_editing_metadata', False)
        self.refresh_ui()
        self._run_task(robocopy.move_batch, self.on_action_finished, files_to_move)
    
    def on_action_finished(self, result: List[MediaFile]):
        self.refresh_ui()
        self.status_bar.showMessage("Task finished successfully.")

    def find_list_item(self, media_file: MediaFile) -> QListWidgetItem | None:
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == media_file:
                return item
        return None

    def refresh_ui(self):
        for i in range(self.file_list.count()):
            widget = self.file_list.itemWidget(self.file_list.item(i))
            widget.refresh_state()

    def on_task_error(self, error: Tuple):
        self.status_bar.showMessage(f"Error occurred: {error[1]}", 10000)
        advice = "\n\nAdvice: Missing output directory?" if "No such file or directory" in str(error[1]) else ""
        self.show_message("Error", f"Task failed:\n{error[1]}{advice}")
        print(error[2])

    def show_message(self, title: str, message: str):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        msg_box.exec()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    dashboard = Dashboard()
    dashboard.show()
    sys.exit(app.exec())
