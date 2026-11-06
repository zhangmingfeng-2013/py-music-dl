#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""音频后处理：ffmpeg 转码、标签写入、封面与 LRC 歌词落盘。

处理链路
    下载完成 → 可选转码（MP3 / FLAC）→ 获取歌词（API / Whisper 兜底）
    → 保存同名 ``.lrc`` → 写入标题/歌手/专辑/年份/封面/歌词标签

设计原则
    后处理是「锦上添花」环节：缺少 ffmpeg、标签库异常、封面下载失败等
    任何问题都只记录日志并返回已有结果，绝不向下载主流程抛异常。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Final, Optional

import requests
import urllib3

from ffmpeg import (
    FFMPEG_BIN,
    FFPROBE_BIN,
    ffmpeg_available,
    matches_host_platform,
    output_is_valid,
    remove_file_quietly,
    resolve_tool,
    run_ffmpeg,
)
from utils import USER_AGENT, log

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

__all__ = [
    "CONVERT_FLAC", "CONVERT_MODES", "CONVERT_MP3", "CONVERT_OFF",
    "FFMPEG_BIN", "FFPROBE_BIN", "MP3_BITRATES", "PostOptions",
    "download_cover", "ffmpeg_available", "post_process", "save_lrc_file",
    "transcode", "write_tags",
]

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

CONVERT_OFF: Final = "off"
CONVERT_MP3: Final = "mp3"
CONVERT_FLAC: Final = "flac"
CONVERT_MODES: Final = (CONVERT_OFF, CONVERT_MP3, CONVERT_FLAC)
MP3_BITRATES: Final = (128, 192, 320)

#: 封面大小上限（8 MiB），防止异常上游返回超大响应耗尽内存
MAX_COVER_BYTES: Final = 8 * 1024 * 1024

_HEADERS: Final = {"User-Agent": USER_AGENT}


# ---- 兼容旧接口：这些函数已迁移至 ffmpeg.py --------------------------------


def _matches_host_platform(path: str) -> bool:
    """兼容别名，见 :func:`ffmpeg.matches_host_platform`。"""
    return matches_host_platform(path)


def _resolve_tool(name: str) -> str:
    """兼容别名，见 :func:`ffmpeg.resolve_tool`。"""
    return resolve_tool(name)


@dataclass
class PostOptions:
    """下载后处理开关（由设置界面持久化）。"""

    convert: str = CONVERT_OFF          # off / mp3 / flac
    mp3_bitrate: int = 320              # 转 mp3 码率（kbps）
    write_tags: bool = True             # 写入文本元数据
    embed_cover: bool = True            # 内嵌专辑封面
    save_lrc: bool = True               # 保存同名 .lrc 文件
    embed_lyrics: bool = True           # 歌词写入音频标签
    whisper_fallback: bool = True       # API 歌词缺失时用 Whisper 语音识别兜底

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "PostOptions":
        """从界面配置字典构造，非法值静默回退默认值。"""
        config = cfg if isinstance(cfg, dict) else {}

        try:
            bitrate = int(config.get("mp3_bitrate", 320) or 320)
        except (TypeError, ValueError):
            bitrate = 320
        if bitrate not in MP3_BITRATES:
            bitrate = 320

        convert = str(config.get("convert_mode", CONVERT_OFF) or CONVERT_OFF)
        if convert not in CONVERT_MODES:
            convert = CONVERT_OFF

        return cls(
            convert=convert,
            mp3_bitrate=bitrate,
            write_tags=bool(config.get("write_tags", True)),
            embed_cover=bool(config.get("embed_cover", True)),
            save_lrc=bool(config.get("save_lrc", True)),
            embed_lyrics=bool(config.get("embed_lyrics", True)),
            whisper_fallback=bool(config.get("whisper_fallback", True)),
        )


# ---------------------------------------------------------------------------
# 转码
# ---------------------------------------------------------------------------


def transcode(src: str, target_ext: str, mp3_bitrate: int = 320) -> Optional[str]:
    """把 ``src`` 转码为同目录下的目标格式。

    Args:
        src: 源音频路径。
        target_ext: ``"mp3"`` 或 ``"flac"``（可带点）。
        mp3_bitrate: MP3 码率（kbps），仅目标为 mp3 时生效。

    Returns:
        新文件路径；失败返回 ``None``。同路径时直接返回 ``src``。
    """
    normalized_ext = str(target_ext or "").lower().lstrip(".")
    if normalized_ext not in (CONVERT_MP3, CONVERT_FLAC):
        return None
    if not src or not os.path.isfile(src):
        log.warning("转码源文件不存在: %s", src)
        return None

    base, _ext = os.path.splitext(src)
    destination = f"{base}.{normalized_ext}"
    if os.path.abspath(destination) == os.path.abspath(src):
        return src

    try:
        bitrate = int(mp3_bitrate)
    except (TypeError, ValueError):
        bitrate = 320

    args = ["-y", "-nostdin", "-loglevel", "error", "-i", src]
    if normalized_ext == CONVERT_MP3:
        args += ["-c:a", "libmp3lame", "-b:a", f"{bitrate}k"]
    else:
        args += ["-c:a", "flac"]
    args.append(destination)

    result = run_ffmpeg(args, timeout=600)
    if not output_is_valid(result, destination):
        stderr = b"" if result is None else (result.stderr or b"")
        log.warning("ffmpeg 转码失败: %s", stderr.decode("utf-8", "ignore")[:200])
        remove_file_quietly(destination)
        return None
    return destination


# ---------------------------------------------------------------------------
# 封面
# ---------------------------------------------------------------------------


def _guess_image_mime(data: bytes, content_type: str) -> str:
    """根据响应头与文件魔数判断图片 MIME；无法识别返回空串。"""
    mime = content_type.split(";")[0].strip().lower()
    if mime in ("image/jpeg", "image/png", "image/webp"):
        return mime
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return ""


def download_cover(url: str, timeout: int = 15) -> Optional[tuple[bytes, str]]:
    """下载封面图片，返回 ``(字节, mime)``；失败或格式非法返回 ``None``。"""
    if not url:
        return None
    try:
        response = requests.get(url, headers=_HEADERS, timeout=timeout, verify=False)
        response.raise_for_status()
        if _header_exceeds(response, MAX_COVER_BYTES):
            log.info("封面超过大小上限，跳过: %s", url)
            return None
        data = response.content
        if not data or len(data) < 64 or len(data) > MAX_COVER_BYTES:
            return None
        mime = _guess_image_mime(data, response.headers.get("Content-Type", ""))
        if not mime:
            return None
        return data, mime
    except requests.RequestException as exc:
        log.info("封面下载失败: %s", exc)
        return None


def _header_exceeds(response: requests.Response, limit: int) -> bool:
    """Content-Length 是否超过上限；缺失/非法时返回 ``False``。"""
    try:
        length = int(response.headers.get("Content-Length", "0"))
    except (TypeError, ValueError):
        return False
    return length > limit


# ---------------------------------------------------------------------------
# 标签写入
# ---------------------------------------------------------------------------


def _text(meta: dict[str, Any], key: str) -> str:
    """取元数据文本值，``None`` / 空值统一为空串。"""
    value = meta.get(key)
    return str(value).strip() if value else ""


def _write_mp3_tags(path: str, meta: dict[str, Any],
                    cover: Optional[tuple[bytes, str]], lyrics: str) -> None:
    """写入 ID3v2.3 标签（APIC 封面 / USLT 歌词）。"""
    from mutagen.id3 import (
        ID3, APIC, TALB, TDRC, TIT2, TPE1, USLT, ID3NoHeaderError,
    )

    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()

    if title := _text(meta, "title"):
        tags.add(TIT2(encoding=3, text=[title]))
    if artist := _text(meta, "artist"):
        tags.add(TPE1(encoding=3, text=[artist]))
    if album := _text(meta, "album"):
        tags.add(TALB(encoding=3, text=[album]))
    if year := _text(meta, "year"):
        tags.add(TDRC(encoding=3, text=[year]))
    if lyrics:
        tags.add(USLT(encoding=3, lang="chi", desc="Lyrics", text=lyrics))
    if cover:
        data, mime = cover
        tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))
    tags.save(path, v2_version=3)


def _write_flac_tags(path: str, meta: dict[str, Any],
                     cover: Optional[tuple[bytes, str]], lyrics: str) -> None:
    """写入 FLAC Vorbis Comment 与 PICTURE 块。"""
    from mutagen.flac import FLAC, Picture

    audio = FLAC(path)
    if title := _text(meta, "title"):
        audio["title"] = title
    if artist := _text(meta, "artist"):
        audio["artist"] = artist
    if album := _text(meta, "album"):
        audio["album"] = album
    if year := _text(meta, "year"):
        audio["date"] = year
    if lyrics:
        audio["lyrics"] = lyrics
    if cover:
        data, mime = cover
        # 避免重复内嵌封面：先清空已有图片
        audio.clear_pictures()
        picture = Picture()
        picture.type = 3
        picture.mime = mime
        picture.desc = "Cover"
        picture.data = data
        audio.add_picture(picture)
    audio.save()


def write_tags(path: str, meta: dict[str, Any], *,
               cover: Optional[tuple[bytes, str]] = None,
               lyrics: str = "") -> bool:
    """把元数据写入音频文件；支持 ``.mp3`` / ``.flac``，其余格式跳过。"""
    if not isinstance(meta, dict):
        log.warning("标签写入跳过：元数据不是字典 (%s)", type(meta).__name__)
        return False
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
    except Exception as exc:  # noqa: BLE001  标签库异常不得影响下载结果
        log.warning("标签写入失败 (%s): %s", os.path.basename(path), exc)
        return False


def save_lrc_file(audio_path: str, lrc_text: str) -> Optional[str]:
    """在音频旁保存同名 ``.lrc`` 文件，返回路径；失败返回 ``None``。"""
    if not lrc_text:
        return None
    lrc_path = os.path.splitext(audio_path)[0] + ".lrc"
    try:
        with open(lrc_path, "w", encoding="utf-8") as handle:
            handle.write(lrc_text)
        return lrc_path
    except OSError as exc:
        log.warning("歌词文件保存失败: %s", exc)
        return None


# ---------------------------------------------------------------------------
# 下载后处理总管线
# ---------------------------------------------------------------------------


def _needs_lyrics(options: PostOptions) -> bool:
    """是否需要获取歌词（保存独立文件或写入标签）。"""
    return options.save_lrc or (options.embed_lyrics and options.write_tags)


def _convert_audio(task: Any, options: PostOptions, path: str,
                   result: dict[str, Any],
                   remark: Callable[[str], None]) -> str:
    """按需转码并返回最终路径；成功后删除源文件。"""
    source_ext = os.path.splitext(path)[1].lower().lstrip(".")
    if options.convert not in (CONVERT_MP3, CONVERT_FLAC):
        return path
    if options.convert == source_ext:
        return path

    if not ffmpeg_available():
        log.warning("未安装 ffmpeg，跳过转码: %s", getattr(task, "display_name", ""))
        return path

    remark(f"转码为 {options.convert.upper()}…")
    destination = transcode(path, options.convert, options.mp3_bitrate)
    if not destination or os.path.abspath(destination) == os.path.abspath(path):
        return path

    # 转码成功后删除源文件，避免同目录重复音频
    remove_file_quietly(path)
    task.filepath = destination
    result["converted"] = True
    log.info("转码完成: %s", os.path.basename(destination))
    return destination


def _acquire_lyrics(
    task: Any, options: PostOptions, meta: dict[str, Any], path: str,
    lyrics_fetcher: Optional[Callable[[dict], Optional[str]]],
    remark: Callable[[str], None],
) -> str:
    """按 API → Whisper 的顺序获取歌词文本；失败返回空串。"""
    lrc_text = str(meta.get("lyrics", "") or "")
    if not _needs_lyrics(options) or lrc_text:
        return lrc_text

    if lyrics_fetcher is not None:
        remark("获取歌词…")
        try:
            lrc_text = lyrics_fetcher(meta) or ""
        except Exception:  # noqa: BLE001  歌词获取失败不应中断后处理
            log.exception("歌词获取异常: %s", getattr(task, "display_name", ""))
            lrc_text = ""

    # API 歌词缺失时的 Whisper 语音识别兜底
    if not lrc_text and options.whisper_fallback:
        try:
            from transcribe import transcribe_to_lrc, whisper_available

            if whisper_available():
                remark("Whisper 识别歌词…")
                lrc_text = transcribe_to_lrc(
                    path,
                    meta_title=str(meta.get("title", "") or ""),
                    meta_artist=str(meta.get("artist", "") or ""),
                    progress_cb=remark,
                ) or ""
        except Exception as exc:  # noqa: BLE001  兜底失败同样不应中断
            log.warning("Whisper 歌词兜底失败 (%s): %s",
                        getattr(task, "display_name", ""), exc)
            lrc_text = ""
    return lrc_text


def _apply_tags(final_path: str, options: PostOptions, meta: dict[str, Any],
                lrc_text: str, result: dict[str, Any],
                remark: Callable[[str], None]) -> None:
    """下载封面并写入标签，回填 ``result`` 中的标记位。"""
    if not options.write_tags:
        return

    remark("写入元数据…")
    cover = None
    if options.embed_cover and meta.get("cover_url"):
        cover = download_cover(str(meta["cover_url"]))
    result["cover_ok"] = cover is not None

    lyrics_for_tag = lrc_text if options.embed_lyrics else ""
    result["lyrics_embedded"] = bool(lyrics_for_tag)
    result["tagged"] = write_tags(
        final_path, meta, cover=cover, lyrics=lyrics_for_tag
    )


def post_process(task: Any, options: PostOptions,
                 lyrics_fetcher: Optional[Callable[[dict], Optional[str]]] = None,
                 notify: Optional[Callable[[Any], None]] = None) -> dict[str, Any]:
    """下载完成后的统一管线：转码 → 歌词 → 标签。

    Args:
        task: ``DownloadTask``（鸭子类型，需含 ``filepath/artist/title/meta``
            与可写的 ``remark``）。
        options: 后处理开关。
        lyrics_fetcher: 歌词获取函数，签名 ``fetcher(meta) -> str | None``。
        notify: 状态回调，用于实时展示当前阶段。

    Returns:
        各环节结果字典：``converted`` / ``tagged`` / ``cover_ok`` /
        ``lrc_saved`` / ``lyrics_embedded``。
    """
    result: dict[str, Any] = {
        "converted": False,
        "tagged": False,
        "cover_ok": False,
        "lrc_saved": False,
        "lyrics_embedded": False,
    }

    raw_meta = getattr(task, "meta", None)
    meta = dict(raw_meta) if isinstance(raw_meta, dict) else {}
    meta.setdefault("title", getattr(task, "title", ""))
    meta.setdefault("artist", getattr(task, "artist", ""))

    def remark(text: str) -> None:
        try:
            task.remark = text
            if notify is not None:
                notify(task)
        except Exception:  # noqa: BLE001  状态提示失败不影响处理
            pass

    final_path = str(getattr(task, "filepath", "") or "")

    try:
        final_path = _convert_audio(task, options, final_path, result, remark)
        lrc_text = _acquire_lyrics(
            task, options, meta, final_path, lyrics_fetcher, remark
        )

        if lrc_text:
            if options.save_lrc:
                result["lrc_saved"] = bool(save_lrc_file(final_path, lrc_text))
        else:
            log.info("未找到歌词: %s", getattr(task, "display_name", ""))

        _apply_tags(final_path, options, meta, lrc_text, result, remark)
    finally:
        # 无论成功失败都清除阶段提示，避免任务行停留在「转码中…」
        try:
            task.remark = ""
        except Exception:  # noqa: BLE001
            pass

    return result
