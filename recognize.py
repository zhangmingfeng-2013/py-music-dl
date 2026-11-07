#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""本地音频指纹识歌（Shazam 协议，shazamio 开源实现）。

单窗口识别有两个准确率陷阱：长前奏 / 静音段取不到有效指纹，以及
特定旋律片段命中的「唯一性误报」（把 A 歌识成 B 歌）。本模块用三个
手段同时提高命中率与正确率：

流程
    1. ffprobe 读取时长，按时长比例生成多个 12 秒采样窗口，
       避开只在歌曲开头取样的盲区；
    2. 每个窗口 ffmpeg 截取为 16kHz mono WAV，shazamio 生成指纹检索；
    3. 偏移校验：Shazam 返回的命中位置必须落在该窗口的分析区间内，
       区间外的命中是典型误报，直接丢弃；
    4. 多窗口共识：同一 track 至少两个窗口命中才算高置信；只有一个
       窗口命中时降级为低置信返回；多个 track 互相矛盾且无多数时放弃，
       宁可返回 ``None`` 也不给出错误歌名；
    5. ``language="zh-CN"`` 让 Shazam 返回中文歌手 / 简体歌名，
       避免 "Zihao Zhang" 这类罗马音元数据污染文件名与后续搜索。

超时 / 无匹配 / 网络异常 / 缺少依赖一律返回 ``None``，不向调用方抛异常。
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
from typing import Any, NamedTuple, Optional

from ffmpeg import (
    FFMPEG_BIN, extract_pcm_wav, ffmpeg_available, probe_duration,
    remove_temp_file,
)
from utils import log

__all__ = [
    "FFMPEG_BIN", "SUPPORTED_EXT", "recognize_available", "recognize_file",
]

SUPPORTED_EXT: set[str] = {
    ".mp3", ".wav", ".flac", ".m4a",
    ".aac", ".ogg", ".wma", ".opus",
}

_WINDOW_SECONDS = 12.0        # 单个采样窗口时长（Shazam 官方约 10s 即可命中）
_DEFAULT_TIMEOUT = 20.0       # 全部窗口的端到端总预算（秒）
_ATTEMPT_TIMEOUT = 8.0        # 单个窗口请求的硬超时（秒）
_OFFSET_TOLERANCE = 3.0       # 命中位置允许超出窗口末尾的容差（秒）
_OFFSET_LEAD = 0.75           # 命中位置早于窗口起点的抖动容差（seek / 估算误差）
_LANGUAGE = "zh-CN"           # 中文元数据（歌手 / 歌名不做罗马音转写）

# 采样比例：先取 0 / 35% / 65% 三个窗口（主歌 + 副歌覆盖）；
# 若三者互相矛盾再补 20% / 50% / 80% 三个窗口做仲裁。
_SAMPLE_RATIOS: tuple[float, ...] = (0.0, 0.35, 0.65, 0.2, 0.5, 0.8)
_DEDUPE_SECONDS = 2.0         # 起点相距不足 2s 的窗口视为重复

# shazamio 会按 language 本地化 sections 的元数据键名，
# 只认英文 "Album"/"Released" 会让中文结果丢失专辑与年份。
_ALBUM_LABELS = {"album", "专辑", "專輯", "アルバム", "앨범"}
_RELEASED_LABELS = {
    "released", "发行时间", "發行時間", "发行日期", "リリース", "발매일",
}


def recognize_available() -> bool:
    """识歌功能是否可用（shazamio 已安装且 ffmpeg 可用）。"""
    return (
        importlib.util.find_spec("shazamio") is not None
        and ffmpeg_available()
    )


# ---------- 纯函数：窗口规划 / 结果校验 / 共识投票 ----------

def _candidate_starts(duration: float,
                      window: float = _WINDOW_SECONDS) -> list[float]:
    """按歌曲时长生成采样窗口起点（秒）。

    - 时长未知或过短：只从头取一个窗口；
    - 其余按时长比例取样，末段窗口不越过音频结尾，重复起点只保留一个。
    """
    try:
        duration = float(duration)
    except (TypeError, ValueError):
        return [0.0]
    if duration <= 0 or duration <= window + 1.0:
        return [0.0]

    starts: list[float] = []
    max_start = max(0.0, duration - window)
    for ratio in _SAMPLE_RATIOS:
        start = round(max(0.0, min(ratio * duration, max_start)), 3)
        if all(abs(start - seen) > _DEDUPE_SECONDS for seen in starts):
            starts.append(start)
    return starts or [0.0]


def _analyzed_span(start: float, actual: float,
                   core: float) -> tuple[float, float]:
    """窗口实际被分析的时间区间 ``(起点, 时长)``。

    shazamio 的识别器在音频长于 ``core`` 时取居中片段，短于则整段使用；
    ``core < 0`` 表示旧版 ``recognize_song`` 整段分析，等价于 ``actual``。
    """
    core = actual if core < 0 else core
    if actual > core + 0.05:
        return start + (actual - core) / 2.0, core
    return start, actual


def _offset_is_plausible(offset: float, span_start: float,
                         span_duration: float,
                         tolerance: float = _OFFSET_TOLERANCE) -> bool:
    """命中偏移是否与窗口分析区间对齐。

    真命中在参考曲目中的起点必然落在窗口内（最多略早于起点，属 seek /
    偏移估算抖动）；明显早于窗口起点的命中意味着只有片段尾部重叠，
    是典型的唯一性误报。
    """
    return (
        span_start - _OFFSET_LEAD
        <= offset
        <= span_start + span_duration + tolerance
    )


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _track_vote_key(track: dict[str, Any]) -> str:
    """投票身份：优先 Shazam track key，缺失时退回「歌手|歌名」。"""
    key = track.get("key")
    if key not in (None, "", 0):
        return f"key:{key}"
    artist = str(track.get("subtitle") or "").strip().lower()
    title = str(track.get("title") or "").strip().lower()
    return f"text:{artist}|{title}"


def _pick_consensus(tracks: list[dict[str, Any]]
                    ) -> tuple[Optional[dict[str, Any]], str, int]:
    """多窗口命中投票。

    Returns:
        ``(track, confidence, votes)``。``confidence`` 为 ``high``（至少
        两窗一致）/ ``low``（仅一窗命中）/ ``""``（无结果或平票放弃）。
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for track in tracks:
        groups.setdefault(_track_vote_key(track), []).append(track)
    if not groups:
        return None, "", 0

    ranked = sorted(groups.values(), key=len, reverse=True)
    best = ranked[0]
    votes = len(best)
    if votes >= 2:
        if len(ranked) > 1 and len(ranked[1]) == votes:
            return None, "", votes      # 平票：不猜，避免误报
        return best[0], "high", votes
    if len(ranked) == 1:
        return best[0], "low", 1
    return None, "", 1                  # 多个互相矛盾的孤立命中


def _evaluate_result(result: Any, start: float, actual: float,
                     core: float) -> Optional[dict[str, Any]]:
    """校验单窗口原始响应，返回可信 track；无效返回 ``None``。"""
    if not isinstance(result, dict):
        return None
    track = result.get("track")
    if not isinstance(track, dict) or not str(track.get("title") or "").strip():
        return None
    matches = result.get("matches")
    if not isinstance(matches, list) or not matches:
        return None

    span_start, span_duration = _analyzed_span(start, actual, core)
    offsets = [
        offset for offset in (
            _as_float(match.get("offset"))
            for match in matches if isinstance(match, dict)
        ) if offset is not None
    ]
    if not any(
        _offset_is_plausible(offset, span_start, span_duration)
        for offset in offsets
    ):
        return None
    return track


# ---------- shazamio 适配（兼容不同版本的识别入口） ----------

def _search_params_class() -> Any:
    """返回 ``shazamio_core.SearchParams``；旧版 shazamio 返回 ``None``。"""
    try:
        from shazamio_core import SearchParams  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001  shazamio-core 缺失/版本不匹配时降级
        return None
    return SearchParams


def _new_engine(language: str,
                window: float) -> tuple[Any, Any, float]:
    """构造 shazamio 客户端，返回 ``(shazam, options, core_seconds)``。

    - shazamio >= 0.8：用 ``SearchParams`` 精确指定分析片段，``core`` 即窗口；
    - 旧版 ``recognize``：默认居中截取 10 秒；
    - 更旧的 ``recognize_song``：整段分析（``core`` 返回 -1）。
    """
    from shazamio import Shazam  # 延迟导入：未安装时不影响主程序启动

    params_cls = _search_params_class()
    if params_cls is not None:
        try:
            shazam = Shazam(language=language,
                            segment_duration_seconds=int(window))
            options = params_cls(segment_duration_seconds=int(window))
            return shazam, options, float(int(window))
        except (TypeError, ValueError):
            pass
    shazam = Shazam(language=language)
    return shazam, None, 10.0 if hasattr(shazam, "recognize") else -1.0


async def _query(shazam: Any, wav: str, options: Any) -> Any:
    """调用识别入口，兼容旧版不接受 ``options`` 的签名。"""
    recognize_fn = getattr(shazam, "recognize", None)
    if recognize_fn is None:
        return await shazam.recognize_song(wav)
    if options is None:
        return await recognize_fn(wav)
    try:
        return await recognize_fn(wav, options=options)
    except TypeError:
        return await recognize_fn(wav)


class _Plan(NamedTuple):
    """一次识歌任务的采样规划。"""

    duration: float
    window: float
    starts: list[float]


async def _attempt_window(path: str, start: float, actual: float,
                          engine: tuple[Any, Any, float],
                          deadline: float) -> Optional[dict[str, Any]]:
    """转码并识别单个窗口；超时 / 异常 / 偏移不可信返回 ``None``。"""
    shazam, options, core = engine
    wav = extract_pcm_wav(
        path, start=start, duration=actual,
        sample_rate=16000, channels=1, timeout=30,
    )
    if wav is None:
        log.debug("识歌窗口转码失败 start=%.1fs", start)
        return None
    try:
        remaining = min(
            _ATTEMPT_TIMEOUT,
            deadline - asyncio.get_running_loop().time(),
        )
        if remaining <= 0.2:
            return None
        result = await asyncio.wait_for(_query(shazam, wav, options), remaining)
    except asyncio.TimeoutError:
        log.debug("识歌窗口超时 start=%.1fs（%.1fs）", start, remaining)
        return None
    except Exception as exc:  # noqa: BLE001  单窗口失败继续尝试其他窗口
        log.debug("识歌窗口异常 start=%.1fs: %s", start, exc)
        return None
    finally:
        remove_temp_file(wav)

    track = _evaluate_result(result, start, actual, core)
    if track is None:
        log.debug("识歌窗口未命中或偏移不可信 start=%.1fs", start)
        return None
    log.debug("识歌窗口命中 start=%.1fs -> %s - %s",
              start, track.get("subtitle"), track.get("title"))
    return track


async def _recognize_async(path: str, plan: _Plan, *,
                           budget: float, language: str
                           ) -> tuple[Optional[dict[str, Any]], str, int]:
    """依次识别各采样窗口，命中共识即提前结束。"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(1.0, budget)
    engine = _new_engine(language, plan.window)

    hits: list[dict[str, Any]] = []
    for index, start in enumerate(plan.starts):
        if loop.time() >= deadline:
            log.info("识歌达到总预算（%ss），已尝试 %d/%d 个窗口",
                     budget, index, len(plan.starts))
            break
        actual = plan.window
        if plan.duration > 0:
            actual = min(plan.window, plan.duration - start)
        if actual < 1.0:
            continue
        track = await _attempt_window(path, start, actual, engine, deadline)
        if track is None:
            continue
        hits.append(track)

        chosen, confidence, votes = _pick_consensus(hits)
        if chosen is not None and confidence == "high":
            return chosen, confidence, votes

    return _pick_consensus(hits)


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
        meta["cover_url"] = str(
            images.get("coverart") or images.get("coverarthq") or ""
        ).strip()
    genres = track.get("genres")
    if isinstance(genres, dict):
        meta["genre"] = str(genres.get("primary") or "").strip()

    for item in _metadata_items(track):
        title = str(item.get("title") or "").lower()
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        if title in _ALBUM_LABELS and not meta["album"]:
            meta["album"] = text
        elif title in _RELEASED_LABELS and not meta["year"]:
            meta["year"] = text[:4] if text[:4].isdigit() else text
    return meta


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


def recognize_file(path: str, *,
                   timeout_s: float = _DEFAULT_TIMEOUT,
                   window_s: float = _WINDOW_SECONDS,
                   language: str = _LANGUAGE) -> Optional[dict[str, str]]:
    """识别本地音频文件。

    Args:
        path: 音频路径。
        timeout_s: 所有采样窗口的总预算（秒）。
        window_s: 单个采样窗口时长（秒）。
        language: Shazam 元数据语言，默认 ``zh-CN``（中文歌手 / 简体歌名）。

    Returns:
        ``{title, artist, album, cover_url, genre, year, confidence, votes}``；
        失败返回 ``None``。``confidence`` 为 ``high`` / ``low``。
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

    try:
        budget = max(1.0, float(timeout_s))
    except (TypeError, ValueError):
        budget = _DEFAULT_TIMEOUT
    try:
        window = max(1.0, float(window_s))
    except (TypeError, ValueError):
        window = _WINDOW_SECONDS

    duration = probe_duration(path)
    plan = _Plan(duration=duration, window=window,
                 starts=_candidate_starts(duration, window))
    log.debug("识歌开始: %s（时长 %.1fs，%d 个窗口）",
              os.path.basename(path), duration, len(plan.starts))

    try:
        track, confidence, votes = asyncio.run(
            _recognize_async(
                path, plan,
                budget=budget, language=language or _LANGUAGE,
            )
        )
    except Exception as exc:  # noqa: BLE001  识歌失败不得影响主流程
        log.warning("识歌失败 (%s): %s", os.path.basename(path), exc)
        return None

    if track is None:
        log.info("识歌无结果: %s", os.path.basename(path))
        return None
    meta = _parse_shazam_track(track)
    meta["confidence"] = confidence
    meta["votes"] = str(votes)
    log.info("识歌成功 (%s, %d 个窗口命中): %s - %s",
             confidence, votes, meta["artist"], meta["title"])
    return meta
