#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""theme.py 测试：色彩运算、调色板完整性与外观探测回退。"""

import os
import sys
import threading

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
        theme.invalidate_appearance_cache()
        assert isinstance(theme.system_prefers_dark(), bool)

    def test_darwin_dark_detection(self, monkeypatch):
        class Result:
            stdout = "Dark\n"

        monkeypatch.setattr(theme.sys, "platform", "darwin")
        monkeypatch.setattr(theme.subprocess, "run", lambda *a, **k: Result())
        theme.invalidate_appearance_cache()
        assert theme.system_prefers_dark() is True

    def test_failure_falls_back_to_light(self, monkeypatch):
        def boom(*args, **kwargs):
            raise OSError("no defaults command")

        monkeypatch.setattr(theme.sys, "platform", "darwin")
        monkeypatch.setattr(theme.subprocess, "run", boom)
        theme.invalidate_appearance_cache()
        assert theme.system_prefers_dark() is False

    def test_result_is_cached(self, monkeypatch):
        calls = []

        class Result:
            stdout = "Dark\n"

        def fake_run(*args, **kwargs):
            calls.append(args)
            return Result()

        monkeypatch.setattr(theme.sys, "platform", "darwin")
        monkeypatch.setattr(theme.subprocess, "run", fake_run)
        theme.invalidate_appearance_cache()
        assert theme.system_prefers_dark() is True
        assert theme.system_prefers_dark() is True
        assert len(calls) == 1  # 第二次命中缓存，不再拉起子进程

        assert theme.system_prefers_dark(refresh=True) is True
        assert len(calls) == 2  # refresh=True 强制重新探测

    def test_cached_appearance_none_when_cold(self, monkeypatch):
        theme.invalidate_appearance_cache()
        # 从未探测：读取缓存不触发子进程，只返回 None
        assert theme.cached_appearance() is None

    def test_appearance_watcher_reports_change(self, monkeypatch):
        values = [True, True, False, False]
        seen: list[bool] = []
        done = threading.Event()

        def probe():
            return values.pop(0) if values else False

        def on_change(dark):
            seen.append(dark)
            done.set()

        monkeypatch.setattr(theme, "_probe_system_dark", probe)
        theme.invalidate_appearance_cache()
        watcher = theme.AppearanceWatcher(interval=0.5, on_change=on_change)
        watcher.start()
        try:
            assert done.wait(5.0), "watcher 未报告外观变化"
        finally:
            watcher.stop()
        assert seen == [False]
        assert theme.cached_appearance() is False
        assert watcher.running is False


class TestThemeHelpers:
    def test_glyph_and_label(self):
        assert theme.glyph_for("auto") == "half"
        assert theme.glyph_for("light") == "sun"
        assert theme.glyph_for("dark") == "moon"
        assert theme.glyph_for("bogus") == "half"  # 未知值按 auto 处理
        assert theme.mode_label("auto") == "自动（跟随系统）"
        assert theme.mode_label("bogus") == "自动（跟随系统）"

    def test_normalize_mode(self):
        assert theme.normalize_mode("dark") == "dark"
        assert theme.normalize_mode("light") == "light"
        assert theme.normalize_mode("neon") == "auto"

    def test_resolve_dark(self):
        assert theme.resolve_dark("dark") is True
        assert theme.resolve_dark("light") is False
        assert theme.resolve_dark("auto", system_dark=True) is True
        assert theme.resolve_dark("auto", system_dark=False) is False

    def test_palette_for(self):
        assert theme.palette_for("mono", "dark").dark is True
        assert theme.palette_for("mono", "light").dark is False
        assert theme.palette_for("aurora", "auto", system_dark=True).scheme == "aurora"
        # 未知方案回退 Liquid，不会抛 KeyError
        assert theme.palette_for("nope", "light").scheme == theme.FALLBACK_SCHEME
        # auto + 相同系统外观得到同一冻结实例（可做身份比较跳过重绘）
        assert theme.palette_for("liquid", "auto", system_dark=True) is \
            theme.palette_for("liquid", "dark")


if __name__ == "__main__":
    raise SystemExit("请使用 pytest 运行该测试文件")
