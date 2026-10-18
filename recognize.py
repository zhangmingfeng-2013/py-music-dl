#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
本地音频指纹识歌（Shazam 协议，shazamio 开源实现）
- 先用 ffmpeg 统一截取前 15s 转 16kHz mono WAV（覆盖 MP3/WAV/FLAC/M4A 等全格式）
- asyncio 整体 3s 硬超时，超时/无匹配/网络异常一律返回 None
- 输出统一结构：{title, artist, album, cover_url, genre, year}
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import tempfile
from typing import Any, Optional

from media import FFMPEG_BIN, ffmpeg_available
from utils import log

SUPPORTED_EXT = {
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
    """截取前 _SAMPLE_SECONDS 秒转 16kHz mono WAV，返回临时文件路径。"""
    try:
        fd, dst = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        cmd = [
            FFMPEG_BIN, "-y", "-nostdin", "-loglevel", "error",
            "-i", src,
            "-t", str(_SAMPLE_SECONDS),
            "-ar", "16000", "-ac", "1",
            "-c:a", "pcm_s16le",
            dst,
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=30, check=False)
        if r.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst) == 0:
            try:
                os.remove(dst)
            except OSError:
                pass
            return None
        return dst
    except (OSError, subprocess.SubprocessError):
        return None


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
    # sections[].metadata[] 内含 Album / Released 等键值
    sections = track.get("sections")
    if not isinstance(sections, list):
        sections = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        metadata = section.get("metadata")
        if not isinstance(metadata, list):
            continue
        for item in metadata:
            if not isinstance(item, dict):
                continue
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
    from shazamio import Shazam
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


def recognize_file(path: str, *, timeout_s: float = _DEFAULT_TIMEOUT) -> Optional[dict[str, str]]:
    """识别本地音频文件，成功返回元数据字典，失败/超时返回 None。"""
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
        track = asyncio.run(asyncio.wait_for(_recognize_async(wav), timeout_s))
        if track is None:
            return None
        return _parse_shazam_track(track)
    except asyncio.TimeoutError:
        log.info("识歌超时（>%ss）: %s", timeout_s, os.path.basename(path))
        return None
    except Exception as e:  # noqa: BLE001
        log.warning("识歌失败 (%s): %s", os.path.basename(path), e)
        return None
    finally:
        try:
            os.remove(wav)
        except OSError:
            pass
