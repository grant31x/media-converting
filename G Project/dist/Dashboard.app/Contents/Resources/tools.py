import os
import subprocess
import threading
import tkinter as tk
import customtkinter as ctk
import shutil
import requests
import netifaces
from pathlib import Path
from datetime import datetime
from rich.console import Console
import argparse

# Initialize Rich console
console = Console()

# Logging
LOG_FILE = Path.home() / "mac_maintenance.log"
def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as log_file:
        log_file.write(f"[{timestamp}] {message}\n")

def run_command(command):
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        output = result.stdout.strip() + '\n' + result.stderr.strip()
        log(output)
        return output
    except Exception as e:
        log(str(e))
        return str(e)

# Core Functions
def update_brew():
    return run_command("brew update && brew upgrade && brew cleanup")

def update_pip():
    return run_command("pip list --outdated --format=freeze | cut -d = -f 1 | xargs -n1 pip install -U")

def clean_temp_dirs():
    user_cache = str(Path.home() / "Library/Caches")
    var_folders = "/private/var/folders"
    output = []
    for path in [user_cache, var_folders]:
        for root, dirs, files in os.walk(path):
            for name in files:
                try:
                    os.remove(os.path.join(root, name))
                except:
                    pass
            for name in dirs:
                try:
                    shutil.rmtree(os.path.join(root, name), ignore_errors=True)
                except:
                    pass
        output.append(f"Cleaned: {path}")
    return "\n".join(output)

def analyze_storage():
    return run_command("du -h ~ | sort -hr | head -n 10")

def remove_orphaned_brew():
    return run_command("brew autoremove")

def clear_trash():
    trash = Path.home() / ".Trash"
    for item in trash.iterdir():
        try:
            if item.is_file():
                item.unlink()
            else:
                shutil.rmtree(item)
        except:
            pass
    return "Trash cleared."

def verify_disk():
    return run_command("diskutil verifyVolume /")

def list_login_items():
    return run_command("""osascript -e 'tell application "System Events" to get the name of every login item'""")

def show_uptime():
    return run_command("uptime")

def find_large_files():
    return run_command("find ~ -type f -size +100M")

def get_network_info():
    hostname = run_command("hostname").strip()
    local_ip = netifaces.ifaddresses(netifaces.gateways()['default'][netifaces.AF_INET][1])[netifaces.AF_INET][0]['addr']
    try:
        public_ip = requests.get("https://api.ipify.org").text
    except:
        public_ip = "Unavailable"
    return f"🛜 Network\nHostname: {hostname}\nLocal IP: {local_ip}\nPublic IP: {public_ip}"

def get_storage_info():
    total, used, free = shutil.disk_usage("/")
    gb = lambda b: round(b / (1024 ** 3))
    return f"💻 Storage\n{gb(free)} / {gb(total)} GB Free"

# GUI Components
class MaintenanceApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.current_tab = tk.StringVar(value="Maintenance")

        # Sidebar (left column)
        self.sidebar = ctk.CTkFrame(self, corner_radius=10)
        self.sidebar.grid(row=0, column=0, rowspan=2, sticky="nsnsw", padx=(10, 5), pady=10)
        self.sidebar.grid_rowconfigure(2, weight=1)

        # Logo / Title
        self.sidebar_title = ctk.CTkLabel(self.sidebar, text="Mac Maintenance", font=ctk.CTkFont(size=18, weight="bold"))
        self.sidebar_title.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="w")

        # Info Display
        self.info_label = ctk.CTkLabel(self.sidebar, text=self.get_info(), justify="left", anchor="w", font=ctk.CTkFont(size=12))
        self.info_label.grid(row=1, column=0, sticky="new", padx=10)

        # Button Container (scrollable)
        self.button_container = ctk.CTkScrollableFrame(self.sidebar, corner_radius=0)
        self.button_container.grid(row=2, column=0, sticky="nswe", padx=10, pady=(10, 0))

        # Tab bar and output area (right column)
        self.tab_bar = ctk.CTkSegmentedButton(self, values=["Maintenance", "Network", "Security"], variable=self.current_tab, command=self.switch_tab)
        self.tab_bar.grid(row=0, column=1, sticky="new", padx=(5, 10), pady=(10, 5))

        # Console output (task log)
        self.console = ctk.CTkTextbox(self, wrap="word")
        self.console.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=(0, 10))

        self.title("Mac Maintenance Assistant")
        self.geometry("900x600")

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.maintenance_buttons = {
            "Update Homebrew": update_brew,
            "Update Pip": update_pip,
            "Clean Temp Dirs": clean_temp_dirs,
            "Analyze Storage": analyze_storage,
            "Remove Orphaned Brew": remove_orphaned_brew,
            "Clear Trash": clear_trash,
            "Verify Disk": verify_disk,
            "Login Items": list_login_items,
            "Show Uptime": show_uptime,
            "Find 100MB+ Files": find_large_files,
        }

        def device_discovery():
            try:
                iface = netifaces.gateways()['default'][netifaces.AF_INET][1]
                ip_info = netifaces.ifaddresses(iface)[netifaces.AF_INET][0]
                ip_addr = ip_info['addr']
                netmask = ip_info['netmask']

                # Convert netmask to CIDR
                cidr = sum(bin(int(x)).count('1') for x in netmask.split('.'))
                subnet = f"{ip_addr.rsplit('.', 1)[0]}.0/{cidr}"
            except Exception as e:
                return f"❌ Failed to detect network: {e}"

            output = run_command(f"nmap -sn {subnet}")
            results = []
            lines = output.splitlines()
            current_ip = ""
            for line in lines:
                if line.startswith("Nmap scan report for"):
                    current_ip = line.split()[-1]
                if "MAC Address" in line:
                    mac = line.split("MAC Address: ")[1]
                    results.append(f"{current_ip} — {mac}")
            if not results:
                return f"❌ No devices found on {subnet} (nmap may not be installed or blocked by firewall)."
            return f"🧭 Active Devices on {subnet}:\n" + "\n".join(results)

        self.network_buttons = {
            "Device Discovery": device_discovery
        }

        self.security_buttons = {
            "Check SIP Status": lambda: self.console.insert(tk.END, "🔐 SIP check not yet implemented\n"),
        }

        self.load_buttons(self.maintenance_buttons)

    def get_info(self):
        return get_network_info() + "\n\n" + get_storage_info()

    def load_buttons(self, button_dict):
        for widget in self.button_container.winfo_children():
            widget.destroy()
        run_all_button = ctk.CTkButton(self.button_container, text="🚀 Run All", fg_color="green", font=ctk.CTkFont(size=13, weight="bold"), command=self.run_all)
        run_all_button.pack(pady=(0, 10), padx=5, fill="x")

        for label, func in button_dict.items():
            btn = ctk.CTkButton(self.button_container, text=label, font=ctk.CTkFont(size=12), command=lambda f=func, l=label: self.run_task(f, l))
            btn.pack(pady=5, padx=5, fill="x")

    def switch_tab(self, value):
        if value == "Maintenance":
            self.load_buttons(self.maintenance_buttons)
        elif value == "Network":
            self.load_buttons(self.network_buttons)
        elif value == "Security":
            self.load_buttons(self.security_buttons)

    def run_task(self, func, label):
        def task():
            self.console.insert(tk.END, f"\n⏳ Running {label}...\n")
            output = func()
            self.console.insert(tk.END, f"{output}\n✅ {label} Done.\n")
            self.console.see(tk.END)
        threading.Thread(target=task).start()

    def run_all(self):
        tab = self.current_tab.get()
        if tab == "Maintenance":
            buttons = self.maintenance_buttons
        elif tab == "Network":
            buttons = self.network_buttons
        elif tab == "Security":
            buttons = self.security_buttons
        else:
            buttons = {}
        for label, func in buttons.items():
            self.run_task(func, label)

# CLI Mode
def run_cli():
    all_tasks = [
        ("Update Homebrew", update_brew),
        ("Update Pip", update_pip),
        ("Clean Temp Dirs", clean_temp_dirs),
        ("Analyze Storage", analyze_storage),
        ("Remove Orphaned Brew", remove_orphaned_brew),
        ("Clear Trash", clear_trash),
        ("Verify Disk", verify_disk),
        ("Login Items", list_login_items),
        ("Show Uptime", show_uptime),
        ("Find 100MB+ Files", find_large_files),
    ]
    console.print("[bold cyan]🔧 Starting Mac Maintenance...[/bold cyan]")
    for label, func in all_tasks:
        console.print(f"[yellow]⏳ {label}...[/yellow]")
        output = func()
        console.print(f"[green]✅ {label} Completed.[/green]\n{output}")
    console.print("[bold green]🎉 All tasks completed![/bold green]")

# Main
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", action="store_true", help="Run in command-line mode")
    args = parser.parse_args()

    if args.cli:
        run_cli()
    else:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        app = MaintenanceApp()
        app.mainloop()