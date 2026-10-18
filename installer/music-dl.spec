# -*- mode: python ; coding: utf-8 -*-
"""
音乐下载器 PyInstaller 打包规格（Windows / macOS / Linux 通用）。

用法：
    pyinstaller music-dl.spec --noconfirm

约定：
  · 入口：gui_qt.py；onedir 窗口应用
  · 资源：assets/（品牌图标、打赏码）整体打入
  · ffmpeg：若 installer/bin/ 下存在平台二进制则一并打入，
    缺失时回退系统 PATH（见 media.py _resolve_ffmpeg）
  · 版本号：installer/VERSION
"""

import os
import sys

# 项目根 = spec 所在目录（installer/）的上级；PyInstaller 执行时注入 SPECPATH
try:
    ROOT = os.path.dirname(SPECPATH)
except NameError:  # 非 PyInstaller 环境直接执行 spec 时回退 cwd
    ROOT = os.path.abspath(os.getcwd())

with open(os.path.join(ROOT, "installer", "VERSION"), encoding="utf-8") as f:
    APP_VERSION = f.read().strip()

APP_NAME = "Shiyin"                    # 内部名（英文，保证跨平台路径安全）
APP_DISPLAY_NAME = "拾音"
BUNDLE_ID = "com.shiyin.app"

# ---- 数据文件（只打入运行时需要的资源，排除矢量源/生成脚本/iconset）----
def collect_assets():
    result = []
    assets_root = os.path.join(ROOT, "assets")
    for dirpath, _dirs, files in os.walk(assets_root):
        # macOS 图标集中间产物不打入
        if os.path.basename(dirpath) == "app.iconset":
            continue
        for fn in files:
            if fn.endswith((".py", ".svg")) or fn == "icon_1024.png":
                continue
            src = os.path.join(dirpath, fn)
            dest = os.path.relpath(dirpath, ROOT)
            result.append((src, dest))
    return result


datas = collect_assets()

# ---- 二进制（可选内置 ffmpeg / ffprobe，来自 installer/bin/）----
# 静态构建仅依赖系统库，无需额外收集 dylib；运行时由 media.py 按
# resource_path("bin", ...) → PATH 的顺序定位。
# 与 media.py _matches_host_platform 同规则校验魔数：installer/bin/ 可能
# 存放为其他平台准备的二进制（如 Linux .deb 用的 ELF），不可打入本平台包。
def _matches_host_platform(path):
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
    except OSError:
        return False
    if sys.platform == "win32":
        return magic[:2] == b"MZ"
    if sys.platform == "darwin":
        return magic in (
            b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",
            b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
            b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf",
        )
    return magic == b"\x7fELF"


binaries = []
_bin_src_dir = os.path.join(ROOT, "installer", "bin")
for _tool in ("ffmpeg", "ffprobe"):
    _tool_exe = _tool + (".exe" if sys.platform == "win32" else "")
    _tool_src = os.path.join(_bin_src_dir, _tool_exe)
    if os.path.isfile(_tool_src) and _matches_host_platform(_tool_src):
        binaries.append((_tool_src, "bin"))
    elif os.path.isfile(_tool_src):
        print(f"    跳过平台不匹配的 {_tool}: {_tool_src}")

# ---- 隐式依赖（动态导入的第三方包）----
hiddenimports = [
    "lxml", "lxml.etree",
    "bs4",
    "mutagen", "mutagen.id3", "mutagen.flac", "mutagen.mp3",
    "pyglass",
]

# pyglass 可能携带资源/子模块，整体收集
from PyInstaller.utils.hooks import collect_all
for _pkg in ("pyglass",):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

a = Analysis(
    [os.path.join(ROOT, "gui_qt.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.QtWebEngineCore",
             # 构建环境若同时装了多个 Qt 绑定会触发 PyInstaller 报错
             "PyQt5", "PySide2", "PySide6"],
    noarchive=False,
)

pyz = PYZ(a.pure)

# ---- 平台可执行图标 ----
_icon = None
if sys.platform == "win32":
    _icon = os.path.join(ROOT, "assets", "icons", "app.ico")
elif sys.platform == "darwin":
    _icon = os.path.join(ROOT, "assets", "icons", "app.icns")

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,             # GUI 应用，无控制台窗口
    disable_windowed_traceback=False,
    icon=_icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)

# ---- macOS .app ----
app = BUNDLE(
    coll,
    name=APP_NAME + ".app",
    icon=_icon,
    bundle_identifier=BUNDLE_ID,
    info_plist={
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_DISPLAY_NAME,
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_VERSION,
        "NSHighResolutionCapable": True,
        "CFBundleDevelopmentRegion": "zh-Hans",
        "LSMinimumSystemVersion": "12.0",
        "NSMicrophoneUsageDescription": "应用不需要麦克风权限。",
    },
) if sys.platform == "darwin" else None
