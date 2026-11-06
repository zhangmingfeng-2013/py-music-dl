#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""ffmpeg / ffprobe 定位与安全调用。

职责
    * 定位可执行文件：优先随安装包内置，其次系统 ``PATH``；
    * 校验二进制魔数与宿主平台匹配（避免 macOS 误用 Linux ELF）；
    * 统一 subprocess 调用、超时与临时 PCM WAV 提取。

媒体后处理、Whisper 转写与 Shazam 识歌共用本模块，避免各自维护
一份 ffmpeg 命令拼装与临时文件清理逻辑。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from typing import Final, Optional

from utils import log, resource_path


def matches_host_platform(path: str) -> bool:
    """校验二进制魔数与宿主平台匹配。

    ``installer/bin/`` 内可能同时存放为不同平台打包的静态二进制。
    macOS 源码直跑时若仅凭存在性选中 Linux ELF，执行会得到
    ``exec format error``；Windows 下同理需要 PE 头。魔数不符的候选
    直接排除，回退系统 PATH。
    """
    try:
        with open(path, "rb") as handle:
            magic = handle.read(4)
    except OSError:
        return False

    if os.name == "nt":
        return magic[:2] == b"MZ"
    if sys.platform == "darwin":
        # Mach-O 32/64 位（大小端）与 Universal Binary（FAT/FAT64）
        return magic in (
            b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",
            b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
            b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf",
        )
    return magic == b"\x7fELF"  # 其余类 Unix 平台按 ELF 判定


def _candidate_paths(name: str) -> tuple[str, ...]:
    """随安装包内置的可执行文件候选路径（按优先级）。"""
    exe = f"{name}.exe" if os.name == "nt" else name
    # 与 music-dl.spec 中 binaries 的目标目录约定保持一致；
    # 末项兼容源码运行（二进制位于项目 installer/bin/）。
    return (
        resource_path("bin", exe),
        resource_path("ffmpeg", "bin", exe),
        resource_path("ffmpeg", exe),
        resource_path(exe),
        resource_path("installer", "bin", exe),
    )


def resolve_bundled(name: str) -> Optional[str]:
    """在随安装包内置的位置查找可执行文件；无匹配返回 ``None``。"""
    for candidate in _candidate_paths(name):
        if (
            os.path.isfile(candidate)
            and os.access(candidate, os.X_OK)
            and matches_host_platform(candidate)
        ):
            return candidate
    return None


def resolve_tool(name: str) -> str:
    """定位媒体工具：优先随包内置，其次系统 PATH，最后退回裸命令名。"""
    return resolve_bundled(name) or shutil.which(name) or name


FFMPEG_BIN: Final = resolve_tool("ffmpeg")
FFPROBE_BIN: Final = resolve_tool("ffprobe")


def run_ffmpeg(args: list[str], *, timeout: float = 60.0,
               quiet: bool = False,
               binary: Optional[str] = None) -> Optional[subprocess.CompletedProcess]:
    """调用 ffmpeg/ffprobe 并返回结果；超时或无法启动返回 ``None``。

    Args:
        args: 不含可执行文件名的参数列表。
        timeout: 子进程超时（秒）。
        quiet: 是否抑制失败日志（用于可用性探测）。
        binary: 指定可执行文件，缺省 ``FFMPEG_BIN``。
    """
    command = [binary or FFMPEG_BIN, *args]
    try:
        return subprocess.run(
            command, capture_output=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        if not quiet:
            log.warning("媒体工具调用失败 (%s): %s", command[0], exc)
        return None


def ffmpeg_available() -> bool:
    """检测系统是否安装（或随包内置）可用的 ffmpeg。"""
    result = run_ffmpeg(["-version"], timeout=5, quiet=True)
    return result is not None and result.returncode == 0


def _new_temp_path(suffix: str) -> str:
    """创建临时文件占位并返回路径（关闭 fd，由 ffmpeg 覆盖写入）。"""
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    return path


def remove_file_quietly(path: Optional[str]) -> None:
    """删除文件，忽略不存在 / 权限错误。"""
    if not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass


def output_is_valid(result: Optional[subprocess.CompletedProcess],
                    path: str) -> bool:
    """校验 ffmpeg 调用成功且输出文件非空。"""
    return (
        result is not None
        and result.returncode == 0
        and os.path.exists(path)
        and os.path.getsize(path) > 0
    )


def extract_pcm_wav(src: str, *, duration: Optional[float] = None,
                    sample_rate: int = 16000,
                    channels: int = 1,
                    timeout: float = 60.0) -> Optional[str]:
    """把任意音频转成 16kHz mono 16-bit PCM WAV 临时文件。

    Args:
        src: 源音频路径。
        duration: 仅截取前 N 秒（识歌场景用）；``None`` 表示完整音频。
        sample_rate: 采样率。
        channels: 声道数。
        timeout: ffmpeg 超时（秒）。

    Returns:
        临时文件路径；失败返回 ``None``（临时文件已清理）。
    """
    if not src or not os.path.isfile(src):
        return None

    destination = _new_temp_path(".wav")
    args = [
        "-y", "-nostdin", "-loglevel", "error",
        "-i", src,
    ]
    if duration is not None and duration > 0:
        args += ["-t", str(float(duration))]
    args += [
        "-ar", str(int(sample_rate)),
        "-ac", str(int(channels)),
        "-c:a", "pcm_s16le",
        destination,
    ]

    result = run_ffmpeg(args, timeout=timeout)
    if not output_is_valid(result, destination):
        remove_file_quietly(destination)
        return None
    return destination


def remove_temp_file(path: Optional[str]) -> None:
    """公开的临时文件清理入口（供各调用方 finally 块使用）。"""
    remove_file_quietly(path)
