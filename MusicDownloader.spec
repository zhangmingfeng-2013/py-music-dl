# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.building.build_main import Analysis
from PyInstaller.building.datastruct import Tree, Target
from PyInstaller.building import api
from PyInstaller.utils.hooks import collect_all, collect_submodules
from PyInstaller.config import CONF

block_cipher = None

datas = []
binaries = []
hiddenimports = [
    'tkinter',
    'tkinter.ttk', 
    'tkinter.scrolledtext',
    'requests',
    'urllib3',
    'bs4',
    'lxml',
    'lxml.etree',
    'lxml.html',
]

a = Analysis(
    ['music_gui.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'numpy', 'scipy', 'pandas', 'PyQt5', 'PySide2'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MusicDownloader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MusicDownloader',
)
