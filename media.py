#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
音频后处理模块
- ffmpeg 转码：flac ↔ mp3（可选码率）
- 元数据写入（mutagen）：标题/歌手/专辑/年份/专辑封面/内嵌歌词
  · mp3 写 ID3v2.4 标签（APIC 封面 / USLT 歌词）
  · flac 写 Vorbis Comment + PICTURE 块
- lrc 歌词文件落盘

设计原则：后处理是“锦上添花”环节，任何失败（缺 ffmpeg、标签库异常、
封面下载失败等）只记录日志并返回结果，绝不向下载主流程抛异常。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Optional

import requests
import urllib3

from utils import log, resource_path

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---- 常量 ----

def _resolve_ffmpeg() -> str:
    """定位 ffmpeg：优先随安装包内置，其次系统 PATH。"""
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    # PyInstaller --add-binary 的几种常见落点
    candidates = (
        resource_path("ffmpeg", "bin", exe),
        resource_path("bin", exe),
        resource_path("ffmpeg", exe),
        resource_path(exe),
    )
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return shutil.which("ffmpeg") or "ffmpeg"


FFMPEG_BIN: str = _resolve_ffmpeg()
FFPROBE_BIN: str = shutil.which("ffprobe") or "ffprobe"

CONVERT_OFF = "off"
CONVERT_MP3 = "mp3"
CONVERT_FLAC = "flac"
CONVERT_MODES = (CONVERT_OFF, CONVERT_MP3, CONVERT_FLAC)
MP3_BITRATES = (128, 192, 320)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    )
}


def ffmpeg_available() -> bool:
    """检测系统是否安装 ffmpeg。"""
    try:
        r = subprocess.run(
            [FFMPEG_BIN, "-version"],
            capture_output=True, timeout=5, check=False,
        )
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@dataclass
class PostOptions:
    """下载后处理开关（由设置界面持久化）。"""

    convert: str = CONVERT_OFF          # off / mp3 / flac
    mp3_bitrate: int = 320              # 转 mp3 码率（kbps）
    write_tags: bool = True             # 写入文本元数据
    embed_cover: bool = True            # 内嵌专辑封面
    save_lrc: bool = True               # 保存同名 .lrc 文件
    embed_lyrics: bool = True           # 歌词写入音频标签

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "PostOptions":
        bitrate = int(cfg.get("mp3_bitrate", 320) or 320)
        if bitrate not in MP3_BITRATES:
            bitrate = 320
        convert = str(cfg.get("convert_mode", CONVERT_OFF) or CONVERT_OFF)
        if convert not in CONVERT_MODES:
            convert = CONVERT_OFF
        return cls(
            convert=convert,
            mp3_bitrate=bitrate,
            write_tags=bool(cfg.get("write_tags", True)),
            embed_cover=bool(cfg.get("embed_cover", True)),
            save_lrc=bool(cfg.get("save_lrc", True)),
            embed_lyrics=bool(cfg.get("embed_lyrics", True)),
        )


# ---- 转码 ----


def transcode(src: str, target_ext: str, mp3_bitrate: int = 320) -> Optional[str]:
    """把 src 转码为同目录下 target_ext 格式，成功返回新文件路径，失败返回 None。

    mp3  → libmp3lame，码率由 mp3_bitrate 决定
    flac → 原生 flac 无损编码
    """
    target_ext = target_ext.lower().lstrip(".")
    if target_ext not in ("mp3", "flac"):
        return None
    base, _ext = os.path.splitext(src)
    dst = f"{base}.{target_ext}"
    if os.path.abspath(dst) == os.path.abspath(src):
        return src
    cmd = [FFMPEG_BIN, "-y", "-nostdin", "-loglevel", "error", "-i", src]
    if target_ext == "mp3":
        cmd += ["-c:a", "libmp3lame", "-b:a", f"{int(mp3_bitrate)}k"]
    else:
        cmd += ["-c:a", "flac"]
    cmd.append(dst)
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=600, check=False)
        if r.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst) == 0:
            log.warning("ffmpeg 转码失败: %s",
                        r.stderr.decode("utf-8", "ignore")[:200])
            if os.path.exists(dst):
                try:
                    os.remove(dst)
                except OSError:
                    pass
            return None
        return dst
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("ffmpeg 调用失败: %s", e)
        return None


# ---- 封面 ----


def download_cover(url: str, timeout: int = 15) -> Optional[tuple[bytes, str]]:
    """下载封面图片，返回 (字节, mime)；失败返回 None。"""
    if not url:
        return None
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout, verify=False)
        resp.raise_for_status()
        data = resp.content
        if not data or len(data) < 64:
            return None
        mime = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if mime not in ("image/jpeg", "image/png", "image/webp"):
            # 按文件头兜底判断
            if data[:3] == b"\xff\xd8\xff":
                mime = "image/jpeg"
            elif data[:8] == b"\x89PNG\r\n\x1a\n":
                mime = "image/png"
            elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
                mime = "image/webp"
            else:
                return None
        return data, mime
    except requests.RequestException as e:
        log.info("封面下载失败: %s", e)
        return None


# ---- 标签写入 ----


def _write_mp3_tags(path: str, meta: dict[str, Any],
                    cover: Optional[tuple[bytes, str]], lyrics: str) -> None:
    from mutagen.id3 import (
        ID3, ID3NoHeaderError, APIC, TALB, TDRC, TIT2, TPE1, USLT,
    )
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    if meta.get("title"):
        tags.add(TIT2(encoding=3, text=[meta["title"]]))
    if meta.get("artist"):
        tags.add(TPE1(encoding=3, text=[meta["artist"]]))
    if meta.get("album"):
        tags.add(TALB(encoding=3, text=[meta["album"]]))
    if meta.get("year"):
        tags.add(TDRC(encoding=3, text=[str(meta["year"])]))
    if lyrics:
        tags.add(USLT(encoding=3, lang="chi", desc="Lyrics", text=lyrics))
    if cover:
        data, mime = cover
        tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))
    tags.save(path, v2_version=3)


def _write_flac_tags(path: str, meta: dict[str, Any],
                     cover: Optional[tuple[bytes, str]], lyrics: str) -> None:
    from mutagen.flac import FLAC, Picture
    audio = FLAC(path)
    if meta.get("title"):
        audio["title"] = meta["title"]
    if meta.get("artist"):
        audio["artist"] = meta["artist"]
    if meta.get("album"):
        audio["album"] = meta["album"]
    if meta.get("year"):
        audio["date"] = str(meta["year"])
    if lyrics:
        audio["lyrics"] = lyrics
    if cover:
        data, mime = cover
        # 避免重复内嵌封面：先清空已有图
        audio.clear_pictures()
        pic = Picture()
        pic.type = 3
        pic.mime = mime
        pic.desc = "Cover"
        pic.data = data
        audio.add_picture(pic)
    audio.save()


def write_tags(path: str, meta: dict[str, Any], *,
               cover: Optional[tuple[bytes, str]] = None,
               lyrics: str = "") -> bool:
    """把元数据写入音频文件；支持 .mp3 / .flac，其余格式跳过。"""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".mp3":
            _write_mp3_tags(path, meta, cover, lyrics)
        elif ext == ".flac":
            _write_flac_tags(path, meta, cover, lyrics)
        else:
            log.info("暂不支持写标签的格式: %s", ext)
            return False
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("标签写入失败 (%s): %s", os.path.basename(path), e)
        return False


def save_lrc_file(audio_path: str, lrc_text: str) -> Optional[str]:
    """在音频旁保存同名 .lrc 文件。"""
    if not lrc_text:
        return None
    lrc_path = os.path.splitext(audio_path)[0] + ".lrc"
    try:
        with open(lrc_path, "w", encoding="utf-8") as f:
            f.write(lrc_text)
        return lrc_path
    except OSError as e:
        log.warning("歌词文件保存失败: %s", e)
        return None


# ---- 下载后处理总管线 ----


def post_process(task: Any, options: PostOptions,
                 lyrics_fetcher: Optional[Callable[[dict], Optional[str]]] = None,
                 notify: Optional[Callable[[Any], None]] = None) -> dict[str, Any]:
    """下载完成后的统一管线：转码 → 歌词 → 标签。

    task: DownloadTask（鸭子类型，需含 filepath/artist/title/meta/remark）
    返回各环节结果字典；任何异常均在内部消化。
    """
    result: dict[str, Any] = {
        "converted": False, "tagged": False, "cover_ok": False,
        "lrc_saved": False, "lyrics_embedded": False,
    }
    final_path = task.filepath
    meta = dict(getattr(task, "meta", None) or {})
    meta.setdefault("title", task.title)
    meta.setdefault("artist", task.artist)

    def _remark(text: str) -> None:
        try:
            task.remark = text
            if notify is not None:
                notify(task)
        except Exception:  # noqa: BLE001
            pass

    # 1) 转码
    src_ext = os.path.splitext(final_path)[1].lower().lstrip(".")
    if options.convert in (CONVERT_MP3, CONVERT_FLAC) and options.convert != src_ext:
        if not ffmpeg_available():
            log.warning("未安装 ffmpeg，跳过转码: %s", task.display_name)
        else:
            _remark(f"转码为 {options.convert.upper()}…")
            dst = transcode(final_path, options.convert, options.mp3_bitrate)
            if dst and os.path.abspath(dst) != os.path.abspath(final_path):
                try:
                    os.remove(final_path)  # 转码成功后删除源文件，避免重复
                except OSError:
                    pass
                final_path = dst
                task.filepath = dst
                result["converted"] = True
                log.info("转码完成: %s", os.path.basename(dst))

    # 2) 歌词（lrc 文件 + 内嵌）
    lrc_text = str(meta.get("lyrics", "") or "")
    need_lyrics = options.save_lrc or (
        options.embed_lyrics and options.write_tags
    )
    if need_lyrics and not lrc_text and lyrics_fetcher is not None:
        _remark("获取歌词…")
        try:
            lrc_text = lyrics_fetcher(meta) or ""
        except Exception:  # noqa: BLE001
            lrc_text = ""

    if lrc_text:
        if options.save_lrc:
            lrc_path = save_lrc_file(final_path, lrc_text)
            result["lrc_saved"] = bool(lrc_path)
    else:
        log.info("未找到歌词: %s", task.display_name)

    # 3) 元数据标签
    if options.write_tags:
        _remark("写入元数据…")
        cover = None
        if options.embed_cover and meta.get("cover_url"):
            cover = download_cover(str(meta["cover_url"]))
        result["cover_ok"] = cover is not None
        lyrics_for_tag = lrc_text if options.embed_lyrics else ""
        result["lyrics_embedded"] = bool(lyrics_for_tag)
        result["tagged"] = write_tags(
            final_path, meta, cover=cover, lyrics=lyrics_for_tag
        )

    task.remark = ""
    return result
