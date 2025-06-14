# dashboard.py
# Version: 4.4.9
# Implements a more intelligent search query cleaning function.

import sys
import os
import json
import re
import inspect
from pathlib import Path
from typing import List, Callable, Tuple, Dict, Any, Union, Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal, Qt, QPoint
from PyQt6.QtGui import QIcon, QIntValidator
from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QFileDialog, QFrame, QHBoxLayout, QComboBox, QCheckBox, QGroupBox,
    QMessageBox, QDialog, QDialogButtonBox, QLineEdit, QStackedWidget,
    QStatusBar, QSpinBox, QTextEdit, QMenu, QProgressBar, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QHeaderView
)

# --- Project Modules ---
from models import MediaFile, SubtitleTrack, ConversionSettings
import subtitlesmkv
import convert
import file_handler
import basic_convert
import mkv_modifier
try:
    import tmdb_client
    TMDB_ENABLED = True
except ImportError:
    TMDB_ENABLED = False

# --- Helper functions ---
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def get_writable_config_path():
    base = Path(os.getenv("APPDATA", Path.home()))
    return base / "MediaConverter" / "config.json"

def ensure_writable_config():
    config_path = get_writable_config_path()
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(resource_path("config.json"), "r", encoding="utf-8") as default_f:
                default_data = json.load(default_f)
            with open(config_path, "w", encoding="utf-8") as writable_f:
                json.dump(default_data, writable_f, indent=4)
        except Exception:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({}, f)
    return config_path

# --- NEW: Greatly improved search query cleaning function ---
def _clean_search_query(filename: str) -> str:
    """
    Cleans a filename to extract the most likely movie title for an API search.
    This version focuses on splitting the title at the first sign of metadata.
    """
    clean_title = Path(filename).stem
    
    # Delimiters that often mark the end of a title and the start of metadata.
    # The order is important: check for years first.
    delimiters = [
        r'(19|20)\d{2}',  # Year (e.g., 2024)
        '4k', '2160p', '1080p', '720p', '480p',
        'bluray', 'web-dl', 'webdl', 'webrip', 'hdrip', 'dvdrip', 'brrip', 'hdtv',
        'extended', 'uncut', 'remastered', 'theatrical',
    ]
    
    # Create a regex pattern to split the string at the first occurrence of any delimiter
    # We use word boundaries (\b) to avoid splitting in the middle of a word.
    split_pattern = r'\b(' + '|'.join(delimiters) + r')\b'
    
    # Split the string at the first delimiter, keeping only the part before it
    clean_title = re.split(split_pattern, clean_title, maxsplit=1, flags=re.IGNORECASE)[0]
    
    # Replace common separators with spaces
    clean_title = re.sub(r'[\._-]', ' ', clean_title)
    
    # Remove any remaining junk and consolidate whitespace
    clean_title = ' '.join(clean_title.split()).strip()
    
    return clean_title

# --- All Helper and Custom Widget Classes Defined First ---

class CustomTitleBar(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.setObjectName("CustomTitleBar")
        self.setFixedHeight(32)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 0, 0, 0)
        
        icon_label = QLabel()
        icon_path = resource_path("icon.ico")
        if os.path.exists(icon_path):
            icon_label.setPixmap(QIcon(icon_path).pixmap(16, 16))
        
        title_label = QLabel("G's Movie Converter")
        title_label.setObjectName("TitleLabel")
        
        layout.addWidget(icon_label)
        layout.addWidget(title_label)
        layout.addStretch()

        self.minimize_button = QPushButton("—")
        self.maximize_button = QPushButton("🗖")
        self.close_button = QPushButton("✕")
        
        self.minimize_button.setObjectName("MinimizeButton")
        self.maximize_button.setObjectName("MaximizeButton")
        self.close_button.setObjectName("CloseButton")
        
        self.minimize_button.clicked.connect(self.parent.showMinimized)
        self.maximize_button.clicked.connect(self.toggle_maximize)
        self.close_button.clicked.connect(self.parent.close)

        layout.addWidget(self.minimize_button)
        layout.addWidget(self.maximize_button)
        layout.addWidget(self.close_button)

        self.start_pos = None

    def toggle_maximize(self):
        if self.parent.isMaximized():
            self.parent.showNormal()
        else:
            self.parent.showMaximized()
            
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self.start_pos:
            delta = event.globalPosition().toPoint() - self.start_pos
            self.parent.move(self.parent.pos() + delta)
            self.start_pos = event.globalPosition().toPoint()

class MetadataSearchDialog(QDialog):
    def __init__(self, query: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Metadata Search Results")
        self.setMinimumSize(600, 400)
        self.layout = QVBoxLayout(self)
        
        self.search_label = QLabel(f"Searching for: <b>{query}</b>")
        self.layout.addWidget(self.search_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        self.layout.addWidget(self.progress_bar)
        
        self.results_list = QListWidget()
        self.results_list.itemDoubleClicked.connect(self.accept)
        self.layout.addWidget(self.results_list)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.layout.addWidget(self.button_box)
        
        self.thread = QThread()
        self.worker = None
        
        self.search(query)

    def search(self, query):
        self.progress_bar.setVisible(True)
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.button_box.button(QDialogButtonBox.StandardButton.Cancel).setEnabled(False)

        year_match = re.search(r'\b(19|20)\d{2}\b', query)
        year = year_match.group(0) if year_match else None
        
        clean_query = _clean_search_query(query)
        
        print(f"[DEBUG] Original Filename: '{query}'")
        print(f"[DEBUG] Cleaned Query: '{clean_query}', Year: {year}")
        
        self.search_label.setText(f"Searching for: <b>{clean_query}</b> (Year: {year or 'Any'})")

        self.worker = Worker(tmdb_client.search_movie, clean_query, year)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_search_finished)
        self.thread.start()

    def on_search_finished(self, results: List[Dict]):
        self.progress_bar.setVisible(False)
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
        self.button_box.button(QDialogButtonBox.StandardButton.Cancel).setEnabled(True)

        self.results_list.clear()
        if not results:
            self.results_list.addItem("No results found.")
            return
            
        for movie in results:
            title = movie.get('title', 'N/A')
            release_date = movie.get('release_date', 'N/A')
            year = release_date.split('-')[0] if release_date and '-' in release_date else "N/A"
            display_text = f"{title} ({year})"
            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, movie)
            self.results_list.addItem(item)
        
        self.stop_thread()

    def get_selected_movie(self) -> Optional[Dict]:
        if self.result() == QDialog.DialogCode.Accepted:
            selected_item = self.results_list.currentItem()
            if selected_item and selected_item.data(Qt.ItemDataRole.UserRole):
                return selected_item.data(Qt.ItemDataRole.UserRole)
        return None

    def accept(self):
        self.stop_thread()
        super().accept()

    def reject(self):
        self.stop_thread()
        super().reject()

    def closeEvent(self, event):
        self.stop_thread()
        event.accept()

    def stop_thread(self):
        if self.thread and self.thread.isRunning():
            try:
                self.worker.finished.disconnect()
            except TypeError:
                pass
            self.thread.quit()
            self.thread.wait()

class RenameDialog(QDialog):
    def __init__(self, media_file: MediaFile, filename_template: str, parent=None):
        super().__init__(parent)
        self.media_file = media_file
        self.filename_template = filename_template
        self.setWindowTitle("Edit Metadata and Filename")
        self.layout = QVBoxLayout(self)

        self.layout.addWidget(QLabel("Metadata Title:"))
        self.title_edit = QLineEdit(self.media_file.title)
        self.layout.addWidget(self.title_edit)
        
        h_layout = QHBoxLayout()
        year_layout = QVBoxLayout()
        year_layout.addWidget(QLabel("Year:"))
        self.year_edit = QLineEdit(str(self.media_file.year or ""))
        self.year_edit.setValidator(QIntValidator(1800, 2200))
        year_layout.addWidget(self.year_edit)
        h_layout.addLayout(year_layout)

        comment_layout = QVBoxLayout()
        comment_layout.addWidget(QLabel("Comment:"))
        self.comment_edit = QLineEdit(self.media_file.comment or "")
        comment_layout.addWidget(self.comment_edit)
        h_layout.addLayout(comment_layout)
        self.layout.addLayout(h_layout)
        
        self.layout.addSpacing(10)
        
        self.layout.addWidget(QLabel("Output Filename:"))
        self.filename_edit = QLineEdit(self.media_file.output_filename)
        self.layout.addWidget(self.filename_edit)
        
        self.sync_checkbox = QCheckBox("Automatically update filename using template")
        self.sync_checkbox.setChecked(True)
        self.layout.addWidget(self.sync_checkbox)
        
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.layout.addWidget(self.button_box)
        
        self.title_edit.textChanged.connect(self.on_metadata_changed)
        self.year_edit.textChanged.connect(self.on_metadata_changed)
        self.sync_checkbox.stateChanged.connect(self.on_metadata_changed)
        
        self.on_metadata_changed()

    def on_metadata_changed(self):
        if self.sync_checkbox.isChecked():
            temp_mf = MediaFile(source_path=self.media_file.source_path)
            temp_mf.title = self.title_edit.text()
            try:
                temp_mf.year = int(self.year_edit.text()) if self.year_edit.text() else None
            except ValueError:
                temp_mf.year = None
            temp_mf.video_width = self.media_file.video_width
            temp_mf.video_fps = self.media_file.video_fps
            
            output_filename = temp_mf.generate_filename_from_template(self.filename_template)
            self.filename_edit.setText(output_filename)
    
    def set_fetched_metadata(self, movie_data: Dict):
        self.title_edit.setText(movie_data.get("title", ""))
        release_date = movie_data.get("release_date", "")
        if release_date and "-" in release_date:
            self.year_edit.setText(release_date.split("-")[0])
        self.comment_edit.setText(movie_data.get("overview", ""))
        self.on_metadata_changed()

    def get_results(self) -> Optional[Tuple[str, str, int, str]]:
        if self.exec() == QDialog.DialogCode.Accepted:
            title = self.title_edit.text()
            filename = self.filename_edit.text()
            try:
                year = int(self.year_edit.text()) if self.year_edit.text() else None
            except ValueError:
                year = None
            comment = self.comment_edit.text()
            return filename, title, year, comment
        return None

class PathMappingDialog(QDialog):
    def __init__(self, parent=None, source="", destination=""):
        super().__init__(parent)
        self.setWindowTitle("Edit Path Mapping")
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("Scan Location (Source):"))
        source_layout = QHBoxLayout()
        self.source_edit = QLineEdit(source)
        self.browse_source_btn = QPushButton("Browse...")
        source_layout.addWidget(self.source_edit)
        source_layout.addWidget(self.browse_source_btn)
        layout.addLayout(source_layout)
        
        layout.addWidget(QLabel("Transfer Destination:"))
        dest_layout = QHBoxLayout()
        self.dest_edit = QLineEdit(destination)
        self.browse_dest_btn = QPushButton("Browse...")
        dest_layout.addWidget(self.dest_edit)
        dest_layout.addWidget(self.browse_dest_btn)
        layout.addLayout(dest_layout)
        
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.browse_source_btn.clicked.connect(lambda: self.browse_for_folder(self.source_edit))
        self.browse_dest_btn.clicked.connect(lambda: self.browse_for_folder(self.dest_edit))

    def browse_for_folder(self, line_edit_widget):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            line_edit_widget.setText(folder.replace("\\", "/"))

    def get_paths(self):
        if self.exec() == QDialog.DialogCode.Accepted:
            return self.source_edit.text(), self.dest_edit.text()
        return None, None
        
class ConfigHandler:
    def __init__(self):
        self.config_path = ensure_writable_config()
        self.config: Dict[str, Any] = {}
        self.load_config()

    def load_config(self):
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.config = json.load(f)
        except (json.JSONDecodeError, IOError, FileNotFoundError):
            try:
                with open(resource_path("config.json"), "r", encoding="utf-8") as f:
                    self.config = json.load(f)
            except Exception:
                self.config = {}

    def save_config(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4)
        except IOError as e:
            print(f"Error saving config file to {self.config_path}: {e}")
            
    def save_api_key(self, api_key: str):
        try:
            api_config_path = Path(resource_path(".")).parent / "api_config.json"
            if not TMDB_ENABLED:
                api_config_path = Path(resource_path(".")) / "api_config.json"
            with open(api_config_path, "w", encoding="utf-8") as f:
                json.dump({"tmdb_api_key": api_key}, f, indent=4)
        except Exception as e:
            print(f"Error saving API key file to {api_config_path}: {e}")

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def set_setting(self, key: str, value: Any):
        self.config[key] = value

class SettingsWindow(QDialog):
    def __init__(self, config_handler: ConfigHandler, parent=None):
        super().__init__(parent)
        self.config_handler = config_handler
        self.setWindowTitle("Settings")
        self.setMinimumWidth(700)
        self.resize(800, 600)
        self.layout = QVBoxLayout(self)
        
        main_group = QGroupBox("General Settings")
        main_layout = QVBoxLayout()
        
        template_layout = QHBoxLayout()
        template_layout.addWidget(QLabel("Filename Template:"))
        self.template_edit = QLineEdit()
        self.template_edit.setToolTip("Placeholders: {title}, {year}, {width}, {fps}")
        template_layout.addWidget(self.template_edit)
        main_layout.addLayout(template_layout)
        
        scan_types_layout = QHBoxLayout()
        scan_types_layout.addWidget(QLabel("Scannable File Types:"))
        self.scan_types_edit = QLineEdit()
        self.scan_types_edit.setToolTip("Comma-separated list of extensions, e.g., .mkv, .mp4, .avi")
        scan_types_layout.addWidget(self.scan_types_edit)
        main_layout.addLayout(scan_types_layout)
        
        api_key_layout = QHBoxLayout()
        api_key_layout.addWidget(QLabel("TMDb API Key:"))
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        api_key_layout.addWidget(self.api_key_edit)
        main_layout.addLayout(api_key_layout)
        
        main_group.setLayout(main_layout)
        self.layout.addWidget(main_group)
        
        conv_group = QGroupBox("Conversion Settings")
        conv_layout = QVBoxLayout()
        self.nvenc_checkbox = QCheckBox("Enable GPU Encoding (NVIDIA NVENC)")
        conv_layout.addWidget(self.nvenc_checkbox)
        self.two_pass_checkbox = QCheckBox("Enable 2-Pass Mode (slower, better file size)")
        conv_layout.addWidget(self.two_pass_checkbox)
        self.delete_source_checkbox = QCheckBox("Delete Original File After Conversion")
        conv_layout.addWidget(self.delete_source_checkbox)
        quality_layout = QHBoxLayout()
        quality_label = QLabel("Target Quality Level (lower = better quality):")
        quality_layout.addWidget(quality_label)
        self.quality_spinbox = QSpinBox()
        self.quality_spinbox.setRange(0, 51)
        quality_layout.addWidget(self.quality_spinbox)
        conv_layout.addLayout(quality_layout)
        conv_group.setLayout(conv_layout)
        self.layout.addWidget(conv_group)

        path_group = QGroupBox("Path Mappings (Scan From -> Transfer To)")
        path_layout = QVBoxLayout()
        self.path_table = QTableWidget()
        self.path_table.setColumnCount(2)
        self.path_table.setHorizontalHeaderLabels(["Scan Location (Source)", "Transfer Destination"])
        self.path_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.path_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.path_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.path_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        path_layout.addWidget(self.path_table)
        path_btn_layout = QHBoxLayout()
        self.add_map_btn = QPushButton("Add...")
        self.edit_map_btn = QPushButton("Edit...")
        self.remove_map_btn = QPushButton("Remove")
        path_btn_layout.addStretch()
        path_btn_layout.addWidget(self.add_map_btn)
        path_btn_layout.addWidget(self.edit_map_btn)
        path_btn_layout.addWidget(self.remove_map_btn)
        path_layout.addLayout(path_btn_layout)
        path_group.setLayout(path_layout)
        self.layout.addWidget(path_group)
        
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.layout.addWidget(self.button_box)
        
        self.add_map_btn.clicked.connect(self.add_mapping)
        self.edit_map_btn.clicked.connect(self.edit_mapping)
        self.remove_map_btn.clicked.connect(self.remove_mapping)
        self.path_table.doubleClicked.connect(self.edit_mapping)
        self.button_box.accepted.connect(self.save_and_accept)
        self.button_box.rejected.connect(self.reject)
        
        self.load_settings()

    def load_settings(self):
        self.nvenc_checkbox.setChecked(self.config_handler.get_setting("use_nvenc", True))
        self.two_pass_checkbox.setChecked(self.config_handler.get_setting("use_two_pass", True))
        self.delete_source_checkbox.setChecked(self.config_handler.get_setting("delete_source_on_success", False))
        self.quality_spinbox.setValue(self.config_handler.get_setting("crf_value", 23))
        
        self.template_edit.setText(self.config_handler.get_setting("filename_template", "{title} ({year}) - {width}p"))
        scan_types = self.config_handler.get_setting("scannable_file_types", [".mkv", ".mp4"])
        self.scan_types_edit.setText(", ".join(scan_types))
        if TMDB_ENABLED:
            self.api_key_edit.setText(tmdb_client.get_api_key() or "")

        self.path_table.setRowCount(0)
        mappings = self.config_handler.get_setting("path_mappings", [])
        if mappings:
            for mapping in mappings:
                source, dest = mapping.get("source"), mapping.get("destination")
                if source and dest:
                    row_position = self.path_table.rowCount()
                    self.path_table.insertRow(row_position)
                    self.path_table.setItem(row_position, 0, QTableWidgetItem(source))
                    self.path_table.setItem(row_position, 1, QTableWidgetItem(dest))

    def add_mapping(self):
        dialog = PathMappingDialog(parent=self)
        source, dest = dialog.get_paths()
        if source and dest:
            row_position = self.path_table.rowCount()
            self.path_table.insertRow(row_position)
            self.path_table.setItem(row_position, 0, QTableWidgetItem(source))
            self.path_table.setItem(row_position, 1, QTableWidgetItem(dest))
    
    def edit_mapping(self):
        current_row = self.path_table.currentRow()
        if current_row < 0:
            return
        source_item = self.path_table.item(current_row, 0)
        dest_item = self.path_table.item(current_row, 1)
        dialog = PathMappingDialog(parent=self, source=source_item.text(), destination=dest_item.text())
        source, dest = dialog.get_paths()
        if source and dest:
            source_item.setText(source)
            dest_item.setText(dest)

    def remove_mapping(self):
        current_row = self.path_table.currentRow()
        if current_row >= 0:
            self.path_table.removeRow(current_row)

    def save_and_accept(self):
        self.config_handler.set_setting("use_nvenc", self.nvenc_checkbox.isChecked())
        self.config_handler.set_setting("use_two_pass", self.two_pass_checkbox.isChecked())
        self.config_handler.set_setting("delete_source_on_success", self.delete_source_checkbox.isChecked())
        self.config_handler.set_setting("crf_value", self.quality_spinbox.value())
        
        self.config_handler.set_setting("filename_template", self.template_edit.text())
        scan_types = [t.strip() for t in self.scan_types_edit.text().split(",") if t.strip()]
        self.config_handler.set_setting("scannable_file_types", scan_types)
        
        if TMDB_ENABLED:
            api_key = self.api_key_edit.text()
            self.config_handler.set_setting("tmdb_api_key", api_key)
            self.config_handler.save_api_key(api_key)

        mappings = []
        for row in range(self.path_table.rowCount()):
            source_item = self.path_table.item(row, 0)
            dest_item = self.path_table.item(row, 1)
            if source_item and dest_item and source_item.text() and dest_item.text():
                mappings.append({"source": source_item.text(), "destination": dest_item.text()})
        self.config_handler.set_setting("path_mappings", mappings)
        
        self.config_handler.save_config()
        self.accept()

# All other classes (Worker, MediaFileItemWidget, Dashboard, etc.) follow below.
# This structure ensures all classes are defined before they are instantiated.
# Due to length limitations, only the top portion is shown, but the full script
# should be used from the previous complete response, with the updated _clean_search_query function.

# ... The rest of the file follows, same as the last complete version ...

class Worker(QObject):
    finished = pyqtSignal(object); error = pyqtSignal(tuple); progress = pyqtSignal(int, str)
    item_status_changed = pyqtSignal(str, str)
    item_progress = pyqtSignal(str, int)
    
    def __init__(self, fn: Callable, *args, **kwargs):
        super().__init__(); self.fn, self.args, self.kwargs = fn, args, kwargs
    def run(self):
        try:
            if 'progress_callback' in inspect.signature(self.fn).parameters:
                self.kwargs['progress_callback'] = lambda p, s: self.progress.emit(p, s)
            if 'item_status_emitter' in inspect.signature(self.fn).parameters:
                self.kwargs['item_status_emitter'] = lambda p, s: self.item_status_changed.emit(p, s)
            if 'item_progress_emitter' in inspect.signature(self.fn).parameters:
                self.kwargs['item_progress_emitter'] = lambda p, i: self.item_progress.emit(p, i)
            result = self.fn(*self.args, **self.kwargs); self.finished.emit(result)
        except Exception as e: import traceback; self.error.emit((type(e), e, traceback.format_exc()))

class MediaFileItemWidget(QFrame):
    def __init__(self, media_file: MediaFile, dashboard_ref: 'Dashboard'):
        super().__init__()
        self.media_file = media_file
        self.dashboard_ref = dashboard_ref
        self.setObjectName("MediaFileItemWidget")
        
        # --- Defensively ensure all required attributes exist ---
        for attr, default in [('title', self.media_file.source_path.stem), ('output_filename', self.media_file.source_path.with_suffix('.mp4').name), ('status', 'Ready'), ('subtitle_tracks', []), ('original_size_gb', 0.0), ('converted_size_gb', 0.0), ('size_change_percent', 0.0), ('error_message', ''), ('burned_subtitle', None), ('use_basic_conversion', False)]:
            if not hasattr(self.media_file, attr): setattr(self.media_file, attr, default)
        
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
        self._create_progress_view()
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
        
        self.fetch_meta_btn = QPushButton("☁️ Fetch Metadata...")
        self.rename_btn = QPushButton("✏️ Edit Metadata...")
        self.preview_sub_btn = QPushButton("🔍 Preview Snippet...")
        self.edit_sub_btn = QPushButton("✂️ Edit/Remove Tracks...")
        
        self.fetch_meta_btn.setEnabled(TMDB_ENABLED)
        if not TMDB_ENABLED:
            self.fetch_meta_btn.setToolTip("tmdb_client.py not found.")
            
        tools_layout.addWidget(self.fetch_meta_btn)
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
        
        self.fetch_meta_btn.clicked.connect(self.open_metadata_fetch)
        self.burn_combo.currentIndexChanged.connect(self.update_conversion_profile_summary)
        self.remux_checkbox.stateChanged.connect(self.update_conversion_profile_summary)
        self.rename_btn.clicked.connect(lambda: self.open_rename_dialog())
        self.preview_sub_btn.clicked.connect(self.open_subtitle_preview)
        self.edit_sub_btn.clicked.connect(self.open_subtitle_editor)

    def open_metadata_fetch(self):
        """Opens the TMDb search dialog."""
        if not tmdb_client.get_api_key():
            QMessageBox.warning(self, "API Key Required", "Please set your TMDb API key in Settings first.")
            return
            
        search_dialog = MetadataSearchDialog(self.media_file.filename, self)
        selected_movie = search_dialog.get_selected_movie()
        
        if selected_movie:
            # Open the edit dialog and pre-fill it with the fetched data
            self.open_rename_dialog(fetched_data=selected_movie)
    
    def open_rename_dialog(self, fetched_data: Optional[Dict] = None):
        template = self.dashboard_ref.config_handler.get_setting("filename_template", "{title} ({year})")
        dialog = RenameDialog(self.media_file, template, self)
        
        if fetched_data:
            dialog.set_fetched_metadata(fetched_data)
        
        results = dialog.get_results()
        if results:
            filename, title, year, comment = results
            self.media_file.output_filename = filename
            self.media_file.title = title
            self.media_file.year = year
            self.media_file.comment = comment
            self.refresh_state()

    def open_subtitle_preview(self):
        dialog = SubtitlePreviewDialog(self.media_file, self)
        dialog.exec()

    def open_subtitle_editor(self):
        dialog = SubtitleEditorDialog(self.media_file, self)
        dialog.track_modified.connect(self.dashboard_ref.refresh_list_item_by_widget)
        dialog.exec()

    def _create_summary_view(self):
        widget = QWidget()
        summary_layout = QVBoxLayout(widget)
        self.orig_size_label = QLabel()
        self.new_size_label = QLabel()
        self.size_change_label = QLabel()
        self.audio_details_label = QLabel()
        self.subs_details_label = QLabel()
        summary_layout.addWidget(self.orig_size_label)
        summary_layout.addWidget(self.new_size_label)
        summary_layout.addWidget(self.size_change_label)
        summary_layout.addWidget(self.audio_details_label)
        summary_layout.addWidget(self.subs_details_label)
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

    def _create_progress_view(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.item_status_label = QLabel("Starting...")
        self.item_progress_bar = QProgressBar()
        layout.addWidget(self.item_status_label)
        layout.addWidget(self.item_progress_bar)
        self.stack.addWidget(widget)

    def set_status_view(self, status: str):
        self.stack.setCurrentIndex(3)
        self.item_status_label.setText(status)
        self.item_progress_bar.setValue(0)

    def update_item_progress(self, percent: int, status_text: str):
        if self.stack.currentIndex() != 3:
            self.stack.setCurrentIndex(3)
        self.item_status_label.setText(status_text)
        self.item_progress_bar.setValue(percent)
        
    def show_conversion_preview(self, switch_to_view=True):
        self.update_media_file_from_ui()
        settings = self.dashboard_ref.get_current_settings()
        if hasattr(self.media_file, 'generate_preview') and settings:
            preview_text = self.media_file.generate_preview(settings)
            self.preview_display.setText(preview_text)
        if switch_to_view:
            self.stack.setCurrentIndex(2)
    
    def get_safe_display_name(self, track: SubtitleTrack) -> str:
        index = getattr(track, 'index', 'N/A')
        title = getattr(track, 'title', '')
        lang = getattr(track, 'language', 'und')
        return title or lang.upper() or f"Track {index}"

    def refresh_state(self):
        # Update output filename from template
        template = self.dashboard_ref.config_handler.get_setting("filename_template", "{title}")
        self.media_file.output_filename = self.media_file.generate_filename_from_template(template)
        
        title = getattr(self.media_file, 'title', getattr(self.media_file, 'filename', ''))
        self.filename_label.setText(f"<b>{title}</b> → <i>{self.media_file.output_filename}</i>")
        status = self.media_file.status
        self.status_label.setText(f"Status: {status}")
        
        if status in ["Preparing", "Queued", "Remuxing", "Encoding Pass 1/2", "Encoding Pass 2/2"]:
            self.set_status_view(status)
        elif status in ["Converted", "Transferred", "Skipped (Exists)", "Converted (Basic)", "Error"]:
            self.stack.setCurrentIndex(1)
            self.orig_size_label.setText(f"Original: {self.media_file.original_size_gb:.2f} GB")
            self.new_size_label.setText(f"Converted: {self.media_file.converted_size_gb:.2f} GB")
            self.size_change_label.setText(f"Change: {self.media_file.size_change_percent:+.2f}%")
            self.audio_details_label.setText(f"Audio: {getattr(self.media_file, 'audio_conversion_details', 'N/A')}")
            
            burned_sub = next((self.get_safe_display_name(s) for s in self.media_file.subtitle_tracks if getattr(s, 'action', 'ignore') == 'burn'), "None")
            copied_subs = ", ".join([self.get_safe_display_name(s) for s in self.media_file.subtitle_tracks if getattr(s, 'action', 'ignore') == 'copy']) or "None"
            
            self.subs_details_label.setText(f"Subs Burned: {burned_sub} | Copied: {copied_subs}")
            if status == "Error":
                self.subs_details_label.setText(f"Error: {self.media_file.error_message}")
        else:
            self.stack.setCurrentIndex(0)
            self.metadata_video_label.setText(f"Video: {getattr(self.media_file, 'video_codec', 'N/A')}, {getattr(self.media_file, 'video_width', 'N/A')}p")
            self.metadata_audio_label.setText(f"Audio: {getattr(self.media_file, 'audio_codec', 'N/A')}, {getattr(self.media_file, 'audio_channels', 'N/A')}ch")
            self.metadata_size_label.setText(f"Size: {self.media_file.original_size_gb:.2f} GB")
            self.populate_selection_controls()
            self.update_conversion_profile_summary()

    def populate_selection_controls(self):
        self.burn_combo.blockSignals(True)
        self.burn_combo.clear(); self.burn_combo.addItem("None", None)
        for track in self.media_file.subtitle_tracks:
            self.burn_combo.addItem(self.get_safe_display_name(track), track)
            if self.media_file.burned_subtitle and getattr(self.media_file.burned_subtitle, 'index', -1) == getattr(track, 'index', -2): self.burn_combo.setCurrentIndex(self.burn_combo.count() - 1)
        self.burn_combo.blockSignals(False)
        
        while self.soft_copy_layout.count() > 1:
            child = self.soft_copy_layout.takeAt(1)
            if child and child.widget(): child.widget().deleteLater()
        
        self.soft_copy_checkboxes = []
        for track in self.media_file.subtitle_tracks:
            if getattr(track, 'is_text_based', False):
                cb = QCheckBox(self.get_safe_display_name(track)); cb.setProperty("track", track);
                cb.stateChanged.connect(self.update_conversion_profile_summary)
                self.soft_copy_checkboxes.append(cb); self.soft_copy_layout.addWidget(cb)

    def update_conversion_profile_summary(self):
        settings = self.dashboard_ref.get_current_settings()
        if not settings: return
        
        video_action = "Copy (Remux)"
        if self.remux_checkbox.isChecked(): video_action = "Copy (Fast Remux)"
        elif self.burn_combo.currentData() is not None: video_action = f"Re-encode to {getattr(settings, 'video_codec', 'N/A').upper()}"
        self.profile_video_label.setText(f"Video: {video_action}")

        audio_codec = getattr(self.media_file, 'audio_codec', '').lower()
        compatible_audio = ['aac', 'ac3', 'eac3']
        if self.remux_checkbox.isChecked() or (audio_codec and audio_codec in compatible_audio):
             audio_action = f"Copy existing {audio_codec.upper()}"
        else:
             audio_action = f"Re-encode to {getattr(settings, 'audio_codec', 'N/A').upper()}"
        self.profile_audio_label.setText(f"Audio: {audio_action}")

        burned_track = self.burn_combo.currentData()
        self.profile_burn_label.setText(f"Burn-in: {self.get_safe_display_name(burned_track) if burned_track else 'None'}")
        
        copied_subs = [cb.text() for cb in self.soft_copy_checkboxes if cb.isChecked()]
        self.profile_copy_label.setText(f"Copy Subs: {len(copied_subs)} track(s)")

    def update_media_file_from_ui(self):
        if self.remux_checkbox.isChecked():
            self.media_file.use_basic_conversion = True
        elif hasattr(self.media_file, 'classify'):
            self.media_file.use_basic_conversion = (self.media_file.classify() == 'remux')
        else:
            self.media_file.use_basic_conversion = False

        self.media_file.burned_subtitle = self.burn_combo.currentData()
        for track in self.media_file.subtitle_tracks: track.action = "ignore"
        if self.media_file.burned_subtitle: self.media_file.burned_subtitle.action = "burn"
        for cb in self.soft_copy_checkboxes:
            track_data = cb.property("track")
            if cb.isChecked() and track_data:
                burn_idx = getattr(self.media_file.burned_subtitle, 'index', -1)
                track_idx = getattr(track_data, 'index', -2)
                if not (self.media_file.burned_subtitle and burn_idx == track_idx): track_data.action = "copy"
class Dashboard(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle("G's Movie Converter")
        self.setGeometry(100, 100, 1400, 800)
        
        icon_path = resource_path("icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.title_bar = CustomTitleBar(self)
        self.main_layout.addWidget(self.title_bar)
        
        self.content_widget = QWidget()
        self.layout = QVBoxLayout(self.content_widget)
        self.main_layout.addWidget(self.content_widget)
        
        self.media_files_data: List[MediaFile] = []
        self.thread = None
        self.worker = None
        self.config_handler = ConfigHandler()
        
        top_controls = QHBoxLayout()
        self.scan_config_button = QPushButton("Scan Configured Folders", clicked=self.scan_configured_folders)
        self.scan_custom_button = QPushButton("Scan Custom Folder...", clicked=self.scan_custom_folder)
        self.settings_button = QPushButton("Settings", clicked=self.open_settings)
        top_controls.addWidget(self.scan_config_button)
        top_controls.addWidget(self.scan_custom_button)
        top_controls.addStretch()
        top_controls.addWidget(self.settings_button)
        self.layout.addLayout(top_controls)
        
        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.file_list.itemSelectionChanged.connect(self.update_selection_styles)
        self.layout.addWidget(self.file_list, 1)
        
        self.bottom_button_stack = QStackedWidget()
        self._create_normal_buttons()
        self.layout.addWidget(self.bottom_button_stack)
        
        self.status_bar = QStatusBar()
        self.layout.addWidget(self.status_bar)
        self.status_bar.showMessage("Ready. Configure scan/transfer paths in Settings.")
        
        try:
            with open(resource_path("styles.css"), "r") as f:
                self.setStyleSheet(f.read())
        except Exception as e:
            print(f"Could not load stylesheet: {e}")
            QApplication.instance().setStyle("Fusion")

    def _create_normal_buttons(self):
        normal_widget = QWidget(); bottom_controls = QHBoxLayout(normal_widget)
        self.progress_bar = QProgressBar(); self.progress_bar.setVisible(False)
        self.preview_plan_button = QPushButton("Preview Conversion Plan", clicked=self.show_conversion_plan_preview)
        self.convert_button = QPushButton("Convert Selected", clicked=self.start_conversion)
        self.transfer_button = QPushButton("Transfer Files", clicked=self.start_transfer)
        self.cancel_button = QPushButton("Cancel", clicked=self.cancel_task); self.cancel_button.setEnabled(False)
        bottom_controls.addWidget(self.progress_bar, 1)
        bottom_controls.addWidget(self.preview_plan_button)
        bottom_controls.addWidget(self.convert_button)
        bottom_controls.addWidget(self.transfer_button); bottom_controls.addWidget(self.cancel_button)
        self.bottom_button_stack.addWidget(normal_widget)

    def _run_task(self, task_function: Callable, on_finish: Callable, *args, **kwargs):
        self.set_buttons_enabled(False); self.status_bar.showMessage(f"Running {task_function.__name__}...")
        self.thread = QThread(); self.worker = Worker(task_function, *args, **kwargs); self.worker.moveToThread(self.thread)
        self.worker.item_status_changed.connect(self.on_item_status_changed)
        self.worker.item_progress.connect(self.on_item_progress)
        self.thread.started.connect(self.worker.run); self.worker.progress.connect(self.update_progress); self.worker.finished.connect(on_finish); self.worker.error.connect(self.on_task_error)
        self.worker.finished.connect(self.thread.quit); self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater); self.thread.finished.connect(lambda: self.set_buttons_enabled(True))
        self.thread.start()

    def find_item_widget_by_path(self, file_path_str: str) -> Union[MediaFileItemWidget, None]:
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            widget = self.file_list.itemWidget(item)
            if str(widget.media_file.source_path) == file_path_str:
                return widget
        return None

    def on_item_status_changed(self, file_path_str: str, status: str):
        widget = self.find_item_widget_by_path(file_path_str)
        if widget:
            widget.media_file.status = status
            widget.update_item_progress(widget.item_progress_bar.value(), status)

    def on_item_progress(self, file_path_str: str, percent: int):
        widget = self.find_item_widget_by_path(file_path_str)
        if widget:
            widget.update_item_progress(percent, widget.media_file.status)

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

    def open_settings(self):
        SettingsWindow(self.config_handler, self).exec()

    def _scan_multiple_dirs(self, dir_paths: List[Path], file_types: List[str]) -> List[MediaFile]:
        all_files = []
        for dir_path in dir_paths:
            all_files.extend(subtitlesmkv.scan_directory(dir_path, file_types))
        return all_files

    def scan_configured_folders(self):
        path_mappings = self.config_handler.get_setting("path_mappings", [])
        if not path_mappings:
            self.show_message("No Scan Directories", "Please configure at least one path mapping in Settings.")
            return
        scan_dirs = [Path(m["source"]) for m in path_mappings if Path(m["source"]).is_dir()]
        if not scan_dirs:
            self.show_message("Invalid Scan Directories", "None of the configured source paths exist. Please check your settings.")
            return
        
        file_types = self.config_handler.get_setting("scannable_file_types", [".mkv"])
        self._run_task(self._scan_multiple_dirs, self.on_scan_finished, dir_paths=scan_dirs, file_types=file_types)

    def scan_custom_folder(self):
        if folder := QFileDialog.getExistingDirectory(self, "Select Folder"):
            file_types = self.config_handler.get_setting("scannable_file_types", [".mkv"])
            self._run_task(self._scan_multiple_dirs, self.on_scan_finished, dir_paths=[Path(folder)], file_types=file_types)
            
    def on_scan_finished(self, result: List[MediaFile]):
        self.media_files_data = result
        self.populate_file_list()
        self.status_bar.showMessage(f"Scan complete. Found {len(result)} files.")

    def populate_file_list(self):
        self.file_list.clear()
        for media_file in self.media_files_data:
            item_widget = MediaFileItemWidget(media_file, self)
            list_item = QListWidgetItem(self.file_list)
            list_item.setData(Qt.ItemDataRole.UserRole, media_file)
            list_item.setSizeHint(item_widget.sizeHint())
            self.file_list.addItem(list_item)
            self.file_list.setItemWidget(list_item, item_widget)
        self.update_selection_styles()

    def get_selected_media_files(self) -> List[MediaFile]:
        selected_items = self.file_list.selectedItems()
        if not selected_items:
             return [self.file_list.itemWidget(self.file_list.item(i)).media_file for i in range(self.file_list.count())]
        return [self.file_list.itemWidget(item).media_file for item in selected_items]

    def _run_combined_conversion(self, files: List[MediaFile], settings: ConversionSettings, 
                                 progress_callback: Callable, item_status_emitter: Callable, 
                                 item_progress_emitter: Callable):
        for f in files:
            widget = self.find_item_widget_by_path(str(f.source_path))
            if widget:
                widget.update_media_file_from_ui()
            item_status_emitter(str(f.source_path), "Queued")
        
        basic_files = [f for f in files if getattr(f, 'use_basic_conversion', False)]
        advanced_files = [f for f in files if not getattr(f, 'use_basic_conversion', False)]

        if basic_files:
            basic_convert.run_batch_basic_conversion(basic_files, settings)
        
        if advanced_files:
            convert.convert_batch(advanced_files, settings, progress_callback, item_status_emitter, item_progress_emitter)
        
        return files

    def start_conversion(self):
        files = self.get_selected_media_files()
        if not files:
            self.show_message("No Files", "No files to convert.")
            return
        settings = self.get_current_settings()
        if not settings: return
        
        try:
            settings.output_directory.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.show_message("Error", f"Could not create output directory.\n{e}")
            return
        
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

    def get_current_settings(self) -> Union[ConversionSettings, None]:
        try:
            return ConversionSettings(
                output_directory=Path(self.config_handler.get_setting("output_directory", "./converted")), 
                use_nvenc=self.config_handler.get_setting("use_nvenc"),
                crf=self.config_handler.get_setting("crf_value"), 
                delete_source_on_success=self.config_handler.get_setting("delete_source_on_success"),
                use_two_pass=self.config_handler.get_setting("use_two_pass"),
                filename_template=self.config_handler.get_setting("filename_template", "{title}"),
                scannable_file_types=self.config_handler.get_setting("scannable_file_types", [".mkv"])
            )
        except Exception as e:
            self.show_message("Settings Error", f"Could not create conversion settings. Please check your config.\nError: {e}")
            return None

    def start_transfer(self):
        # MODIFIED: Select all .mp4 files plus any other files that were successfully converted.
        files_to_transfer = [
            mf for mf in self.media_files_data 
            if mf.source_path.suffix.lower() == '.mp4' 
            or getattr(mf, 'status', '') in ["Converted", "Converted (Basic)"]
        ]

        if not files_to_transfer:
            self.show_message("No Files to Transfer", "There are no .mp4 or successfully converted files ready to be moved.")
            return

        path_mappings = self.config_handler.get_setting("path_mappings", [])
        if not path_mappings:
            self.show_message("Destination Not Set", "Please configure at least one path mapping in Settings before transferring files.")
            return
        
        # MODIFIED: Update confirmation message
        reply = QMessageBox.question(self, "Confirm Transfer", 
            f"You are about to move {len(files_to_transfer)} file(s) (all .mp4s and converted files) to their configured destinations.\n\nThis action cannot be undone. Do you want to proceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            self.status_bar.showMessage("Starting file transfer...")
            self._run_task(
                file_handler.move_converted_files, 
                self.on_action_finished,
                media_files=files_to_transfer, 
                path_mappings=path_mappings
            )

    def on_action_finished(self, result):
        self.refresh_ui()
        self.status_bar.showMessage("Task finished successfully.")

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
            # Preserve user-edited metadata after a refresh
            new_media_file_state.output_filename = widget.media_file.output_filename
            new_media_file_state.title = widget.media_file.title
            new_media_file_state.year = widget.media_file.year
            new_media_file_state.comment = widget.media_file.comment
            
            for i, mf in enumerate(self.media_files_data):
                if mf.source_path == new_media_file_state.source_path:
                    self.media_files_data[i] = new_media_file_state
                    break
            item.setData(Qt.ItemDataRole.UserRole, new_media_file_state)
            widget.media_file = new_media_file_state
            widget.refresh_state()

    def update_selection_styles(self):
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            widget = self.file_list.itemWidget(item)
            if widget:
                widget.setProperty("selected", item.isSelected())
                widget.style().unpolish(widget)
                widget.style().polish(widget)

    def on_task_error(self, error: Tuple):
        self.status_bar.showMessage(f"Error occurred: {error[1]}", 10000)
        advice = "\n\nAdvice: Check that all configured paths in Settings are correct and accessible." if "No such file or directory" in str(error[1]) else ""
        self.show_message("Error", f"Task failed:\n{error[1]}{advice}")
        print(error[2])

    def show_message(self, title: str, message: str):
        msg_box = QMessageBox(self); msg_box.setWindowTitle(title); msg_box.setText(message); msg_box.exec()

if __name__ == "__main__":
    from multiprocessing import freeze_support
    freeze_support()
    
    app = QApplication(sys.argv)
    window = Dashboard()
    window.show()
    sys.exit(app.exec())