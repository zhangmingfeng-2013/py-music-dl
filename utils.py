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


# ---- 音质等级（筛选）----

# tier: standard=标准 / hq=高清 / lossless=无损 / unknown=未知
TIER_STANDARD = "standard"
TIER_HQ = "hq"
TIER_LOSSLESS = "lossless"
TIER_UNKNOWN = "unknown"

TIER_ORDER: dict[str, int] = {
    TIER_STANDARD: 1, TIER_HQ: 2, TIER_LOSSLESS: 3, TIER_UNKNOWN: 0,
}
TIER_LABELS: dict[str, str] = {
    TIER_STANDARD: "标准", TIER_HQ: "高清",
    TIER_LOSSLESS: "无损", TIER_UNKNOWN: "未知",
}


def quality_tier(quality: str = "", url: str = "") -> str:
    """把音质标签/URL 归一化为 standard/hq/lossless/unknown 四档。

    无损：flac/ape/wav 等无损封装
    高清：320K mp3、明确的高码率链接
    标准：其他可识别音频（128K、m4a/aac 等）
    未知：尚无音频链接或无法判断
    """
    ext = ""
    if url:
        ext = ext_from_url(url)
        if ext in _LOSSLESS_EXTS:
            return TIER_LOSSLESS
    q = (quality or "").strip().upper()
    if q in ("LOSSLESS", "FLAC", "APE", "WAV", "SQ", "HIRES", "HI-RES"):
        return TIER_LOSSLESS
    if q in ("320K", "HQ", "320", "320KBPS"):
        return TIER_HQ
    # 纯码率标签（128K/192KBPS 等）按码率判定
    import re as _re
    if q:
        m_label = _re.fullmatch(r"(\d{2,3})\s*(?:k|kbps)?", q, _re.IGNORECASE)
        if m_label:
            kbps = int(m_label.group(1))
            if kbps >= 320:
                return TIER_HQ
            if kbps >= 96:
                return TIER_STANDARD
    # 链接中带明确码率参数时按码率判定
    m = _re.search(r"[?&/](?:br|bitrate|bk)=?(\d{2,3})(?:k)?(?:bps)?(?:&|$|/)",
                   (url or "").lower())
    if m:
        kbps = int(m.group(1))
        if kbps >= 320:
            return TIER_HQ
        if kbps >= 96:
            return TIER_STANDARD
    if ext in ("mp3", "m4a", "ogg", "aac", "wma"):
        return TIER_STANDARD
    return TIER_UNKNOWN


# ---- 速度格式化 ----

def format_speed(bps: float) -> str:
    """字节/秒 → 可读速度"""
    if not bps or bps <= 0:
        return "--"
    if bps >= 1024 * 1024:
        return f"{bps / (1024 * 1024):.1f} MB/s"
    return f"{bps / 1024:.0f} KB/s"
