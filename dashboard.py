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
    QProgressBar, QMessageBox, QDialog, QDialogButtonBox, QLineEdit
)

# --- Import all our backend modules ---
from models import MediaFile, SubtitleTrack, ConversionSettings
import subtitlesmkv
import convert
import robocopy

# ==============================================================================
# In a real project, the following class would be in: /utils/config.py
# ==============================================================================
class ConfigHandler:
    """Handles loading and saving application settings to a JSON file."""
    def __init__(self, config_path: str = "config.json"):
        self.config_path = Path(config_path)
        self.config: Dict[str, Any] = {}
        self.default_config = {
            "scan_directories": [
                "E:/Movies",
                "E:/TV Shows"
            ],
            "output_directory": "./converted"
        }

    def load_config(self):
        """Loads configuration from the JSON file, or creates it with defaults."""
        if not self.config_path.exists():
            print("Config file not found, creating with defaults.")
            self.config = self.default_config
            self.save_config()
        else:
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    loaded_config = json.load(f)
                    # Ensure all default keys exist
                    self.config = self.default_config | loaded_config
            except (json.JSONDecodeError, IOError):
                print("Error reading config file, loading defaults.")
                self.config = self.default_config
        self.save_config() # Save to ensure new keys are written

    def save_config(self):
        """Saves the current configuration to the JSON file."""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4)
        except IOError as e:
            print(f"Error saving config file: {e}")

    def get_scan_dirs(self) -> List[str]:
        """Returns the list of scan directories."""
        return self.config.get("scan_directories", [])

    def set_scan_dirs(self, dir_list: List[str]):
        """Updates the list of scan directories."""
        self.config["scan_directories"] = dir_list

    def get_output_dir(self) -> str:
        """Returns the output directory path."""
        return self.config.get("output_directory", "./converted")

    def set_output_dir(self, dir_path: str):
        """Updates the output directory path."""
        self.config["output_directory"] = dir_path


# ==============================================================================
# In a real project, the following class would be in: settings_window.py
# ==============================================================================
class SettingsWindow(QDialog):
    """A dialog window for managing application settings."""
    def __init__(self, config_handler: ConfigHandler, parent=None):
        super().__init__(parent)
        self.config_handler = config_handler
        self.setWindowTitle("Settings")
        self.setMinimumWidth(500)

        self.layout = QVBoxLayout(self)
        
        # Output Directory Section
        self.layout.addWidget(QLabel("Default Output Directory:"))
        output_dir_layout = QHBoxLayout()
        self.output_dir_edit = QLineEdit()
        self.browse_output_btn = QPushButton("Browse...")
        output_dir_layout.addWidget(self.output_dir_edit)
        output_dir_layout.addWidget(self.browse_output_btn)
        self.layout.addLayout(output_dir_layout)

        # Scan Directory List
        self.dir_list_widget = QListWidget()
        self.layout.addWidget(QLabel("Scan Directories:"))
        self.layout.addWidget(self.dir_list_widget)
        
        # Add/Remove Buttons
        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("Add Scan Directory...")
        self.remove_btn = QPushButton("Remove Selected")
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.remove_btn)
        self.layout.addLayout(btn_layout)

        # Dialog Buttons (Save/Cancel)
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.layout.addWidget(self.button_box)
        
        # --- Connections ---
        self.browse_output_btn.clicked.connect(self.browse_output_directory)
        self.add_btn.clicked.connect(self.add_directory)
        self.remove_btn.clicked.connect(self.remove_directory)
        self.button_box.accepted.connect(self.save_and_accept)
        self.button_box.rejected.connect(self.reject)

        self.load_settings()

    def load_settings(self):
        """Populates the UI with current settings from the config handler."""
        self.output_dir_edit.setText(self.config_handler.get_output_dir())
        self.dir_list_widget.clear()
        for directory in self.config_handler.get_scan_dirs():
            self.dir_list_widget.addItem(directory)

    def browse_output_directory(self):
        """Opens a dialog to select a new output directory."""
        folder = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if folder:
            self.output_dir_edit.setText(folder)

    def add_directory(self):
        """Opens a dialog to add a new scan directory."""
        folder = QFileDialog.getExistingDirectory(self, "Select Directory to Add")
        if folder:
            self.dir_list_widget.addItem(folder)

    def remove_directory(self):
        """Removes the selected directory from the list."""
        selected_items = self.dir_list_widget.selectedItems()
        if not selected_items:
            return
        for item in selected_items:
            self.dir_list_widget.takeItem(self.dir_list_widget.row(item))

    def save_and_accept(self):
        """Saves the settings and closes the dialog."""
        new_dir_list = []
        for i in range(self.dir_list_widget.count()):
            new_dir_list.append(self.dir_list_widget.item(i).text())
        
        self.config_handler.set_scan_dirs(new_dir_list)
        self.config_handler.set_output_dir(self.output_dir_edit.text())
        self.config_handler.save_config()
        self.accept()


class Worker(QObject):
    """A worker thread for running background tasks without freezing the GUI."""
    finished = pyqtSignal(object)
    error = pyqtSignal(tuple)
    progress = pyqtSignal(int)

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
    """A custom widget to display and manage a single media file."""
    def __init__(self, media_file: MediaFile):
        super().__init__()
        self.media_file = media_file
        self.setFrameShape(QFrame.Shape.StyledPanel)

        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(10, 5, 10, 5)

        top_layout = QHBoxLayout()
        self.filename_label = QLabel(f"<b>{self.media_file.filename}</b>")
        self.status_label = QLabel(f"Status: {self.media_file.status}")
        top_layout.addWidget(self.filename_label)
        top_layout.addStretch()
        top_layout.addWidget(self.status_label)
        self.layout.addLayout(top_layout)

        controls_layout = QHBoxLayout()
        burn_group = QGroupBox("Burn-in Subtitle (Hardsub)")
        burn_layout = QVBoxLayout()
        self.burn_combo = QComboBox()
        self.burn_combo.addItem("None", None)
        for track in self.media_file.subtitle_tracks:
            self.burn_combo.addItem(track.get_display_name(), track)
            if self.media_file.burned_subtitle and self.media_file.burned_subtitle.index == track.index:
                self.burn_combo.setCurrentIndex(self.burn_combo.count() - 1)
        burn_layout.addWidget(self.burn_combo)
        burn_group.setLayout(burn_layout)
        controls_layout.addWidget(burn_group)
        
        soft_copy_group = QGroupBox("Copy Subtitles (Softsub)")
        soft_copy_layout = QVBoxLayout()
        self.soft_copy_checkboxes: list[QCheckBox] = []
        for track in self.media_file.subtitle_tracks:
            if track.codec in ['subrip', 'ass', 'mov_text', 'ssa']:
                cb = QCheckBox(track.get_display_name())
                cb.setProperty("track", track)
                self.soft_copy_checkboxes.append(cb)
                soft_copy_layout.addWidget(cb)
        soft_copy_group.setLayout(soft_copy_layout)
        controls_layout.addWidget(soft_copy_group)

        self.layout.addLayout(controls_layout)
        self.setLayout(self.layout)

    def update_media_file_from_ui(self):
        """Syncs the user's UI choices back to the MediaFile data object."""
        selected_burn_track = self.burn_combo.currentData()
        self.media_file.burned_subtitle = selected_burn_track
        
        for track in self.media_file.subtitle_tracks:
            track.action = "ignore"

        if selected_burn_track:
            selected_burn_track.action = "burn"

        for cb in self.soft_copy_checkboxes:
            if cb.isChecked():
                track = cb.property("track")
                if not (selected_burn_track and selected_burn_track.index == track.index):
                    track.action = "copy"


class Dashboard(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Media Conversion Dashboard")
        self.setGeometry(100, 100, 900, 700)
        self.media_files_data: List[MediaFile] = []
        self.thread = None
        self.worker = None

        self.config_handler = ConfigHandler()
        self.config_handler.load_config()

        self.layout = QVBoxLayout(self)

        top_controls_layout = QHBoxLayout()
        self.scan_config_button = QPushButton("1a. Scan Configured Folders")
        self.scan_custom_button = QPushButton("1b. Scan Custom Folder...")
        self.convert_button = QPushButton("2. Convert Selected")
        self.transfer_button = QPushButton("3. Transfer Converted")
        self.settings_button = QPushButton("Settings")
        
        top_controls_layout.addWidget(self.scan_config_button)
        top_controls_layout.addWidget(self.scan_custom_button)
        top_controls_layout.addWidget(self.convert_button)
        top_controls_layout.addWidget(self.transfer_button)
        top_controls_layout.addStretch()
        top_controls_layout.addWidget(self.settings_button)
        self.layout.addLayout(top_controls_layout)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.layout.addWidget(self.file_list)

        self.progress_bar = QProgressBar()
        self.layout.addWidget(self.progress_bar)
        
        self.scan_config_button.clicked.connect(self.scan_configured_folders)
        self.scan_custom_button.clicked.connect(self.scan_custom_folder)
        self.convert_button.clicked.connect(self.start_conversion)
        self.transfer_button.clicked.connect(self.start_transfer)
        self.settings_button.clicked.connect(self.open_settings)

    def _run_task(self, task_function: Callable, on_finish: Callable, *args):
        self.set_buttons_enabled(False)
        self.progress_bar.setValue(0)
        
        self.thread = QThread()
        self.worker = Worker(task_function, *args)
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
        self.scan_config_button.setEnabled(enabled)
        self.scan_custom_button.setEnabled(enabled)
        self.convert_button.setEnabled(enabled)
        self.transfer_button.setEnabled(enabled)
        self.settings_button.setEnabled(enabled)

    def open_settings(self):
        dialog = SettingsWindow(self.config_handler, self)
        dialog.exec()

    def _scan_multiple_dirs(self, dir_paths: List[str]) -> List[MediaFile]:
        all_media_files = []
        for dir_path in dir_paths:
            all_media_files.extend(subtitlesmkv.scan_directory(Path(dir_path)))
        return all_media_files

    def scan_configured_folders(self):
        configured_dirs = self.config_handler.get_scan_dirs()
        if not configured_dirs:
            self.show_message("No Directories Configured", "Please add scan directories in Settings.")
            return
        self.file_list.clear()
        self._run_task(self._scan_multiple_dirs, self.on_scan_finished, configured_dirs)

    def scan_custom_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Custom Media Folder")
        if folder:
            self.file_list.clear()
            self._run_task(self._scan_multiple_dirs, self.on_scan_finished, [folder])

    def on_scan_finished(self, result: List[MediaFile]):
        self.media_files_data = result
        self.populate_file_list()
        self.progress_bar.setValue(100)
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
        self.update_statuses()

    def _get_selected_media_files(self) -> List[MediaFile]:
        selected_files = []
        selected_items = self.file_list.selectedItems()
        if not selected_items and self.file_list.count() > 0:
            items_to_process = [self.file_list.item(i) for i in range(self.file_list.count())]
        else:
            items_to_process = selected_items

        for item in items_to_process:
            widget = self.file_list.itemWidget(item)
            widget.update_media_file_from_ui()
            selected_files.append(item.data(Qt.ItemDataRole.UserRole))
        return selected_files

    def start_conversion(self):
        files_to_convert = self._get_selected_media_files()
        if not files_to_convert:
            self.show_message("No Files Selected", "Please select files to convert, or scan a folder first.")
            return
            
        # Initialize settings from our config handler
        output_dir = Path(self.config_handler.get_output_dir())
        settings = ConversionSettings(output_directory=output_dir)

        # *** FIX: Ensure output directory exists before starting conversion ***
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            print(f"Ensured output directory exists: {output_dir}")
        except Exception as e:
            self.show_message("Directory Error", f"Could not create output directory '{output_dir}'.\nPlease check permissions.\n\nError: {e}")
            return

        self._run_task(convert.convert_batch, self.on_conversion_finished, files_to_convert, settings)

    def on_conversion_finished(self, result: List[MediaFile]):
        self.progress_bar.setValue(100)
        self.update_statuses()
        self.show_message("Conversion Finished", "Batch conversion process has completed.")

    def start_transfer(self):
        files_to_move = [mf for mf in self.media_files_data if mf.status == "Converted"]
        if not files_to_move:
             self.show_message("No Files to Transfer", "No files have been successfully converted yet.")
             return
        
        for mf in files_to_move:
            if "S0" in mf.filename and "E0" in mf.filename:
                setattr(mf, "media_type", "tv")
                setattr(mf, "title", "Example Show")
                setattr(mf, "season", 1)
                setattr(mf, "episode", 1)
            else:
                setattr(mf, "media_type", "movie")
                setattr(mf, "title", mf.filename.rsplit('.', 1)[0])

        self._run_task(robocopy.move_batch, self.on_transfer_finished, files_to_move)
    
    def on_transfer_finished(self, result):
        self.progress_bar.setValue(100)
        self.update_statuses()
        self.show_message("Transfer Finished", "File transfer process has completed.")

    def update_statuses(self):
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            widget = self.file_list.itemWidget(item)
            widget.status_label.setText(f"Status: {widget.media_file.status}")

    def on_task_error(self, error: Tuple):
        self.set_buttons_enabled(True)
        self.progress_bar.setValue(0)
        # Add more specific error advice
        error_message = str(error[1])
        advice = ""
        if "No such file or directory" in error_message:
            advice = "\n\nAdvice: This might be caused by a missing output directory. Please check the path in Settings."
        
        self.show_message("Error", f"An error occurred in the background task:\n{error_message}{advice}")
        print(error[2])

    def show_message(self, title: str, message: str):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        msg_box.exec()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    dashboard = Dashboard()
    dashboard.show()
    sys.exit(app.exec())
