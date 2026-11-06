#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""本地音频指纹识歌（Shazam 协议，shazamio 开源实现）。

流程
    1. ffmpeg 统一截取前 15 秒并转 16kHz mono WAV（覆盖 MP3/WAV/FLAC/M4A…）；
    2. asyncio 端到端硬超时（默认 3 秒）；
    3. shazamio 返回的 track 节点解析为统一元数据结构。

超时 / 无匹配 / 网络异常 / 缺少依赖一律返回 ``None``，不向调用方抛异常。
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
from typing import Any, Optional

from ffmpeg import FFMPEG_BIN, extract_pcm_wav, ffmpeg_available, remove_temp_file
from utils import log

__all__ = [
    "FFMPEG_BIN", "SUPPORTED_EXT", "recognize_available", "recognize_file",
]

SUPPORTED_EXT: set[str] = {
    ".mp3", ".wav", ".flac", ".m4a",
    ".aac", ".ogg", ".wma", ".opus",
}

_SAMPLE_SECONDS = 15          # Shazam 签名只需数秒样本，15s 兼顾命中率
_DEFAULT_TIMEOUT = 3.0        # 端到端硬超时（转码 + 指纹 + 请求）


def recognize_available() -> bool:
    """识歌功能是否可用（shazamio 已安装且 ffmpeg 可用）。"""
    return (
        importlib.util.find_spec("shazamio") is not None
        and ffmpeg_available()
    )


def _to_sample_wav(src: str) -> Optional[str]:
    """截取前 15 秒转 16kHz mono WAV，返回临时文件路径；失败返回 ``None``。"""
    return extract_pcm_wav(
        src, duration=_SAMPLE_SECONDS, sample_rate=16000, channels=1, timeout=30
    )


def _metadata_items(track: dict[str, Any]) -> list[dict[str, Any]]:
    """收集 ``sections[].metadata[]`` 中所有合法的键值项。"""
    sections = track.get("sections")
    if not isinstance(sections, list):
        return []
    items: list[dict[str, Any]] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        metadata = section.get("metadata")
        if not isinstance(metadata, list):
            continue
        items.extend(item for item in metadata if isinstance(item, dict))
    return items


def _parse_shazam_track(track: dict[str, Any]) -> dict[str, str]:
    """把 shazamio 的 track 节点解析为统一元数据结构（纯函数）。"""
    meta: dict[str, str] = {
        "title": "", "artist": "", "album": "",
        "cover_url": "", "genre": "", "year": "",
    }
    if not isinstance(track, dict):
        return meta

    meta["title"] = str(track.get("title") or "").strip()
    meta["artist"] = str(track.get("subtitle") or "").strip()
    images = track.get("images")
    if isinstance(images, dict):
        meta["cover_url"] = str(images.get("coverart") or "").strip()
    genres = track.get("genres")
    if isinstance(genres, dict):
        meta["genre"] = str(genres.get("primary") or "").strip()

    for item in _metadata_items(track):
        title = str(item.get("title") or "").lower()
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        if title == "album" and not meta["album"]:
            meta["album"] = text
        elif title == "released" and not meta["year"]:
            meta["year"] = text[:4] if text[:4].isdigit() else text
    return meta


async def _recognize_async(wav_path: str) -> Optional[dict[str, Any]]:
    """调用 shazamio 识别，返回原始 track 节点。"""
    from shazamio import Shazam  # 延迟导入：未安装识歌依赖时不影响主程序启动

    shazam = Shazam()
    # shazamio >= 0.5 推荐 recognize；旧版本回退 recognize_song
    recognize_fn = getattr(shazam, "recognize", None) or shazam.recognize_song
    result = await recognize_fn(wav_path)
    if not isinstance(result, dict):
        return None
    track = result.get("track")
    if not isinstance(track, dict) or not track.get("title"):
        return None
    return track


def recognize_file(path: str, *,
                   timeout_s: float = _DEFAULT_TIMEOUT) -> Optional[dict[str, str]]:
    """识别本地音频文件。

    Args:
        path: 音频路径。
        timeout_s: 端到端超时（秒）。

    Returns:
        ``{title, artist, album, cover_url, genre, year}``；失败返回 ``None``。
    """
    if not path or not os.path.isfile(path):
        return None
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED_EXT:
        log.info("不支持的识歌格式: %s", ext)
        return None
    if not recognize_available():
        log.warning("shazamio 或 ffmpeg 不可用，无法识歌")
        return None

    wav = _to_sample_wav(path)
    if wav is None:
        log.warning("识歌预处理失败（ffmpeg 转码）: %s", os.path.basename(path))
        return None
    try:
        timeout = float(timeout_s)
    except (TypeError, ValueError):
        timeout = _DEFAULT_TIMEOUT
    try:
        track = asyncio.run(
            asyncio.wait_for(_recognize_async(wav), max(0.0, timeout))
        )
        if track is None:
            return None
        return _parse_shazam_track(track)
    except asyncio.TimeoutError:
        log.info("识歌超时（>%ss）: %s", timeout_s, os.path.basename(path))
        return None
    except Exception as exc:  # noqa: BLE001  识歌失败不得影响主流程
        log.warning("识歌失败 (%s): %s", os.path.basename(path), exc)
        return None
    finally:
        remove_temp_file(wav)
