#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""通用工具函数与运行环境探测。

本模块只依赖标准库，作为全项目的底层工具层：

* 运行环境：资源目录 / 用户配置目录 / 是否 PyInstaller 冻结运行
* 文件名安全化与下载目录准备
* 容量、时长、速度、文本进度条格式化
* 音频扩展名与音质档位归一化
* JSON 读写（原子写入，供配置与历史记录模块复用）
* 统一日志器
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: 源码运行时的默认下载目录（相对项目根目录）
DEFAULT_DOWNLOAD_DIR: Final = "downloaded_music"

#: 统一 User-Agent，避免各 HTTP 模块重复维护
USER_AGENT: Final = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)

_LOG_FORMAT: Final = "%(asctime)s [%(levelname)s] %(message)s"
_LOG_DATE_FORMAT: Final = "%H:%M:%S"


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------


def setup_logger(name: str = "musicdl", level: int = logging.INFO) -> logging.Logger:
    """返回带 stderr 输出的项目 logger（重复调用不会重复添加 handler）。"""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FORMAT))
        logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = False
    return logger


log = setup_logger()


# ---------------------------------------------------------------------------
# 运行环境与路径
# ---------------------------------------------------------------------------


def is_frozen() -> bool:
    """是否运行于 PyInstaller 打包后的环境。"""
    return bool(getattr(sys, "frozen", False))


def app_base_dir() -> str:
    """程序只读资源根目录。

    * 源码运行：项目根目录（本文件所在目录）
    * PyInstaller：``sys._MEIPASS``（onefile 解压目录 / onedir 资源目录）
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return str(meipass)
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(*parts: str) -> str:
    """拼接随程序分发的只读资源路径（assets/、图标等）。"""
    return os.path.join(app_base_dir(), *parts)


def user_config_dir() -> str:
    """各平台标准的用户可写配置目录（打包后使用）。

    * Windows：``%APPDATA%/shiyin``
    * macOS：``~/Library/Application Support/shiyin``
    * Linux：``$XDG_CONFIG_HOME/shiyin`` 或 ``~/.config/shiyin``
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    directory = os.path.join(base, "shiyin")
    os.makedirs(directory, exist_ok=True)
    return directory


def user_config_path(filename: str) -> str:
    """用户可写配置文件路径。

    打包后写入系统标准配置目录；源码运行保持当前目录，便于开发调试。
    """
    if is_frozen():
        return os.path.join(user_config_dir(), filename)
    return filename


def default_download_dir() -> str:
    """默认下载目录。

    打包后固定到用户 ``下载/shiyin``，避免安装目录只读；源码运行使用相对目录。
    """
    if is_frozen():
        return os.path.join(os.path.expanduser("~"), "Downloads", "shiyin")
    return DEFAULT_DOWNLOAD_DIR


def ensure_download_dir(directory: str = DEFAULT_DOWNLOAD_DIR) -> str:
    """确保下载目录存在，返回其绝对路径。"""
    path = Path(directory).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


# ---------------------------------------------------------------------------
# 文件名安全化
# ---------------------------------------------------------------------------

# Windows / POSIX 均不允许的字符，外加 C0 控制字符与 DEL
_ILLEGAL_FILENAME_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')


def safe_filename(text: Any) -> str:
    """清理文件名中的系统保留字符与控制字符，并去除首尾空白。

    非字符串输入按空串处理，保证该函数可以安全用于任意上游元数据。
    """
    if text is None:
        return ""
    cleaned = _ILLEGAL_FILENAME_RE.sub("", str(text))
    return cleaned.strip()


# ---------------------------------------------------------------------------
# 格式化
# ---------------------------------------------------------------------------


def format_duration(seconds: float) -> str:
    """秒数 → ``mm:ss``；非法值返回 ``--:--``。"""
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return "--:--"
    if not math.isfinite(value) or value <= 0:
        return "--:--"
    minutes, secs = divmod(int(value), 60)
    return f"{minutes}:{secs:02d}"


def format_size(size_bytes: int) -> str:
    """字节数 → 可读大小；非正值返回 ``未知``。"""
    try:
        value = int(size_bytes)
    except (TypeError, ValueError):
        return "未知"
    if value <= 0:
        return "未知"
    megabytes = value / (1024 * 1024)
    if megabytes >= 1:
        return f"{megabytes:.2f} MB"
    return f"{value / 1024:.1f} KB"


def format_speed(bps: float) -> str:
    """字节/秒 → 可读速度；非正值返回 ``--``。"""
    try:
        value = float(bps)
    except (TypeError, ValueError):
        return "--"
    if not math.isfinite(value) or value <= 0:
        return "--"
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):.1f} MB/s"
    return f"{value / 1024:.0f} KB/s"


def format_progress_bar(downloaded: int, total: int, bar_width: int = 40) -> str:
    """返回单行文本进度条；``total <= 0`` 时退化为已下载量提示。"""
    total = max(0, int(total or 0))
    downloaded = max(0, int(downloaded or 0))
    if total <= 0:
        return f"已下载: {format_size(downloaded)}"
    ratio = min(1.0, downloaded / total)
    filled = int(bar_width * ratio)
    bar_text = "█" * filled + "░" * (bar_width - filled)
    return f"[{bar_text}] {ratio * 100:.1f}%"


# ---------------------------------------------------------------------------
# 音频扩展名 / 音质
# ---------------------------------------------------------------------------

_LOSSLESS_EXTS: Final = frozenset({"flac", "wav", "ape"})
_VALID_EXTS: Final = frozenset({"mp3", "flac", "wav", "ape", "m4a", "ogg"})
_LOSSY_EXTS: Final = frozenset({"mp3", "m4a", "ogg", "aac", "wma"})


def ext_from_url(url: str) -> str:
    """从 URL 路径提取小写扩展名，无法识别时回退 ``mp3``。"""
    if not url:
        return "mp3"
    path = str(url).split("?", 1)[0].split("#", 1)[0]
    filename = path.rsplit("/", 1)[-1]
    if "." not in filename:
        return "mp3"
    ext = filename.rsplit(".", 1)[-1].lower()
    return ext if ext in _VALID_EXTS else "mp3"


def quality_from_ext(ext: str) -> str:
    """按扩展名推断音质标签（仅用于展示）。"""
    normalized = str(ext or "").lower().lstrip(".")
    return "LOSSLESS" if normalized in _LOSSLESS_EXTS else "320K"


def quality_from_url(url: str) -> str:
    """直接从 URL 推断音质标签。"""
    return quality_from_ext(ext_from_url(url))


# 音质档位：standard=标准 / hq=高清 / lossless=无损 / unknown=未知
TIER_STANDARD: Final = "standard"
TIER_HQ: Final = "hq"
TIER_LOSSLESS: Final = "lossless"
TIER_UNKNOWN: Final = "unknown"

TIER_ORDER: dict[str, int] = {
    TIER_STANDARD: 1,
    TIER_HQ: 2,
    TIER_LOSSLESS: 3,
    TIER_UNKNOWN: 0,
}
TIER_LABELS: dict[str, str] = {
    TIER_STANDARD: "标准",
    TIER_HQ: "高清",
    TIER_LOSSLESS: "无损",
    TIER_UNKNOWN: "未知",
}

_LOSSLESS_LABELS: Final = frozenset(
    {"LOSSLESS", "FLAC", "APE", "WAV", "SQ", "HIRES", "HI-RES"}
)
_HQ_LABELS: Final = frozenset({"320K", "HQ", "320", "320KBPS"})
_KBPS_LABEL_RE: Final = re.compile(r"(\d{2,3})\s*(?:k|kbps)?", re.IGNORECASE)
_KBPS_URL_RE: Final = re.compile(
    r"[?&/](?:br|bitrate|bk)=?(\d{2,3})(?:k)?(?:bps)?(?:&|$|/)"
)


def _tier_from_kbps(kbps: int) -> str:
    """按码率映射档位；低于 96kbps 视为未知（与历史行为一致）。"""
    if kbps >= 320:
        return TIER_HQ
    if kbps >= 96:
        return TIER_STANDARD
    return TIER_UNKNOWN


def quality_tier(quality: str = "", url: str = "") -> str:
    """把音质标签或下载链接归一化为四档。

    判定优先级：URL 中的无损扩展名 > 标签文本 > 标签/URL 中的码率 >
    有损扩展名 > 未知。该顺序保证「标签写 320K 但链接是 .flac」时按
    真实容器判定，避免筛选结果与实际文件不符。
    """
    ext = ext_from_url(url) if url else ""
    if ext in _LOSSLESS_EXTS:
        return TIER_LOSSLESS

    label = str(quality or "").strip().upper()
    if label in _LOSSLESS_LABELS:
        return TIER_LOSSLESS
    if label in _HQ_LABELS:
        return TIER_HQ

    # 纯码率标签（128K / 192KBPS …）按码率判定
    label_match = _KBPS_LABEL_RE.fullmatch(label)
    if label_match:
        tier = _tier_from_kbps(int(label_match.group(1)))
        if tier != TIER_UNKNOWN:
            return tier

    # 链接中带明确码率参数（?br=320 / /bitrate=128 …）时按码率判定
    if url:
        url_match = _KBPS_URL_RE.search(str(url).lower())
        if url_match:
            tier = _tier_from_kbps(int(url_match.group(1)))
            if tier != TIER_UNKNOWN:
                return tier

    if ext in _LOSSY_EXTS:
        return TIER_STANDARD
    return TIER_UNKNOWN


# ---------------------------------------------------------------------------
# JSON 读写（配置 / 历史记录共用）
# ---------------------------------------------------------------------------


def load_json(path: str, default: Any) -> Any:
    """读取 JSON 文件；文件缺失、损坏或类型不符时返回 ``default`` 的浅拷贝。"""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError, TypeError):
        if isinstance(default, (dict, list)):
            return default.copy()
        return default


def save_json_atomic(path: str, payload: Any, *, indent: int = 2) -> bool:
    """原子写入 JSON（同目录临时文件 + ``os.replace``），失败返回 ``False``。

    原子替换可避免进程崩溃或断电时留下半截 JSON，导致下次启动配置丢失。
    """
    directory = os.path.dirname(os.path.abspath(path)) or "."
    tmp_path = ""
    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=".tmp-", suffix=".json", dir=directory
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=indent)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        return True
    except (OSError, TypeError, ValueError):
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False
