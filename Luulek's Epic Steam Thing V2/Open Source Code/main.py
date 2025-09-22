import sys
import os
import requests
import io
import zipfile
import shutil
import time
import subprocess
import json
import threading

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QListWidget, QLabel, QMessageBox, QLineEdit, QDialog, QCheckBox,
    QFileDialog, QFormLayout, QListWidgetItem, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

# Optional extras
try:
    from win10toast import ToastNotifier
    _HAS_TOAST = True
except ImportError:
    _HAS_TOAST = False

# Constants
API_URL = "https://api.github.com/repos/ayka-667/SteamTools-GameList/contents"
RAW_URL = "https://raw.githubusercontent.com/ayka-667/SteamTools-GameList/main/"
CACHE_DIR = os.path.join(os.getcwd(), "DownloadCache")
APP_TITLE = "Luulek's Epic Steam Thing V2"
APP_ICON = os.path.join(os.getcwd(), "Files", "Icon.ico")
STATE_FILE = os.path.join(os.getcwd(), "app_state.json")
FILES_DIR = os.path.join(os.getcwd(), "Files")
ONLINE_FIX_DIR = os.path.join(FILES_DIR, "OnlineFix")

# Error messages
ERR_INVALID_STEAM = "Invalid steam location is specified in settings!"
ERR_FAILED_DOWNLOAD = "Failed to download!"
ERR_NOTHING_IN_ORDER = "Nothing is in order!"
ERR_NOTHING_SELECTED = "Nothing is selected!"
ERR_NOT_UNITY = "This is not a unity game! please go to https://online-fix.me/ for manual installation"

os.makedirs(CACHE_DIR, exist_ok=True)

# Persistence helpers
def load_state():
    default = {
        'settings': {
            'steam_path': '',
            'dark_theme': True,
            'delete_after': False,
            'win_notify': False,
            'restart_steam': False
        },
        'added': []
    }
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # merge defaults
            s = default['settings']
            s.update(data.get('settings', {}))
            return {'settings': s, 'added': data.get('added', [])}
        except Exception:
            return default
    return default

def save_state(state):
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass

class SettingsWindow(QDialog):
    def __init__(self, parent=None, settings=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        layout = QFormLayout()

        self.steam_path = QLineEdit()
        browse_btn = QPushButton("Browse")
        def pick():
            path = QFileDialog.getExistingDirectory(self, "Select Steam Folder")
            if path:
                self.steam_path.setText(path)
        browse_btn.clicked.connect(pick)
        h = QHBoxLayout()
        h.addWidget(self.steam_path)
        h.addWidget(browse_btn)
        from PyQt6.QtWidgets import QWidget
        w = QWidget()
        w.setLayout(h)
        layout.addRow("Steam Location (required)", w)

        # Checkboxes
        self.dark_theme = QCheckBox("Enable Dark Theme")
        self.delete_after = QCheckBox("Delete Manifests after put into Steam (saves storage)")
        self.win_notify = QCheckBox("Input a Windows Notification when done")
        self.restart_steam = QCheckBox("Automatically restart steam after its done")
        layout.addRow(self.dark_theme)
        layout.addRow(self.delete_after)
        layout.addRow(self.win_notify)
        layout.addRow(self.restart_steam)

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.accept)
        layout.addRow(save_btn)

        self.setLayout(layout)

        if settings:
            self.steam_path.setText(settings.get('steam_path',''))
            self.dark_theme.setChecked(settings.get('dark_theme', True))
            self.delete_after.setChecked(settings.get('delete_after', False))
            self.win_notify.setChecked(settings.get('win_notify', False))
            self.restart_steam.setChecked(settings.get('restart_steam', False))

class Worker(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, items, settings_values, parent=None):
        super().__init__(parent)
        self.items = items
        self.settings = settings_values

    def run(self):
        steam_path = self.settings.get('steam_path','')
        if not steam_path or not os.path.exists(os.path.join(steam_path, 'steam.exe')):
            self.error.emit(ERR_INVALID_STEAM)
            return

        start_t = time.perf_counter()
        try:
            for name in self.items:
                url = RAW_URL + name
                resp = requests.get(url)
                if resp.status_code != 200:
                    self.error.emit(ERR_FAILED_DOWNLOAD)
                    return

                # save zip
                dest_path = os.path.join(CACHE_DIR, name)
                with open(dest_path, 'wb') as f:
                    f.write(resp.content)

                # extract into folder
                extract_dir = os.path.join(CACHE_DIR, name.replace('.zip',''))
                os.makedirs(extract_dir, exist_ok=True)
                with zipfile.ZipFile(dest_path) as z:
                    z.extractall(extract_dir)

                # delete zip after extraction
                try:
                    os.remove(dest_path)
                except Exception:
                    pass

                # copy .manifest and .lua
                depotcache = os.path.join(steam_path, 'config', 'depotcache')
                stplugin = os.path.join(steam_path, 'config', 'stplug-in')
                os.makedirs(depotcache, exist_ok=True)
                os.makedirs(stplugin, exist_ok=True)

                for root, _, files in os.walk(extract_dir):
                    for f in files:
                        if f.endswith('.manifest'):
                            try:
                                shutil.copy2(os.path.join(root,f), os.path.join(depotcache, f))
                            except Exception:
                                pass
                        if f.endswith('.lua'):
                            try:
                                shutil.copy2(os.path.join(root,f), os.path.join(stplugin, f))
                            except Exception:
                                pass

                # optionally delete extracted folder
                if self.settings.get('delete_after', False):
                    try:
                        shutil.rmtree(extract_dir)
                    except Exception:
                        pass

            elapsed = time.perf_counter() - start_t
            self.finished.emit(f"Done! ({elapsed:.3f} seconds)")

        except Exception as e:
            self.error.emit(f"Error: {e}")

class DownloaderApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        try:
            from PyQt6.QtGui import QIcon
            if os.path.exists(APP_ICON):
                self.setWindowIcon(QIcon(APP_ICON))
        except Exception:
            pass

        self.resize(1100, 520)

        # load state
        state = load_state()
        self.settings_values = state['settings']
        self.added = state.get('added', [])

        main_layout = QHBoxLayout()

        # Side buttons
        side_layout = QVBoxLayout()
        self.add_btn = QPushButton("Add")
        self.settings_btn = QPushButton("Settings")
        self.insert_fix_btn = QPushButton("Insert Online-Fix (only unity)")
        self.add_to_order_btn = QPushButton("Add To Order")
        self.start_order_btn = QPushButton("Start Order")

        self.add_btn.clicked.connect(self.add_now)
        self.insert_fix_btn.clicked.connect(self.insert_online_fix)
        self.settings_btn.clicked.connect(self.open_settings)
        self.add_to_order_btn.clicked.connect(self.add_to_order)
        self.start_order_btn.clicked.connect(self.start_order)

        side_layout.addWidget(self.add_btn)
        side_layout.addWidget(self.add_to_order_btn)
        side_layout.addWidget(self.start_order_btn)
        side_layout.addWidget(self.settings_btn)
        side_layout.addWidget(self.insert_fix_btn)
        side_layout.addStretch()

        main_layout.addLayout(side_layout)

        # Main content
        content_layout = QVBoxLayout()
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Enter a steam game name or a steam app id.")
        self.search_bar.textChanged.connect(self.filter_list)
        content_layout.addWidget(self.search_bar)
        self.label = QLabel("Fetching Manifests & LUA's from database...")
        content_layout.addWidget(self.label)
        self.list_widget = QListWidget()
        content_layout.addWidget(self.list_widget)

        main_layout.addLayout(content_layout, 3)

        # Right panel
        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel("Order"))
        self.order_list = QListWidget()
        right_layout.addWidget(self.order_list)
        right_layout.addWidget(QLabel("Previously Added"))
        self.added_list = QListWidget()
        self.added_list.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        right_layout.addWidget(self.added_list)

        main_layout.addLayout(right_layout, 1)

        self.setLayout(main_layout)

        self.files = []
        self.filtered_files = []
        self.order = []
        self.workers = []

        self.apply_theme()
        self.fetch_files()
        self.populate_added()

    def populate_added(self):
        self.added_list.clear()
        for name in self.added:
            self.added_list.addItem(name)

    def save_all_state(self):
        state = {'settings': self.settings_values, 'added': self.added}
        save_state(state)

    def fetch_files(self):
        try:
            resp = requests.get(API_URL)
            resp.raise_for_status()
            data = resp.json()
            self.files = [f['name'] for f in data if f['name'].endswith('.zip')]
            self.files.sort(key=lambda x: x.lower())
            self.filtered_files = self.files.copy()
            self.list_widget.addItems(self.files)
            self.label.setText(f"Found {len(self.files)} Manifest & Lua's. Select one to download:")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to fetch files: {e}")

    def filter_list(self, text):
        self.list_widget.clear()
        if text:
            self.filtered_files = [f for f in self.files if text.lower() in f.lower()]
        else:
            self.filtered_files = self.files.copy()
        self.list_widget.addItems(self.filtered_files)

    def add_now(self):
        selected = self.list_widget.currentItem()
        if not selected:
            QMessageBox.warning(self, "No Selection", ERR_NOTHING_SELECTED)
            return
        self.start_processing([selected.text()], mark_added=True)

    def add_to_order(self):
        selected = self.list_widget.currentItem()
        if not selected:
            QMessageBox.warning(self, "No Selection", ERR_NOTHING_SELECTED)
            return
        name = selected.text()
        self.order.append(name)
        self.order_list.addItem(name)

    def start_order(self):
        if not self.order:
            QMessageBox.warning(self, "Order", ERR_NOTHING_IN_ORDER)
            return
        items = self.order.copy()
        self.order.clear()
        self.order_list.clear()
        self.start_processing(items, mark_added=True)

    def open_settings(self):
        settings = SettingsWindow(self, settings=self.settings_values)
        if settings.exec():
            self.settings_values['steam_path'] = settings.steam_path.text()
            self.settings_values['dark_theme'] = settings.dark_theme.isChecked()
            self.settings_values['delete_after'] = settings.delete_after.isChecked()
            self.settings_values['win_notify'] = settings.win_notify.isChecked()
            self.settings_values['restart_steam'] = settings.restart_steam.isChecked()
            self.apply_theme()
            self.save_all_state()

    def apply_theme(self):
        if self.settings_values.get('dark_theme', True):
            self.setStyleSheet('''
                QWidget { background: #111111; color: #FFFFFF; }
                QLineEdit, QListWidget { background: #222222; color: #FFFFFF; }
                QCheckBox { color: #FFFFFF; }
                QPushButton { background: #1e1e1e; color: #FFFFFF; }
            ''')
        else:
            self.setStyleSheet('')

    def start_processing(self, items, mark_added=False):
        worker = Worker(items, self.settings_values)
        worker.finished.connect(self.on_worker_finished)
        worker.error.connect(self.on_worker_error)
        worker.finished.connect(lambda _: self.cleanup_worker(worker))
        worker.error.connect(lambda _: self.cleanup_worker(worker))
        worker.mark_added = mark_added
        self.workers.append(worker)
        worker.start()

    def cleanup_worker(self, worker):
        if worker in self.workers:
            self.workers.remove(worker)
            worker.quit()
            worker.wait()

    def on_worker_finished(self, message):
        QMessageBox.information(self, "Info", message)
        # toast
        if self.settings_values.get('win_notify', False) and _HAS_TOAST:
            try:
                tn = ToastNotifier()
                icon = os.path.join(FILES_DIR, 'NotificationPicture.png')
                tn.show_toast(APP_TITLE, "Done putting steam manifests and luas into steam.", icon_path=icon if os.path.exists(icon) else None, duration=5)
            except Exception:
                pass
        # restart steam
        if self.settings_values.get('restart_steam', False):
            try:
                subprocess.run(['taskkill','/F','/IM','steam.exe'], check=False)
                steam_exe = os.path.join(self.settings_values.get('steam_path',''), 'steam.exe')
                if os.path.exists(steam_exe):
                    os.startfile(steam_exe)
            except Exception:
                pass
        self.save_all_state()

    def on_worker_error(self, message):
        QMessageBox.critical(self, "Error", message)

    def insert_online_fix(self):
        target = QFileDialog.getExistingDirectory(self, "Select game folder to apply Online-Fix")
        if not target:
            return
        if not os.path.exists(os.path.join(target, 'UnityCrashHandler64.exe')):
            QMessageBox.critical(self, "Error", ERR_NOT_UNITY)
            return
        data_folder = None
        for name in os.listdir(target):
            if 'data' in name.lower():
                candidate = os.path.join(target, name)
                if os.path.isdir(candidate):
                    data_folder = candidate
                    break
        if not data_folder:
            QMessageBox.critical(self, "Error", ERR_NOT_UNITY)
            return
        src = ONLINE_FIX_DIR
        if not os.path.exists(src):
            QMessageBox.critical(self, "Error", "OnlineFix folder missing from Files folder")
            return
        src_data = os.path.join(src, 'Data')
        if not os.path.exists(src_data) or not os.path.isdir(src_data):
            QMessageBox.critical(self, "Error", "OnlineFix/Data missing in Files/OnlineFix")
            return
        try:
            for item in os.listdir(src):
                s = os.path.join(src, item)
                if item.lower() == 'data':
                    continue
                dest = os.path.join(target, item)
                if os.path.isdir(s):
                    if os.path.exists(dest):
                        shutil.rmtree(dest)
                    shutil.copytree(s, dest)
                else:
                    shutil.copy2(s, dest)
            for root, dirs, files in os.walk(src_data):
                rel = os.path.relpath(root, src_data)
                dest_root = os.path.join(data_folder, rel) if rel != '.' else data_folder
                os.makedirs(dest_root, exist_ok=True)
                for f in files:
                    sfile = os.path.join(root, f)
                    dfile = os.path.join(dest_root, f)
                    try:
                        shutil.copy2(sfile, dfile)
                    except Exception:
                        pass
            QMessageBox.information(self, "Info", "Done! (Online-Fix applied)")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Online-Fix failed: {e}")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = DownloaderApp()
    window.show()
    sys.exit(app.exec())
