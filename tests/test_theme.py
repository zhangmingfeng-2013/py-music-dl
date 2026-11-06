#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""theme.py 测试：色彩运算、调色板完整性与外观探测回退。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import theme  # noqa: E402
from downloader import TaskStatus  # noqa: E402


class TestColors:
    def test_rgb_hex_roundtrip(self):
        assert theme._rgb("#0A84FF") == (10, 132, 255)
        assert theme._hex(10, 132, 255) == "#0a84ff"

    def test_hex_clamps(self):
        assert theme._hex(-5, 300, 0) == "#00ff00"

    def test_mix(self):
        assert theme.mix("#000000", "#FFFFFF", 0.5) == "#7f7f7f"
        assert theme.mix("#000000", "#FFFFFF", 0) == "#000000"
        assert theme.mix("#000000", "#FFFFFF", 1) == "#ffffff"

    def test_blend_matches_mix(self):
        assert theme.blend("#FF0000", "#0000FF", 0.25) == theme.mix(
            "#0000FF", "#FF0000", 0.25
        )


class TestPalettes:
    def test_schemes_and_modes(self):
        assert set(theme.SCHEMES) == {"liquid", "mono", "aurora"}
        for key, scheme in theme.SCHEMES.items():
            assert scheme["name"]
            assert scheme["light"].scheme == key
            assert scheme["dark"].scheme == key
            assert scheme["light"].dark is False
            assert scheme["dark"].dark is True
        assert [mode for mode, _label in theme.THEME_MODES] == [
            "auto", "light", "dark"
        ]

    def test_palette_is_frozen(self):
        palette = theme.SCHEMES["liquid"]["light"]
        try:
            palette.bg = "#000000"  # type: ignore[misc]
        except Exception as exc:  # frozen dataclass 抛出 FrozenInstanceError
            assert exc.__class__.__name__ == "FrozenInstanceError"
        else:
            raise AssertionError("Palette 应为 frozen dataclass")

    def test_status_entries_cover_all_task_states(self):
        for scheme in theme.SCHEMES.values():
            for appearance in ("light", "dark"):
                status = scheme[appearance].status
                assert set(status) == {item.value for item in TaskStatus}

    def test_geometry_tokens(self):
        liquid = theme.SCHEMES["liquid"]["light"]
        mono = theme.SCHEMES["mono"]["light"]
        assert liquid.radius_card > mono.radius_card
        assert liquid.glass is True
        assert mono.glass is False
        assert liquid.accent_contrast == "#FFFFFF"


class TestSystemAppearance:
    def test_returns_bool_on_current_platform(self):
        assert isinstance(theme.system_prefers_dark(), bool)

    def test_darwin_dark_detection(self, monkeypatch):
        class Result:
            stdout = "Dark\n"

        monkeypatch.setattr(theme.sys, "platform", "darwin")
        monkeypatch.setattr(theme.subprocess, "run", lambda *a, **k: Result())
        assert theme.system_prefers_dark() is True

    def test_failure_falls_back_to_light(self, monkeypatch):
        def boom(*args, **kwargs):
            raise OSError("no defaults command")

        monkeypatch.setattr(theme.sys, "platform", "darwin")
        monkeypatch.setattr(theme.subprocess, "run", boom)
        assert theme.system_prefers_dark() is False


if __name__ == "__main__":
    raise SystemExit("请使用 pytest 运行该测试文件")
