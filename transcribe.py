#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Whisper 语音转写 → 结构化 LRC
- 封装 faster-whisper 本地推理，默认 base 模型（约 140MB，首次自动下载）
- 后处理：按时间轴生成 [mm:ss.xx]、断句优化、去重
- 不抛出异常，任何失败返回 None 并打日志
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import tempfile
from typing import Any, Callable, Iterator, Optional

from media import FFMPEG_BIN
from utils import log

# 模型档位（base 为中文-体积平衡）
_WHISPER_MODEL = "base"

_SENTENCE_END_RE = re.compile(r"([。！？；…])")


def whisper_available() -> bool:
    """探测 faster-whisper 是否已安装（不触发模型下载）。"""
    return importlib.util.find_spec("faster_whisper") is not None


class _ModelLoader:
    """模块级单例：懒加载 WhisperModel，仅首次调用时实例化。"""

    def __init__(self) -> None:
        self._model: Any = None

    def get(self) -> Any:
        if self._model is None:
            from faster_whisper import WhisperModel
            log.info("正在加载 Whisper %s 模型（首次使用需下载）…", _WHISPER_MODEL)
            self._model = WhisperModel(
                _WHISPER_MODEL,
                device="cpu",
                compute_type="int8",
            )
        return self._model


_MODEL = _ModelLoader()


# ---- 纯后处理：segments → LRC ----


def _hundredths(t: float) -> str:
    """秒 → [mm:ss.hh]。"""
    mins = int(t) // 60
    secs = int(t) % 60
    hunds = int(round((t - int(t)) * 100))
    if hunds >= 100:
        hunds = 99
    return f"[{mins:02d}:{secs:02d}.{hunds:02d}]"


def _split_segment(seg_start: float, seg_end: float, text: str) -> Iterator[tuple[float, float, str]]:
    """对超长 segment 按句末标点拆分，时间按字符占比线性分配。"""
    parts = _SENTENCE_END_RE.split(text)
    if len(parts) <= 1 or (seg_end - seg_start) <= 8.0:
        yield seg_start, seg_end, text
        return
    # 把标点前移归并到前一个分句
    clauses: list[str] = []
    i = 0
    while i < len(parts):
        if _SENTENCE_END_RE.match(parts[i]):
            if clauses:
                clauses[-1] += parts[i]
            i += 1
        else:
            clause = parts[i].strip()
            if clause:
                clauses.append(clause)
            i += 1
    if not clauses:
        yield seg_start, seg_end, text
        return
    # 标点视为占一个字符权重（不实际计入但用于保持比例）
    lens = [len(c) for c in clauses]
    total = sum(lens)
    dur = seg_end - seg_start
    offset = seg_start
    for idx, c in enumerate(clauses):
        ratio = lens[idx] / total if total else (1.0 / len(clauses))
        piece_dur = dur * ratio
        end = offset + piece_dur
        yield offset, end, c
        offset = end


def _segments_to_lrc(segments: list[Any], *, meta_title: str = "", meta_artist: str = "") -> str:
    """将 faster-whisper segments 转成标准 LRC。"""
    lines: list[str] = []
    if meta_title:
        lines.append(f"[ti:{meta_title}]")
    if meta_artist:
        lines.append(f"[ar:{meta_artist}]")

    prev_text = ""
    for seg in segments:
        start = float(getattr(seg, "start", 0.0))
        end = float(getattr(seg, "end", 0.0))
        text = str(getattr(seg, "text", "")).strip()
        if not text or not any(ch.isalnum() for ch in text):
            continue
        for s, _e, t in _split_segment(start, end, text):
            if not t or t == prev_text:
                continue
            lines.append(f"{_hundredths(s)}{t}")
            prev_text = t
    return "\n".join(lines)


# ---- 主入口 ----


def _fallback_wav(src: str) -> Optional[str]:
    """用 ffmpeg 把任意音频转成 16kHz mono WAV，返回临时文件路径。"""
    try:
        fd, dst = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        cmd = [
            FFMPEG_BIN, "-y", "-nostdin", "-loglevel", "error",
            "-i", src,
            "-ar", "16000", "-ac", "1",
            "-c:a", "pcm_s16le",
            dst,
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=60, check=False)
        if r.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst) == 0:
            try:
                os.remove(dst)
            except OSError:
                pass
            return None
        return dst
    except (OSError, subprocess.SubprocessError):
        return None


def transcribe_to_lrc(
    audio_path: str,
    *,
    meta_title: str = "",
    meta_artist: str = "",
    language: Optional[str] = None,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    """对本地音频文件进行 Whisper 转写，返回 LRC 文本；失败返回 None。"""
    if not whisper_available():
        log.warning("faster-whisper 未安装，跳过 Whisper 歌词兜底")
        return None
    if not os.path.isfile(audio_path):
        return None

    tmp_wav: Optional[str] = None
    try:
        model = _MODEL.get()
        # 先尝试原始文件；PyAV 解码失败时才 ffmpeg 转 WAV 回退
        attempt_paths: list[Optional[str]] = [audio_path, None]
        for attempt_path in attempt_paths:
            if attempt_path is None:
                tmp_wav = _fallback_wav(audio_path)
                if tmp_wav is None:
                    return None
                attempt_path = tmp_wav
            if progress_cb is not None:
                progress_cb("Whisper 识别中…")
            try:
                segs, _info = model.transcribe(
                    attempt_path,
                    language=language,
                    vad_filter=True,
                    beam_size=5,
                    condition_on_previous_text=True,
                )
                segments = list(segs)
                if not segments:
                    return None
                return _segments_to_lrc(segments, meta_title=meta_title, meta_artist=meta_artist)
            except Exception as exc:  # noqa: BLE001
                if attempt_path == audio_path:
                    log.info("Whisper 直接解码失败，尝试 ffmpeg 回退: %s", exc)
                    continue
                log.warning("Whisper 识别失败: %s", exc)
                return None
        return None
    finally:
        if tmp_wav is not None and os.path.exists(tmp_wav):
            try:
                os.remove(tmp_wav)
            except OSError:
                pass
