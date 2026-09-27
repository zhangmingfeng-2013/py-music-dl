#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
共享工具模块 — 文件名清理、格式化、进度条、日志配置
"""

import os
import re
import sys
import logging
from typing import Optional
from pathlib import Path

# ---- 日志 ----

def setup_logger(name: str = "musicdl", level: int = logging.INFO) -> logging.Logger:
    """创建标准 logger,同时输出到 stderr"""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
        ))
        logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = False
    return logger


log = setup_logger()

# ---- 常量 ----

DEFAULT_DOWNLOAD_DIR = "downloaded_music"

# ---- 文件名校验 ----

_ILLEGAL_CHARS_RE = re.compile(r'[\\/*?:"<>|]')


def safe_filename(text: str) -> str:
    """清理文件名中的非法字符"""
    return _ILLEGAL_CHARS_RE.sub("", text).strip()


def ensure_download_dir(directory: str = DEFAULT_DOWNLOAD_DIR) -> str:
    """确保下载目录存在,返回绝对路径"""
    path = Path(directory).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return str(path)

# ---- 格式化 ----


def format_duration(seconds: float) -> str:
    """秒数 → mm:ss"""
    if not seconds or seconds <= 0:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def format_size(size_bytes: int) -> str:
    """字节 → 可读大小"""
    if not size_bytes or size_bytes <= 0:
        return "未知"
    mb = size_bytes / (1024 * 1024)
    if mb >= 1:
        return f"{mb:.2f} MB"
    return f"{size_bytes / 1024:.1f} KB"


def format_progress_bar(downloaded: int, total: int, bar_width: int = 40) -> str:
    """返回文本进度条字符串（单行,不带换行前缀）"""
    if total <= 0:
        return f"已下载: {format_size(downloaded)}"
    percent = downloaded / total * 100
    filled = int(bar_width * downloaded / total)
    bar = "█" * filled + "░" * (bar_width - filled)
    return f"[{bar}] {percent:.1f}%"

# ---- 文件扩展名推断 ----


_LOSSLESS_EXTS = frozenset({"flac", "wav", "ape"})
_VALID_EXTS = frozenset({"mp3", "flac", "wav", "ape", "m4a", "ogg"})


def ext_from_url(url: str) -> str:
    """从 URL 提取文件扩展名（小写）,无法识别返回 mp3"""
    try:
        path = url.split("?")[0]
        ext = path.rsplit(".", 1)[-1].lower()
        return ext if ext in _VALID_EXTS else "mp3"
    except (IndexError, ValueError):
        return "mp3"


def quality_from_ext(ext: str) -> str:
    """根据扩展名推断音质标签"""
    return "LOSSLESS" if ext in _LOSSLESS_EXTS else "320K"


def quality_from_url(url: str) -> str:
    """直接从 URL 推断音质"""
    return quality_from_ext(ext_from_url(url))
