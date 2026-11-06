#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Whisper 语音转写 → 结构化 LRC。

* 封装 faster-whisper 本地推理，默认 base 模型（约 140MB，首次自动下载）；
* 后处理：按时间轴生成 ``[mm:ss.xx]``、长句按句末标点拆分、相邻重复去重；
* 模型加载为进程级单例（带锁），重复调用不会重复实例化；
* 不向调用方抛异常，任何失败返回 ``None`` 并记录日志。
"""

from __future__ import annotations

import importlib.util
import os
import re
import threading
from typing import Any, Callable, Iterator, Optional

from ffmpeg import extract_pcm_wav, remove_temp_file
from utils import log

#: 模型档位（base 为中文识别率与体积的平衡点）
_WHISPER_MODEL = "base"

_SENTENCE_END_RE = re.compile(r"([。！？；…])")


def whisper_available() -> bool:
    """探测 faster-whisper 是否已安装（不触发模型下载）。"""
    return importlib.util.find_spec("faster_whisper") is not None


class _ModelLoader:
    """模块级单例：懒加载 ``WhisperModel``，仅首次调用时实例化。"""

    def __init__(self) -> None:
        self._model: Any = None
        self._lock = threading.Lock()

    def get(self) -> Any:
        """返回模型实例；多个线程首次并发调用时只加载一次。"""
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel  # 延迟导入，避免启动开销

                log.info("正在加载 Whisper %s 模型（首次使用需下载）…", _WHISPER_MODEL)
                self._model = WhisperModel(
                    _WHISPER_MODEL,
                    device="cpu",
                    compute_type="int8",
                )
        return self._model


_MODEL = _ModelLoader()


# ---------------------------------------------------------------------------
# 纯后处理：segments → LRC
# ---------------------------------------------------------------------------


def _hundredths(timestamp: float) -> str:
    """秒 → ``[mm:ss.hh]``；负值按 0 处理，百分秒钳制到 99。"""
    value = max(0.0, float(timestamp))
    minutes = int(value) // 60
    seconds = int(value) % 60
    hundredths = int(round((value - int(value)) * 100))
    if hundredths >= 100:
        hundredths = 99
    return f"[{minutes:02d}:{seconds:02d}.{hundredths:02d}]"


def _merge_clauses(parts: list[str]) -> list[str]:
    """把 ``re.split`` 产生的标点片段归并到前一个分句。"""
    clauses: list[str] = []
    for part in parts:
        if _SENTENCE_END_RE.match(part):
            if clauses:
                clauses[-1] += part
            continue
        clause = part.strip()
        if clause:
            clauses.append(clause)
    return clauses


def _split_segment(seg_start: float, seg_end: float,
                   text: str) -> Iterator[tuple[float, float, str]]:
    """对超长 segment 按句末标点拆分，时间按字符占比线性分配。

    ``<= 8s`` 的 segment 保持原样，避免把正常歌词切得过碎。
    """
    parts = _SENTENCE_END_RE.split(text)
    if len(parts) <= 1 or (seg_end - seg_start) <= 8.0:
        yield seg_start, seg_end, text
        return

    clauses = _merge_clauses(parts)
    if not clauses:
        yield seg_start, seg_end, text
        return

    # 分句长度包含句末标点，按字符占比分配时间轴
    lengths = [len(clause) for clause in clauses]
    total = sum(lengths)
    duration = seg_end - seg_start
    offset = seg_start
    for index, clause in enumerate(clauses):
        ratio = lengths[index] / total if total else (1.0 / len(clauses))
        piece_duration = duration * ratio
        end = offset + piece_duration
        yield offset, end, clause
        offset = end


def _segments_to_lrc(segments: list[Any], *, meta_title: str = "",
                     meta_artist: str = "") -> str:
    """把 faster-whisper segments 转成标准 LRC 文本。"""
    lines: list[str] = []
    if meta_title:
        lines.append(f"[ti:{meta_title}]")
    if meta_artist:
        lines.append(f"[ar:{meta_artist}]")

    previous = ""
    for segment in segments:
        start = float(getattr(segment, "start", 0.0))
        end = float(getattr(segment, "end", 0.0))
        text = str(getattr(segment, "text", "")).strip()
        if not text or not any(char.isalnum() for char in text):
            continue
        for piece_start, _piece_end, piece_text in _split_segment(start, end, text):
            if not piece_text or piece_text == previous:
                continue
            lines.append(f"{_hundredths(piece_start)}{piece_text}")
            previous = piece_text
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def _fallback_wav(src: str) -> Optional[str]:
    """兼容旧接口：把任意音频转成 16kHz mono WAV 临时文件。"""
    return extract_pcm_wav(src, timeout=60)


def _transcribe_once(model: Any, path: str,
                     language: Optional[str],
                     progress_cb: Optional[Callable[[str], None]],
                     *, meta_title: str = "",
                     meta_artist: str = "") -> Optional[str]:
    """执行一次转写；没有有效 segment 时返回 ``None``。"""
    if progress_cb is not None:
        try:
            progress_cb("Whisper 识别中…")
        except Exception:  # noqa: BLE001  进度回调异常不影响识别
            pass
    segments_iter, _info = model.transcribe(
        path,
        language=language,
        vad_filter=True,
        beam_size=5,
        condition_on_previous_text=True,
    )
    segments = list(segments_iter)
    if not segments:
        return None
    return _segments_to_lrc(
        segments, meta_title=meta_title, meta_artist=meta_artist
    )


def transcribe_to_lrc(
    audio_path: str,
    *,
    meta_title: str = "",
    meta_artist: str = "",
    language: Optional[str] = None,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    """对本地音频文件进行 Whisper 转写，返回 LRC 文本；失败返回 ``None``。"""
    if not whisper_available():
        log.warning("faster-whisper 未安装，跳过 Whisper 歌词兜底")
        return None
    if not audio_path or not os.path.isfile(audio_path):
        return None

    tmp_wav: Optional[str] = None
    try:
        try:
            model = _MODEL.get()
        except Exception as exc:  # noqa: BLE001  模型下载/加载失败按无结果处理
            log.warning("Whisper 模型加载失败: %s", exc)
            return None
        # 先尝试原始文件；PyAV 解码失败时才用 ffmpeg 转 WAV 回退
        for attempt_path, is_fallback in (
            (audio_path, False),
            (None, True),
        ):
            if is_fallback:
                tmp_wav = _fallback_wav(audio_path)
                if tmp_wav is None:
                    return None
                attempt_path = tmp_wav
            try:
                return _transcribe_once(
                    model, attempt_path, language, progress_cb,
                    meta_title=meta_title, meta_artist=meta_artist,
                )
            except Exception as exc:  # noqa: BLE001  解码/推理异常按回退策略处理
                if not is_fallback:
                    log.info("Whisper 直接解码失败，尝试 ffmpeg 回退: %s", exc)
                    continue
                log.warning("Whisper 识别失败: %s", exc)
                return None
        return None
    finally:
        remove_temp_file(tmp_wav)
