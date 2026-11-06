#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""utils.py 单元测试：文件名清理、格式化、音质归一化、JSON 原子写入。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils  # noqa: E402


class TestSafeFilename:
    def test_removes_reserved_chars(self):
        assert utils.safe_filename('a/b\\c:d*e?f"g<h>i|j') == "abcdefghij"

    def test_strips_whitespace(self):
        assert utils.safe_filename("  hello  ") == "hello"

    def test_removes_control_chars(self):
        assert utils.safe_filename("a\nb\tc\x00d\x7f") == "abcd"

    def test_none_and_non_string(self):
        assert utils.safe_filename(None) == ""
        assert utils.safe_filename(123) == "123"

    def test_keeps_unicode(self):
        assert utils.safe_filename("周杰伦 - 晴天") == "周杰伦 - 晴天"


class TestFormatters:
    def test_duration(self):
        assert utils.format_duration(0) == "--:--"
        assert utils.format_duration(-5) == "--:--"
        assert utils.format_duration(None) == "--:--"
        assert utils.format_duration(float("nan")) == "--:--"
        assert utils.format_duration(61.9) == "1:01"

    def test_size(self):
        assert utils.format_size(0) == "未知"
        assert utils.format_size(-1) == "未知"
        assert utils.format_size(512) == "0.5 KB"
        assert utils.format_size(1024 * 1024) == "1.00 MB"
        assert utils.format_size("bad") == "未知"

    def test_speed(self):
        assert utils.format_speed(0) == "--"
        assert utils.format_speed(-1) == "--"
        assert utils.format_speed(2048) == "2 KB/s"
        assert utils.format_speed(2.5 * 1024 * 1024) == "2.5 MB/s"
        assert utils.format_speed(float("inf")) == "--"

    def test_progress_bar(self):
        assert utils.format_progress_bar(0, 0) == "已下载: 未知"
        bar = utils.format_progress_bar(50, 100, bar_width=10)
        assert bar == "[█████░░░░░] 50.0%"
        # 超量下载钳制到 100%
        assert utils.format_progress_bar(200, 100, bar_width=10).endswith("100.0%")
        assert utils.format_progress_bar(-1, 100).startswith("[░░░")


class TestExtensionsAndQuality:
    def test_ext_from_url(self):
        assert utils.ext_from_url("https://x/a.flac") == "flac"
        assert utils.ext_from_url("https://x/a.FLAC?token=1") == "flac"
        assert utils.ext_from_url("https://x/a.m4a#frag") == "m4a"
        assert utils.ext_from_url("https://x/stream") == "mp3"
        assert utils.ext_from_url("https://x/a.xyz") == "mp3"
        assert utils.ext_from_url("") == "mp3"

    def test_quality_from_ext(self):
        assert utils.quality_from_ext("flac") == "LOSSLESS"
        assert utils.quality_from_ext(".ape") == "LOSSLESS"
        assert utils.quality_from_ext("mp3") == "320K"

    def test_quality_tier_table(self):
        cases = [
            ("", "https://x/a.flac", utils.TIER_LOSSLESS),
            ("FLAC", "", utils.TIER_LOSSLESS),
            ("LOSSLESS", "", utils.TIER_LOSSLESS),
            ("320K", "", utils.TIER_HQ),
            ("320", "", utils.TIER_HQ),
            ("320kbps", "", utils.TIER_HQ),
            ("192K", "", utils.TIER_STANDARD),
            ("96kbps", "", utils.TIER_STANDARD),
            ("", "https://x/a.mp3", utils.TIER_STANDARD),
            ("", "", utils.TIER_UNKNOWN),
            ("", "https://x/stream?br=320", utils.TIER_HQ),
            ("", "https://x/stream?br=128", utils.TIER_STANDARD),
            ("", "https://x/a.ape", utils.TIER_LOSSLESS),
            # 标签与链接冲突时按真实容器（无损扩展名优先）
            ("320K", "https://x/a.flac", utils.TIER_LOSSLESS),
        ]
        for quality, url, expected in cases:
            assert utils.quality_tier(quality, url) == expected, (quality, url)

    def test_tier_metadata(self):
        assert utils.TIER_ORDER[utils.TIER_LOSSLESS] > utils.TIER_ORDER[utils.TIER_HQ]
        assert utils.TIER_LABELS[utils.TIER_UNKNOWN] == "未知"


class TestJsonHelpers:
    def test_roundtrip_and_parent_creation(self, tmp_path):
        target = tmp_path / "nested" / "config.json"
        payload = {"标题": "晴天", "count": 2}
        assert utils.save_json_atomic(str(target), payload)
        assert utils.load_json(str(target), {}) == payload

    def test_load_missing_and_corrupt(self, tmp_path):
        missing = tmp_path / "missing.json"
        assert utils.load_json(str(missing), {"a": 1}) == {"a": 1}
        corrupt = tmp_path / "corrupt.json"
        corrupt.write_text("{broken", encoding="utf-8")
        assert utils.load_json(str(corrupt), []) == []

    def test_save_failure_returns_false(self, tmp_path):
        # 目标路径是一个目录 → os.replace 失败
        directory = tmp_path / "as_dir"
        directory.mkdir()
        assert not utils.save_json_atomic(str(directory), {"a": 1})
        # 失败后不遗留临时文件
        leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".tmp-")]
        assert leftovers == []

    def test_default_copy_is_not_shared(self):
        default = {"a": 1}
        first = utils.load_json("/nonexistent/never.json", default)
        first["a"] = 2
        assert default == {"a": 1}


def test_path_helpers():
    assert utils.resource_path("assets", "x.png").endswith(
        os.path.join("assets", "x.png")
    )
    assert isinstance(utils.app_base_dir(), str)
    assert utils.is_frozen() is False


if __name__ == "__main__":
    import pytest  # noqa: F401  允许直接运行 pytest
    raise SystemExit("请使用 pytest 运行该测试文件")
