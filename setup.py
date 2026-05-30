import sys
import os
from cx_Freeze import setup, Executable, Freezer

if sys.platform == "darwin":
    python_framework_path = "/Library/Frameworks/Python.framework/Versions/3.14"
    python_lib_path = f"{python_framework_path}/lib/python3.14"
    
    include_files = [
        (f"{python_framework_path}/Python", "MacOS/Python"),
        (python_lib_path, "lib/python3.14"),
    ]
    
    excludes = ["ClassKit", "AVKit"]
else:
    include_files = []
    excludes = []

build_exe_options = {
    "packages": ["requests", "urllib3", "bs4", "lxml"],
    "excludes": ["tkinter"] + excludes,
    "optimize": 2,
    "include_files": include_files,
}

bdist_dmg_options = {
    "volume_label": "MusicDownloader",
}

executables = [
    Executable(
        "music_gui.py",
        base="Win32GUI" if sys.platform == "win32" else None,
        target_name="MusicDownloader",
    )
]

setup(
    name="MusicDownloader",
    version="1.0",
    description="音乐下载器",
    options={
        "build_exe": build_exe_options,
        "bdist_dmg": bdist_dmg_options,
    },
    executables=executables,
)
