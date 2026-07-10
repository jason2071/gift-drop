"""cx_Freeze build config for the Windows .msi installer.

Build with:  python setup_msi.py bdist_msi
Output:      dist/GiftDrop-<version>-win64.msi

The installer drops the frozen app in Program Files and adds a Start-menu
shortcut. User gifts and settings live under %APPDATA%/GiftDrop (see gifts.py /
config.py), so the read-only install location is fine.
"""

import sys

from cx_Freeze import Executable, setup

VERSION = "1.2.0"

build_exe_options = {
    "packages": [
        "cv2", "numpy", "PIL",
        "win32api", "win32gui", "win32con", "win32process", "win32ui",
        "pyautogui",
    ],
    "include_files": [("assets/", "assets/")],
    "excludes": [
        "tkinter.test", "test", "unittest",
        "PyQt5", "PyQt6", "PySide2", "PySide6",
        "scipy", "pandas", "matplotlib", "IPython", "notebook",
    ],
    "optimize": 1,
}

bdist_msi_options = {
    # Fixed GUID so future versions upgrade in place instead of installing twice.
    "upgrade_code": "{7F3A9C2E-4B1D-4E8A-9C6F-1A2B3C4D5E60}",
    "add_to_path": False,
    "initial_target_dir": r"[ProgramFiles64Folder]\GiftDrop",
    "install_icon": "assets/app.ico",
    "summary_data": {
        "author": "jason2071",
        "comments": "TikTok gift-send macro",
    },
}

base = "Win32GUI" if sys.platform == "win32" else None

setup(
    name="GiftDrop",
    version=VERSION,
    description="TikTok gift-send macro",
    options={"build_exe": build_exe_options, "bdist_msi": bdist_msi_options},
    executables=[
        Executable(
            "main.py",
            base=base,
            target_name="GiftDrop.exe",
            icon="assets/app.ico",
            shortcut_name="GiftDrop",
            shortcut_dir="ProgramMenuFolder",
        )
    ],
)
