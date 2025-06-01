import sys
import os
import subprocess
from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QLabel, QVBoxLayout, QFrame
)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt

class ScriptDashboard(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("⚾️🎮💻☑️")
        self.setStyleSheet("background-color: #0f0f0f; color: white; font-size: 16px;")
        self.setFixedSize(450, 500)

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(30, 20, 30, 10)
        main_layout.setSpacing(8)

        # Header
        header_container = QFrame()
        header_container.setStyleSheet("background-color: rgba(30, 30, 30, 0.92); border-radius: 16px;")
        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(24, 4, 24, 4)
        header_label = QLabel("G - Home 💻")
        header_label.setAlignment(Qt.AlignCenter)
        header_label.setFont(QFont("Arial", 30, QFont.Bold))
        header_label.setStyleSheet("color: white; padding: 4px 0;")
        header_layout.addWidget(header_label)
        header_container.setLayout(header_layout)
        main_layout.addWidget(header_container)

        # Button style
        btn_style = """
            QPushButton {
                background-color: #0078d4;
                color: white;
                border-radius: 8px;
                padding: 12px;
            }
            QPushButton:hover {
                background-color: #005fa3;
            }
        """

        # Determine script directory based on execution context
        if getattr(sys, 'frozen', False):
            script_dir = os.path.join(os.path.dirname(sys.executable), '..', 'Resources')
        else:
            script_dir = os.path.dirname(os.path.abspath(__file__))

        script_dir = os.path.abspath(script_dir)

        # Discover scripts
        script_files = []
        if os.path.exists(script_dir):
            for filename in os.listdir(script_dir):
                if filename.endswith(".py") and filename not in ("Dashboard.py", "__init__.py", "setup.py"):
                    label = os.path.splitext(filename)[0].replace("_", " ").title()
                    script_files.append((label, os.path.join(script_dir, filename)))

        for name, path in script_files:
            btn = QPushButton(name)
            btn.setStyleSheet(btn_style)
            btn.clicked.connect(lambda _, p=path: self.run_script(p))
            main_layout.addWidget(btn)

        # Footer
        footer = QLabel("Creativity is thinking up new things – Innovation is doing new things.")
        footer.setAlignment(Qt.AlignCenter)
        footer.setWordWrap(True)
        footer.setStyleSheet("color: gray; font-size: 12px; padding: 0px; margin: 0px;")
        main_layout.addWidget(footer)

        self.setLayout(main_layout)

    def run_script(self, script_path):
        try:
            subprocess.Popen([
                "osascript", "-e",
                f'tell application "Terminal" to do script "python3 \\"{script_path}\\""'
            ])
        except Exception as e:
            print(f"Error launching script: {e}")
        
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ScriptDashboard()
    window.show()
    sys.exit(app.exec_())