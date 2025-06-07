# dashboard.py
# This is the main PyQt6 GUI for the media conversion tool.

import sys
from pathlib import Path
from typing import List, Callable, Tuple

from PyQt6.QtCore import QObject, QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QFileDialog, QFrame, QHBoxLayout, QComboBox, QCheckBox, QGroupBox,
    QProgressBar, QMessageBox
)

# --- Import all our backend modules ---
from models import MediaFile, SubtitleTrack, ConversionSettings
import subtitlesmkv
import convert
import robocopy


class Worker(QObject):
    """
    A worker thread for running background tasks without freezing the GUI.
    """
    finished = pyqtSignal(object)  # Emits the result of the task
    error = pyqtSignal(tuple)      # Emits a tuple of (exception_type, exception, traceback)
    progress = pyqtSignal(int)     # Emits progress percentage

    def __init__(self, fn: Callable, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            # Note: Progress reporting would need to be integrated into the backend functions.
            # For now, this structure is ready for it.
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

        # Top section: Filename and Status
        top_layout = QHBoxLayout()
        self.filename_label = QLabel(f"<b>{self.media_file.filename}</b>")
        self.status_label = QLabel(f"Status: {self.media_file.status}")
        top_layout.addWidget(self.filename_label)
        top_layout.addStretch()
        top_layout.addWidget(self.status_label)
        self.layout.addLayout(top_layout)

        # Bottom section: Subtitle controls
        controls_layout = QHBoxLayout()
        
        # Burn-in selection
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
        
        # Soft-copy selection
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

        self.layout = QVBoxLayout(self)

        top_controls_layout = QHBoxLayout()
        self.scan_button = QPushButton("1. Scan Media Folder")
        self.scan_button.clicked.connect(self.scan_folder)
        self.convert_button = QPushButton("2. Convert Selected Files")
        self.convert_button.clicked.connect(self.start_conversion)
        self.transfer_button = QPushButton("3. Transfer Converted Files")
        self.transfer_button.clicked.connect(self.start_transfer)
        
        top_controls_layout.addWidget(self.scan_button)
        top_controls_layout.addWidget(self.convert_button)
        top_controls_layout.addWidget(self.transfer_button)
        self.layout.addLayout(top_controls_layout)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.layout.addWidget(self.file_list)

        self.progress_bar = QProgressBar()
        self.layout.addWidget(self.progress_bar)

    def _run_task(self, task_function: Callable, on_finish: Callable, *args):
        """Helper to run a function in a background thread."""
        self.set_buttons_enabled(False)
        self.progress_bar.setValue(0)
        
        self.thread = QThread()
        self.worker = Worker(task_function, *args)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(on_finish)
        self.worker.error.connect(self.on_task_error)
        
        # Clean up thread and worker
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(lambda: self.set_buttons_enabled(True))

        self.thread.start()

    def set_buttons_enabled(self, enabled: bool):
        """Enable or disable the main action buttons."""
        self.scan_button.setEnabled(enabled)
        self.convert_button.setEnabled(enabled)
        self.transfer_button.setEnabled(enabled)

    def scan_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Media Folder")
        if folder:
            self.file_list.clear()
            self._run_task(subtitlesmkv.scan_directory, self.on_scan_finished, Path(folder))

    def on_scan_finished(self, result: List[MediaFile]):
        self.media_files_data = result
        self.populate_file_list()
        self.progress_bar.setValue(100)
        self.show_message("Scan Complete", f"Found {len(self.media_files_data)} MKV files.")

    def populate_file_list(self):
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
        settings = ConversionSettings()
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
        
        # Mockup for setting media type, a real app would have a UI for this.
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
        """Refreshes the status labels on all file widgets."""
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            widget = self.file_list.itemWidget(item)
            widget.status_label.setText(f"Status: {widget.media_file.status}")

    def on_task_error(self, error: Tuple):
        """Handles errors from the worker thread."""
        self.set_buttons_enabled(True)
        self.progress_bar.setValue(0)
        self.show_message("Error", f"An error occurred in the background task:\n{error[1]}")
        print(error[2]) # Print full traceback to console

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
