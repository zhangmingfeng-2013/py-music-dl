# -*- mode: python ; coding: utf-8 -*-

from cx_Freeze import setup, Executable

build_exe_options = {
    "packages": ["requests", "urllib3", "bs4", "lxml"],
    "excludes": ["tkinter"],
    "optimize": 2,
}

bdist_msi_options = {
    "upgrade_code": None,
    "initial_target_dir": r"C:\Program Files\MusicDownloader",
}

executables = [
    Executable(
        "music_gui.py",
        base="Win32GUI",
        target_name="MusicDownloader.exe",
    )
]

setup(
    name="MusicDownloader",
    version="1.0",
    description="音乐下载器",
    options={
        "build_exe": build_exe_options,
        "bdist_msi": bdist_msi_options,
    },
    executables=executables,
)
