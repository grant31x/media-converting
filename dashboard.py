# dashboard.py
# This is the main PyQt6 GUI for the media conversion tool.

import sys
import json
from pathlib import Path
from typing import List, Callable, Tuple, Dict, Any

from PyQt6.QtCore import QObject, QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QFileDialog, QFrame, QHBoxLayout, QComboBox, QCheckBox, QGroupBox,
    QProgressBar, QMessageBox, QDialog, QDialogButtonBox, QLineEdit, QStackedWidget
)

# Assumed to be in other files, included here for self-containment
from models import MediaFile, SubtitleTrack, ConversionSettings
import subtitlesmkv
import convert
import robocopy

class ConfigHandler:
    def __init__(self, config_path: str = "config.json"):
        self.config_path = Path(config_path)
        self.config: Dict[str, Any] = {}
        self.default_config = {
            "scan_directories": ["E:/Movies", "E:/TV Shows"],
            "output_directory": "./converted"
        }
        self.load_config()
    def load_config(self):
        if not self.config_path.exists(): self.config = self.default_config; self.save_config()
        else:
            try:
                with open(self.config_path, "r", encoding="utf-8") as f: self.config = self.default_config | json.load(f)
            except (json.JSONDecodeError, IOError): self.config = self.default_config
        self.save_config()
    def save_config(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f: json.dump(self.config, f, indent=4)
        except IOError as e: print(f"Error saving config file: {e}")
    def get_scan_dirs(self) -> List[str]: return self.config.get("scan_directories", [])
    def set_scan_dirs(self, dir_list: List[str]): self.config["scan_directories"] = dir_list
    def get_output_dir(self) -> str: return self.config.get("output_directory", "./converted")
    def set_output_dir(self, dir_path: str): self.config["output_directory"] = dir_path

class SettingsWindow(QDialog):
    def __init__(self, config_handler: ConfigHandler, parent=None):
        super().__init__(parent)
        self.config_handler = config_handler
        self.setWindowTitle("Settings")
        self.setMinimumWidth(500)
        self.layout = QVBoxLayout(self)
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
        self.browse_output_btn.clicked.connect(self.browse_output_directory)
        self.add_btn.clicked.connect(self.add_directory)
        self.remove_btn.clicked.connect(self.remove_directory)
        self.button_box.accepted.connect(self.save_and_accept)
        self.button_box.rejected.connect(self.reject)
        self.load_settings()
    def load_settings(self):
        self.output_dir_edit.setText(self.config_handler.get_output_dir())
        self.dir_list_widget.clear()
        for directory in self.config_handler.get_scan_dirs(): self.dir_list_widget.addItem(directory)
    def browse_output_directory(self):
        if folder := QFileDialog.getExistingDirectory(self, "Select Output Directory"): self.output_dir_edit.setText(folder)
    def add_directory(self):
        if folder := QFileDialog.getExistingDirectory(self, "Select Directory to Add"): self.dir_list_widget.addItem(folder)
    def remove_directory(self):
        for item in self.dir_list_widget.selectedItems(): self.dir_list_widget.takeItem(self.dir_list_widget.row(item))
    def save_and_accept(self):
        self.config_handler.set_scan_dirs([self.dir_list_widget.item(i).text() for i in range(self.dir_list_widget.count())])
        self.config_handler.set_output_dir(self.output_dir_edit.text())
        self.config_handler.save_config(); self.accept()

class Worker(QObject):
    finished = pyqtSignal(object); error = pyqtSignal(tuple); progress = pyqtSignal(int)
    def __init__(self, fn: Callable, *args, **kwargs): super().__init__(); self.fn, self.args, self.kwargs = fn, args, kwargs
    def run(self):
        try: self.finished.emit(self.fn(*self.args, **self.kwargs))
        except Exception as e: import traceback; self.error.emit((type(e), e, traceback.format_exc()))

class MediaFileItemWidget(QFrame):
    """A custom widget to display and manage a single media file, with multiple views."""
    def __init__(self, media_file: MediaFile):
        super().__init__()
        self.media_file = media_file
        self.setFrameShape(QFrame.Shape.StyledPanel)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)

        header_layout = QHBoxLayout()
        self.filename_label = QLabel(f"<b>{self.media_file.filename}</b>")
        self.status_label = QLabel()
        header_layout.addWidget(self.filename_label)
        header_layout.addStretch()
        header_layout.addWidget(self.status_label)
        main_layout.addLayout(header_layout)

        self.stack = QStackedWidget()
        main_layout.addWidget(self.stack)

        self._create_selection_view()
        self._create_summary_view()
        self.refresh_state()

    def _create_selection_view(self):
        selection_widget = QWidget()
        controls_layout = QHBoxLayout(selection_widget)
        controls_layout.setContentsMargins(10, 5, 10, 5)

        burn_group = QGroupBox("Burn-in Subtitle (Hardsub)")
        burn_layout = QVBoxLayout()
        self.burn_combo = QComboBox()
        burn_layout.addWidget(self.burn_combo)
        burn_group.setLayout(burn_layout)
        
        soft_copy_group = QGroupBox("Copy Subtitles (Softsub)")
        self.soft_copy_layout = QVBoxLayout()
        soft_copy_group.setLayout(self.soft_copy_layout)

        controls_layout.addWidget(burn_group)
        controls_layout.addWidget(soft_copy_group)
        self.stack.addWidget(selection_widget)

    def _create_summary_view(self):
        summary_widget = QWidget()
        summary_layout = QHBoxLayout(summary_widget)
        summary_layout.setContentsMargins(10, 5, 10, 5)

        self.orig_size_label = QLabel()
        self.new_size_label = QLabel()
        self.size_change_label = QLabel()
        self.audio_details_label = QLabel()

        for label in [self.orig_size_label, self.new_size_label, self.size_change_label, self.audio_details_label]:
            summary_layout.addWidget(label)
            summary_layout.addStretch()

        self.stack.addWidget(summary_widget)
        
    def populate_selection_controls(self):
        self.burn_combo.clear()
        self.burn_combo.addItem("None", None)
        for track in self.media_file.subtitle_tracks:
            self.burn_combo.addItem(track.get_display_name(), track)
            if self.media_file.burned_subtitle and self.media_file.burned_subtitle.index == track.index:
                self.burn_combo.setCurrentIndex(self.burn_combo.count() - 1)
        
        while self.soft_copy_layout.count():
            child = self.soft_copy_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        self.soft_copy_checkboxes: list[QCheckBox] = []
        # --- NEW: More robust list of text-based codecs ---
        TEXT_SUB_CODECS = ['subrip', 'srt', 'ass', 'mov_text', 'ssa']
        for track in self.media_file.subtitle_tracks:
            # Check if track.codec is not None before checking its value
            if track.codec and track.codec.lower() in TEXT_SUB_CODECS:
                cb = QCheckBox(track.get_display_name())
                cb.setProperty("track", track)
                self.soft_copy_checkboxes.append(cb)
                self.soft_copy_layout.addWidget(cb)
    
    def refresh_state(self):
        self.status_label.setText(f"Status: {self.media_file.status}")
        
        if self.media_file.status in ["Converted", "Transferred", "Skipped (Exists)"]:
            self.orig_size_label.setText(f"Original Size: {self.media_file.original_size_mb:.2f} MB")
            self.new_size_label.setText(f"Converted Size: {self.media_file.converted_size_mb:.2f} MB")
            size_change = self.media_file.size_change_percent
            self.size_change_label.setText(f"Change: {size_change:+.2f}%")
            self.audio_details_label.setText(f"Audio: {getattr(self.media_file, 'audio_conversion_details', 'N/A')}")
            self.stack.setCurrentIndex(1)
        else:
            self.populate_selection_controls()
            self.stack.setCurrentIndex(0)

    def update_media_file_from_ui(self):
        selected_burn_track = self.burn_combo.currentData()
        self.media_file.burned_subtitle = selected_burn_track
        
        for track in self.media_file.subtitle_tracks: track.action = "ignore"
        if selected_burn_track: selected_burn_track.action = "burn"

        for cb in self.soft_copy_checkboxes:
            if cb.isChecked():
                track = cb.property("track")
                if not (selected_burn_track and selected_burn_track.index == track.index):
                    track.action = "copy"

class Dashboard(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Media Conversion Dashboard")
        self.setGeometry(100, 100, 950, 700)
        self.media_files_data: List[MediaFile] = []
        self.thread = None; self.worker = None

        self.config_handler = ConfigHandler()
        self.layout = QVBoxLayout(self)

        top_controls_layout = QHBoxLayout()
        self.scan_config_button = QPushButton("Scan Configured Folders")
        self.scan_custom_button = QPushButton("Scan Custom Folder...")
        self.settings_button = QPushButton("Settings")
        top_controls_layout.addWidget(self.scan_config_button)
        top_controls_layout.addWidget(self.scan_custom_button)
        top_controls_layout.addStretch()
        top_controls_layout.addWidget(self.settings_button)
        self.layout.addLayout(top_controls_layout)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.layout.addWidget(self.file_list, 1)

        bottom_controls_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.convert_button = QPushButton("Convert Selected")
        self.transfer_button = QPushButton("Transfer Converted")
        bottom_controls_layout.addWidget(self.progress_bar)
        bottom_controls_layout.addWidget(self.convert_button)
        bottom_controls_layout.addWidget(self.transfer_button)
        self.layout.addLayout(bottom_controls_layout)
        
        self.scan_config_button.clicked.connect(self.scan_configured_folders)
        self.scan_custom_button.clicked.connect(self.scan_custom_folder)
        self.settings_button.clicked.connect(self.open_settings)
        self.convert_button.clicked.connect(self.start_conversion)
        self.transfer_button.clicked.connect(self.start_transfer)

    def _run_task(self, task_function: Callable, on_finish: Callable, *args):
        self.set_buttons_enabled(False)
        self.progress_bar.setRange(0,0)
        self.thread = QThread(); self.worker = Worker(task_function, *args); self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(on_finish)
        self.worker.error.connect(self.on_task_error)
        self.worker.finished.connect(self.thread.quit); self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater); self.thread.finished.connect(lambda: self.set_buttons_enabled(True))
        self.thread.start()

    def set_buttons_enabled(self, enabled: bool):
        for btn in [self.scan_config_button, self.scan_custom_button, self.settings_button, self.convert_button, self.transfer_button]:
            btn.setEnabled(enabled)
        self.progress_bar.setRange(0,100); self.progress_bar.setValue(0 if enabled else 100)

    def open_settings(self):
        SettingsWindow(self.config_handler, self).exec()

    def _scan_multiple_dirs(self, dir_paths: List[str]) -> List[MediaFile]:
        return [mf for dir_path in dir_paths for mf in subtitlesmkv.scan_directory(Path(dir_path))]

    def scan_configured_folders(self):
        if not (configured_dirs := self.config_handler.get_scan_dirs()):
            self.show_message("No Directories Configured", "Please add scan directories in Settings.")
            return
        self._run_task(self._scan_multiple_dirs, self.on_scan_finished, configured_dirs)

    def scan_custom_folder(self):
        if folder := QFileDialog.getExistingDirectory(self, "Select Custom Media Folder"):
            self._run_task(self._scan_multiple_dirs, self.on_scan_finished, [folder])

    def on_scan_finished(self, result: List[MediaFile]):
        self.media_files_data = result
        self.populate_file_list()
        self.show_message("Scan Complete", f"Found {len(self.media_files_data)} MKV files.")

    def populate_file_list(self):
        self.file_list.clear()
        for media_file in self.media_files_data:
            item_widget = MediaFileItemWidget(media_file)
            list_item = QListWidgetItem(self.file_list)
            list_item.setData(Qt.ItemDataRole.UserRole, media_file)
            list_item.setSizeHint(item_widget.sizeHint())
            self.file_list.addItem(list_item)
            self.file_list.setItemWidget(list_item, item_widget)

    def _get_selected_media_files(self) -> List[MediaFile]:
        items_to_process = self.file_list.selectedItems() or [self.file_list.item(i) for i in range(self.file_list.count())]
        selected_files = []
        for item in items_to_process:
            widget = self.file_list.itemWidget(item)
            widget.update_media_file_from_ui()
            selected_files.append(item.data(Qt.ItemDataRole.UserRole))
        return selected_files

    def start_conversion(self):
        if not (files_to_convert := self._get_selected_media_files()):
            self.show_message("No Files Selected", "Please select files to convert, or scan a folder first."); return
            
        output_dir = Path(self.config_handler.get_output_dir())
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.show_message("Directory Error", f"Could not create output directory '{output_dir}'.\nError: {e}"); return

        settings = ConversionSettings(output_directory=output_dir)
        self._run_task(convert.convert_batch, self.on_action_finished, files_to_convert, settings)

    def start_transfer(self):
        files_to_move = [mf for mf in self.media_files_data if mf.status == "Converted"]
        if not files_to_move: self.show_message("No Files to Transfer", "No successfully converted files found."); return
        for mf in files_to_move:
            setattr(mf, "media_type", "tv" if "S0" in mf.filename and "E0" in mf.filename else "movie")
            setattr(mf, "title", mf.filename.rsplit('.', 1)[0])
            if mf.media_type == "tv": setattr(mf, "season", 1); setattr(mf, "episode", 1)
        self._run_task(robocopy.move_batch, self.on_action_finished, files_to_move)
    
    def on_action_finished(self, result: List[MediaFile]):
        self.refresh_ui()
        self.show_message("Task Finished", "The requested batch process has completed.")

    def refresh_ui(self):
        """Refreshes all widgets in the list to reflect the latest media file state."""
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            widget = self.file_list.itemWidget(item)
            widget.refresh_state()

    def on_task_error(self, error: Tuple):
        self.set_buttons_enabled(True)
        advice = "\n\nAdvice: This might be caused by a missing output directory. Check Settings." if "No such file or directory" in str(error[1]) else ""
        self.show_message("Error", f"An error occurred in the background task:\n{error[1]}{advice}")
        print(error[2])

    def show_message(self, title: str, message: str):
        msg_box = QMessageBox(self); msg_box.setWindowTitle(title); msg_box.setText(message); msg_box.exec()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    # Apply a style for a more modern look
    app.setStyle("Fusion")
    dashboard = Dashboard()
    dashboard.show()
    sys.exit(app.exec())
