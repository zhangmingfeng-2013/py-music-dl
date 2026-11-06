#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""ffmpeg.py 测试：平台魔数校验、工具定位、WAV 提取。"""

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ffmpeg  # noqa: E402


class TestPlatformMagic:
    def test_missing_and_empty(self, tmp_path):
        assert ffmpeg.matches_host_platform(str(tmp_path / "missing")) is False
        empty = tmp_path / "empty"
        empty.write_bytes(b"")
        assert ffmpeg.matches_host_platform(str(empty)) is False

    def test_elf_rejected_off_linux(self, tmp_path):
        elf = tmp_path / "ffmpeg"
        elf.write_bytes(b"\x7fELF" + b"\x00" * 60)
        expected = sys.platform.startswith("linux")
        assert ffmpeg.matches_host_platform(str(elf)) is expected


class TestResolve:
    def test_returns_string(self):
        assert isinstance(ffmpeg.FFMPEG_BIN, str)
        assert isinstance(ffmpeg.FFPROBE_BIN, str)
        assert isinstance(ffmpeg.resolve_tool("definitely-not-a-real-binary"), str)

    def test_ffmpeg_available_returns_bool(self):
        assert isinstance(ffmpeg.ffmpeg_available(), bool)

    def test_run_missing_binary(self):
        assert ffmpeg.run_ffmpeg(
            ["-version"], timeout=2, quiet=True, binary="/no/such/ffmpeg"
        ) is None


class TestTempHelpers:
    def test_remove_file_quietly(self, tmp_path):
        path = tmp_path / "x"
        path.write_text("x")
        ffmpeg.remove_file_quietly(str(path))
        assert not path.exists()
        # 再次删除不存在文件不抛异常
        ffmpeg.remove_file_quietly(str(path))
        ffmpeg.remove_file_quietly(None)

    def test_output_is_valid(self):
        assert ffmpeg.output_is_valid(None, "x") is False

        result = subprocess.CompletedProcess(args=[], returncode=0)
        assert ffmpeg.output_is_valid(result, "/nonexistent") is False

    def test_extract_requires_source(self):
        assert ffmpeg.extract_pcm_wav("") is None
        assert ffmpeg.extract_pcm_wav("/nonexistent/audio.mp3") is None


@pytest.mark.skipif(not ffmpeg.ffmpeg_available(), reason="需要 ffmpeg")
def test_extract_wav(tmp_path):
    source = tmp_path / "tone.wav"
    generated = ffmpeg.run_ffmpeg([
        "-y", "-nostdin", "-loglevel", "error",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=0.2",
        "-c:a", "pcm_s16le", str(source),
    ])
    assert generated is not None and generated.returncode == 0

    extracted = ffmpeg.extract_pcm_wav(str(source), duration=0.1, timeout=20)
    assert extracted is not None
    try:
        assert os.path.getsize(extracted) > 0
        assert extracted.endswith(".wav")
    finally:
        ffmpeg.remove_temp_file(extracted)


if __name__ == "__main__":
    raise SystemExit("请使用 pytest 运行该测试文件")
