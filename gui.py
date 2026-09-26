#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
音乐下载器 GUI v3.1 — 多方案自适应设计系统
功能：多平台并发搜索 + 批量下载队列 + 任务面板（进度/暂停/取消）
数据源：基于聚合音乐站 API
支持平台：咪咕音乐 / 网易云音乐 / QQ音乐 / 酷我音乐

设计系统（三套可切换方案，均与 Apple 硬件设计语言协调）：
  · Liquid 液态玻璃 — 对齐 macOS / iOS 26：大圆角胶囊、通透材质、系统蓝
  · Mono 单色极简 — 对齐专业工具：直角化小圆角、黑白灰、无斑马纹
  · Aurora 极光柔彩 — 对齐多彩消费硬件：超大圆角、紫罗兰主色、柔光底
通用语言：
  · 连续圆角（超椭圆 squircle，几何令牌按方案统一下发）
  · 自适应色彩（环境跟随系统外观 / 内容跟随任务状态 / 用户手动覆盖）
  · 半透明材质层次（窗口 → 卡片 → 输入 → 悬浮 逐级抬升）
  · 极简退让（发丝线 + 留白，无重边框阴影）
  · 统一字体与单色描边符号（苹方 + 自绘图标库）
  · 克制动效（110~200ms 缓动过渡）
  · python3 gui.py --demo 进入设计预览（演示数据，用于 UX 测试）
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk, messagebox, filedialog, font as tkfont
from typing import Any, Callable, Optional

from api import PLATFORM_NAMES, search_all_platforms, get_song_detail
from downloader import DownloadQueue, DownloadTask, TaskStatus
from utils import ensure_download_dir, format_size, DEFAULT_DOWNLOAD_DIR

# ---- 常量 ----

WIN_WIDTH = 1040
WIN_HEIGHT = 820
MIN_WIDTH = 940
MIN_HEIGHT = 680
TASK_ROW_HEIGHT = 54
MAX_TASK_PANEL_HEIGHT = 4 * TASK_ROW_HEIGHT

UI_FONT = "PingFang SC"
MONO_FONT = "SF Mono"

APP_TITLE = "音乐下载器"
APP_VERSION = "v3.1"
APP_SUBTITLE = "多平台聚合 · 咪咕 网易云 QQ音乐 酷我"

SETTINGS_FILE = "settings.json"
DEFAULT_SETTINGS = {"scheme": "liquid", "theme_mode": "auto"}

# ==================== 色彩工具 ====================


def _rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def _hex(r: int, g: int, b: int) -> str:
    return f"#{max(0, min(255, int(r))):02x}{max(0, min(255, int(g))):02x}{max(0, min(255, int(b))):02x}"


def mix(a: str, b: str, t: float) -> str:
    """a 向 b 混合 t（0~1），t 越大越接近 b"""
    ar, ag, ab = _rgb(a)
    br, bg, bb = _rgb(b)
    return _hex(
        ar + (br - ar) * t,
        ag + (bg - ag) * t,
        ab + (bb - ab) * t,
    )


def blend(over: str, under: str, alpha: float) -> str:
    """将 over 以 alpha 透明度叠在 under 上（模拟半透明材质）"""
    return mix(under, over, alpha)


# ==================== 连续圆角（squircle）=============


def _squircle_points(
    x1: float, y1: float, x2: float, y2: float,
    r: float, n: float = 4.5, steps: int = 11,
) -> list[float]:
    """超椭圆圆角矩形路径（连续曲率，接近 Apple squircle）。返回平铺坐标列表。"""
    w, h = x2 - x1, y2 - y1
    r = min(r, w / 2, h / 2)
    if r < 1.5 or w <= 2 * r:
        return [x1, y1, x2, y1, x2, y2, x1, y2]

    p = 2.0 / n
    pts: list[float] = []

    def arc(cx: float, cy: float, sx: int, sy: int, t0: float, t1: float) -> None:
        for i in range(steps + 1):
            t = t0 + (t1 - t0) * i / steps
            c = max(math.cos(t), 0.0)
            s = max(math.sin(t), 0.0)
            pts.extend([cx + sx * r * (c ** p), cy + sy * r * (s ** p)])

    pts.extend([x1 + r, y1, x2 - r, y1])                       # 顶边
    arc(x2 - r, y1 + r, +1, +1, math.pi / 2, 0.0)              # 右上角
    pts.extend([x2, y2 - r])                                   # 右边
    arc(x2 - r, y2 - r, +1, +1, 0.0, math.pi / 2)              # 右下角
    pts.extend([x1 + r, y2])                                   # 底边
    arc(x1 + r, y2 - r, -1, +1, math.pi / 2, 0.0)              # 左下角
    pts.extend([x1, y1 + r])                                   # 左边
    arc(x1 + r, y1 + r, -1, -1, 0.0, math.pi / 2)              # 左上角
    return pts


# ==================== 统一单色符号库 ====================

GLYPHS: frozenset[str] = frozenset({
    "note", "search", "folder", "trash", "clock", "download",
    "pause", "play", "close", "chevron", "moon", "sun", "half",
})


def draw_glyph(
    cv: tk.Canvas, name: str, cx: float, cy: float, fg: str,
    s: float = 1.0,
) -> None:
    """在 (cx, cy) 处绘制统一描边风格的单色符号。

    设计框约 12×12，s 为缩放系数；全部使用圆头线/实心填充两种语汇，
    保证任何方案下图标视觉重量一致。
    """
    lw = max(1.5 * s, 1.0)

    def X(x: float) -> float:
        return cx + x * s

    def Y(y: float) -> float:
        return cy + y * s

    def line(x1: float, y1: float, x2: float, y2: float, width: float = lw) -> None:
        cv.create_line(
            X(x1), Y(y1), X(x2), Y(y2), fill=fg, width=width,
            capstyle=tk.ROUND,
        )

    def poly(points: list[tuple[float, float]]) -> None:
        cv.create_polygon(
            [v for x, y in points for v in (X(x), Y(y))],
            fill=fg, outline="", smooth=False,
        )

    if name == "note":                       # 八分音符 ♪
        cv.create_oval(X(-5.2), Y(2.4), X(-0.6), Y(6.2), fill=fg, outline="")
        line(-2.9, 3.2, -2.9, -5.2)
        poly([(-2.9, -5.2), (3.2, -3.0), (3.2, -0.2), (-2.9, -2.4)])
    elif name == "search":
        cv.create_oval(
            X(-5.2), Y(-5.2), X(1.2), Y(1.2),
            fill="", outline=fg, width=lw,
        )
        line(1.8, 1.8, 5.2, 5.2)
    elif name == "folder":
        poly([
            (-6, -1.2), (-2.8, -1.2), (-1.4, -3.2), (6, -3.2),
            (6, 4.2), (-6, 4.2),
        ])
    elif name == "trash":
        line(-4.2, -3.2, 4.2, -3.2)
        line(-2.6, -4.8, 2.6, -4.8)
        line(-3, -3.2, -2.3, 4.4)
        line(3, -3.2, 2.3, 4.4)
        line(-2.3, 4.4, 2.3, 4.4)
    elif name == "clock":
        cv.create_oval(X(-4.8), Y(-4.8), X(4.8), Y(4.8), fill="", outline=fg, width=lw)
        line(0, 0, 0, -3.0)
        line(0, 0, 2.1, 0.8)
    elif name == "download":
        line(0, -5.4, 0, 2.2)
        line(-3.0, -0.6, 0, 2.6)
        line(3.0, -0.6, 0, 2.6)
        line(-5.2, 2.0, -5.2, 5.0)
        line(-5.2, 5.0, 5.2, 5.0)
        line(5.2, 2.0, 5.2, 5.0)
    elif name == "pause":
        cv.create_rectangle(X(-4.4), Y(-5), X(-1.2), Y(5), fill=fg, outline="")
        cv.create_rectangle(X(1.2), Y(-5), X(4.4), Y(5), fill=fg, outline="")
    elif name == "play":
        poly([(-3.6, -5.2), (5.2, 0), (-3.6, 5.2)])
    elif name == "close":
        line(-4, -4, 4, 4)
        line(-4, 4, 4, -4)
    elif name == "chevron":
        line(-3.2, -2.2, 0, 1.2)
        line(0, 1.2, 3.2, -2.2)
    elif name == "moon":
        cv.create_arc(
            X(-6), Y(-7), X(7), Y(7),
            start=90, extent=180, fill=fg, outline="", style=tk.PIESLICE,
        )
        cv.create_oval(X(-7), Y(-7), X(7), Y(7), fill="", outline=fg, width=lw)
    elif name == "sun":
        cv.create_oval(X(-3), Y(-3), X(3), Y(3), fill="", outline=fg, width=lw)
        for i in range(8):
            a = i * math.pi / 4
            x1, y1 = math.cos(a) * 4.4, math.sin(a) * 4.4
            x2, y2 = math.cos(a) * 6.2, math.sin(a) * 6.2
            line(x1, y1, x2, y2)
    elif name == "half":                    # 自动模式：半明半暗
        cv.create_arc(
            X(-6), Y(-6), X(6), Y(6),
            start=90, extent=180, fill=fg, outline="", style=tk.PIESLICE,
        )
        cv.create_oval(X(-6), Y(-6), X(6), Y(6), fill="", outline=fg, width=lw)


# ==================== 缓动 ====================


def ease_out_cubic(k: float) -> float:
    return 1.0 - (1.0 - k) ** 3


def ease_in_out_sine(k: float) -> float:
    return (1.0 - math.cos(math.pi * k)) / 2.0


class Animator:
    """克制动效调度器：16ms 帧循环，按 key 覆盖旧动画。

    任务字典为类级共享，任意实例都可取消同一 key 的旧动画。
    """

    _jobs: dict[str, str] = {}

    def __init__(self, root: tk.Misc):
        self.root = root

    def cancel(self, key: str) -> None:
        if key in self._jobs:
            try:
                self.root.after_cancel(self._jobs.pop(key))
            except Exception:
                pass

    def animate(
        self, key: str, t0: float, t1: float, dur_ms: int,
        easing: Callable[[float], float] = ease_out_cubic,
        on_frame: Optional[Callable[[float], None]] = None,
        on_done: Optional[Callable[[], None]] = None,
    ) -> None:
        self.cancel(key)
        start = time.monotonic()

        def step() -> None:
            k = min((time.monotonic() - start) * 1000.0 / dur_ms, 1.0)
            value = t0 + (t1 - t0) * easing(k)
            if on_frame:
                try:
                    on_frame(value)
                except tk.TclError:
                    return
            if k < 1.0:
                self._jobs[key] = self.root.after(16, step)
            else:
                self._jobs.pop(key, None)
                if on_done:
                    on_done()

        self._jobs[key] = self.root.after(0, step)


# ==================== 字体 ====================

_font_cache: dict[tuple[Any, ...], tkfont.Font] = {}


def ui_font(size: int, bold: bool = False) -> tkfont.Font:
    key = (UI_FONT, size, bold)
    if key not in _font_cache:
        _font_cache[key] = tkfont.Font(
            family=UI_FONT, size=size,
            weight="bold" if bold else "normal",
        )
    return _font_cache[key]


def mono_font(size: int = 10) -> tkfont.Font:
    key = ("mono", size)
    if key not in _font_cache:
        _font_cache[key] = tkfont.Font(family=MONO_FONT, size=size)
    return _font_cache[key]


def _truncate(text: str, fnt: tkfont.Font, max_w: float) -> str:
    if fnt.measure(text) <= max_w:
        return text
    while text and fnt.measure(text + "…") > max_w:
        text = text[:-1]
    return text + "…"


# ==================== 主题（自适应明暗）=============


@dataclass(frozen=True)
class Palette:
    name: str
    scheme: str
    dark: bool
    bg: str             # 窗口背景
    card: str           # 卡片（半透明材质视觉）
    border: str         # 发丝线
    divider: str        # 分割线
    input_bg: str       # 输入区
    track: str          # 进度轨道
    text: str
    text2: str
    text3: str
    accent: str
    accent_hover: str
    accent_press: str
    accent_soft: str
    accent_soft_hover: str
    hover_card: str     # 卡片上的悬浮层
    hover_bg: str       # 背景上的悬浮层
    danger: str
    danger_soft: str
    row_alt: str        # 表格斑马纹
    status: dict[str, str]
    # ---- 几何令牌（连续圆角体系，按方案统一下发）----
    radius_card: int = 18       # 卡片圆角
    radius_control: int = -1    # 控件圆角；-1 表示全圆角胶囊
    radius_track: float = 3.0   # 进度条圆角
    radius_icon: int = 10       # 品牌图标圆角
    accent_contrast: str = "#FFFFFF"   # 主色之上的文字/符号色
    zebra: bool = True          # 结果表是否使用斑马纹


def _make_palette(
    scheme: str, dark: bool, *,
    bg: str, card: str,
    text: str, text2: str, text3: str,
    accent: str, status: dict[str, str],
    accent_contrast: str = "#FFFFFF",
    input_bg: Optional[str] = None,
    row_alt: Optional[str] = None,
    radius_card: int = 18, radius_control: int = -1,
    radius_track: float = 3.0, radius_icon: int = 10,
    zebra: bool = True, border_t: float = 0.14,
) -> Palette:
    danger = "#FF453A" if dark else "#FF3B30"
    # 语义统一：以下均为“基底色（card/bg）混入少量 text 压暗”，
    # mix(base, toward, t) 表示从 base 向 toward 走 t
    return Palette(
        name="深色" if dark else "浅色",
        scheme=scheme,
        dark=dark,
        bg=bg,
        card=card,
        border=mix(card, text, border_t),
        divider=mix(card, text, 0.08),
        input_bg=input_bg or ("#FFFFFF" if not dark else blend("#FFFFFF", bg, 0.08)),
        track=mix(card, text, 0.09),
        text=text, text2=text2, text3=text3,
        accent=accent,
        accent_hover=mix(accent, "#FFFFFF", 0.16),
        accent_press=mix(accent, "#000000", 0.14),
        accent_soft=blend(accent, card, 0.12),
        accent_soft_hover=blend(accent, card, 0.20),
        hover_card=mix(card, text, 0.05),
        hover_bg=mix(bg, text, 0.06),
        danger=danger,
        danger_soft=blend(danger, card, 0.10),
        row_alt=row_alt or (card if not zebra else mix(card, text, 0.028)),
        status=status,
        radius_card=radius_card,
        radius_control=radius_control,
        radius_track=radius_track,
        radius_icon=radius_icon,
        accent_contrast=accent_contrast,
        zebra=zebra,
    )


# ---- 方案 A：Liquid 液态玻璃（对齐 macOS / iOS 26）----

def _liquid_palette(dark: bool) -> Palette:
    if not dark:
        return _make_palette(
            "liquid", False,
            bg="#F2F2F7",
            card=blend("#FFFFFF", "#F2F2F7", 0.68),
            text="#1C1C1E", text2="#6E6E73", text3="#AEAEB4",
            accent="#0A84FF",
            status={
                "pending": "#8E8E93", "fetching": "#32ADE6",
                "downloading": "#0A84FF", "paused": "#FF9F0A",
                "completed": "#30B55A", "failed": "#FF3B30",
                "cancelled": "#8E8E93",
            },
            radius_card=18, radius_icon=10,
        )
    return _make_palette(
        "liquid", True,
        bg="#17171C",
        card=blend("#2C2C2E", "#17171C", 0.55),
        text="#F2F2F7", text2="#98989D", text3="#6A6A72",
        accent="#0A84FF",
        status={
            "pending": "#98989D", "fetching": "#64D2FF",
            "downloading": "#0A84FF", "paused": "#FFD60A",
            "completed": "#30D158", "failed": "#FF453A",
            "cancelled": "#98989D",
        },
        radius_card=18, radius_icon=10,
    )


# ---- 方案 B：Mono 单色极简（对齐专业创作工具）----

def _mono_palette(dark: bool) -> Palette:
    if not dark:
        return _make_palette(
            "mono", False,
            bg="#F6F6F4",
            card="#FFFFFF",
            text="#1D1D1F", text2="#6E6E73", text3="#A2A2A0",
            accent="#1D1D1F", accent_contrast="#FFFFFF",
            status={
                "pending": "#8E8E93", "fetching": "#6A8CA8",
                "downloading": "#3A3A3C", "paused": "#C7831C",
                "completed": "#3D7A52", "failed": "#D14B42",
                "cancelled": "#8E8E93",
            },
            radius_card=10, radius_control=8, radius_track=2.0,
            radius_icon=8, zebra=False, border_t=0.18,
        )
    return _make_palette(
        "mono", True,
        bg="#101010",
        card="#1C1C1E",
        text="#ECECEE", text2="#9A9AA0", text3="#5E5E64",
        accent="#ECECEC", accent_contrast="#111112",
        input_bg=blend("#FFFFFF", "#101010", 0.07),
        status={
            "pending": "#9A9AA0", "fetching": "#7FA9C6",
            "downloading": "#D8D8DE", "paused": "#D9A344",
            "completed": "#4E9C68", "failed": "#E06B60",
            "cancelled": "#9A9AA0",
        },
        radius_card=10, radius_control=8, radius_track=2.0,
        radius_icon=8, zebra=False, border_t=0.18,
    )


# ---- 方案 C：Aurora 极光柔彩（对齐多彩消费硬件）----

def _aurora_palette(dark: bool) -> Palette:
    if not dark:
        bg, accent = "#F4F1FB", "#7C5CFF"
        card = blend("#FFFFFF", bg, 0.72)
        return _make_palette(
            "aurora", False,
            bg=bg, card=card,
            text="#221E2E", text2="#6E6878", text3="#ABA5B8",
            accent=accent,
            status={
                "pending": "#9A94A8", "fetching": "#2FB5C9",
                "downloading": accent, "paused": "#FF9F0A",
                "completed": "#2EAD6B", "failed": "#FF4D4F",
                "cancelled": "#9A94A8",
            },
            row_alt=blend(accent, card, 0.05),
            radius_card=22, radius_track=3.5, radius_icon=11,
        )
    bg, accent = "#151220", "#A084FF"
    card = blend("#2A2440", bg, 0.60)
    return _make_palette(
        "aurora", True,
        bg=bg, card=card,
        text="#F1EEF9", text2="#A79FBA", text3="#6E6680",
        accent=accent,
        status={
            "pending": "#8E87A0", "fetching": "#5AD0E6",
            "downloading": accent, "paused": "#FFD60A",
            "completed": "#38D07A", "failed": "#FF5A60",
            "cancelled": "#8E87A0",
        },
        row_alt=blend(accent, card, 0.07),
        radius_card=22, radius_track=3.5, radius_icon=11,
    )


# key → 展示名 / 明暗调色板
SCHEMES: dict[str, dict[str, Any]] = {
    "liquid": {"name": "液态玻璃 Liquid", "light": _liquid_palette(False), "dark": _liquid_palette(True)},
    "mono":   {"name": "单色极简 Mono",   "light": _mono_palette(False),   "dark": _mono_palette(True)},
    "aurora": {"name": "极光柔彩 Aurora", "light": _aurora_palette(False), "dark": _aurora_palette(True)},
}

THEME_MODES = (("auto", "自动（跟随系统）"), ("light", "浅色"), ("dark", "深色"))

PAL: Palette = SCHEMES["liquid"]["light"]
"""当前生效的调色板（全局）"""


def load_settings() -> dict[str, Any]:
    """读取界面偏好（设计方案 / 外观模式）"""
    data = dict(DEFAULT_SETTINGS)
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                if saved.get("scheme") in SCHEMES:
                    data["scheme"] = saved["scheme"]
                if saved.get("theme_mode") in ("auto", "light", "dark"):
                    data["theme_mode"] = saved["theme_mode"]
    except Exception:
        pass
    return data


def save_settings(data: dict[str, Any]) -> None:
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

_palette_aware: list[Callable[[Palette], None]] = []


def register_palette_aware(cb: Callable[[Palette], None]) -> None:
    """注册主题变更回调（widget 重绘）"""
    _palette_aware.append(cb)


def apply_palette(p: Palette) -> None:
    global PAL
    PAL = p
    for cb in _palette_aware:
        try:
            cb(p)
        except tk.TclError:
            pass


def system_prefers_dark() -> bool:
    """探测系统外观是否深色"""
    try:
        if sys.platform == "darwin":
            out = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True, text=True, timeout=2,
            )
            return out.stdout.strip() == "Dark"
        if sys.platform == "win32":
            import winreg  # type: ignore
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            return bool(winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0)
        out = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
            capture_output=True, text=True, timeout=2,
        )
        return "dark" in out.stdout
    except Exception:
        return False


# ==================== 基础组件 ====================


class Card:
    """圆角卡片容器：Canvas 绘制 squircle 底 + 内嵌内容 Frame。"""

    def __init__(
        self, parent: tk.Misc, *, radius: Optional[int] = None,
        pad_x: int = 14, pad_y: int = 12,
    ):
        self.radius = radius if radius is not None else PAL.radius_card
        self.pad_x = pad_x
        self.pad_y = pad_y
        self.fill = PAL.card
        self.border = PAL.border

        self.canvas = tk.Canvas(parent, highlightthickness=0, bd=0, bg=PAL.bg)
        self.inner = tk.Frame(self.canvas, bg=self.fill)
        self.win_id = self.canvas.create_window(
            pad_x, pad_y, window=self.inner, anchor="nw",
        )
        self.inner.bind("<Configure>", self._on_inner_resize)
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        register_palette_aware(self.set_palette)

    def _on_inner_resize(self, event: tk.Event) -> None:
        # 只跟随 inner 的【请求】高度；实际高度会被画布反向约束，
        # 直接用 event.height 会形成「收缩→再请求更小」的连锁反应
        req_h = self.inner.winfo_reqheight()
        if req_h != getattr(self, "_last_req_h", None):
            self._last_req_h = req_h
            self.canvas.configure(height=req_h + 2 * self.pad_y)

    def _on_canvas_resize(self, event: tk.Event) -> None:
        self._draw()

    def _draw(self) -> None:
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        self.canvas.delete("card")
        if w > 2 and h > 2:
            pts = _squircle_points(0.75, 0.75, w - 0.75, h - 0.75, self.radius)
            self.canvas.create_polygon(
                pts, fill=self.fill, outline=self.border, tags="card",
            )
            self.canvas.tag_lower("card")
        # inner 始终约束在画布可视区内：小窗不裁切、大窗填满弹性区
        self.canvas.itemconfig(
            self.win_id,
            width=max(w - 2 * self.pad_x, 1),
            height=max(h - 2 * self.pad_y, 1),
        )

    def set_palette(self, p: Palette) -> None:
        self.fill = p.card
        self.border = p.border
        self.radius = p.radius_card
        self.canvas.configure(bg=p.bg)
        self.inner.configure(bg=p.card)
        self._draw()

    # 几何代理
    def grid(self, **kw: Any) -> None:
        self.canvas.grid(**kw)

    def pack(self, **kw: Any) -> None:
        self.canvas.pack(**kw)

    def grid_rowconfigure(self, *a: Any, **kw: Any) -> None:
        self.inner.grid_rowconfigure(*a, **kw)

    def grid_columnconfigure(self, *a: Any, **kw: Any) -> None:
        self.inner.grid_columnconfigure(*a, **kw)


class PillButton(tk.Canvas):
    """胶囊按钮：squircle 全圆角，悬停/按压渐变过渡。

    kind: accent（主）/ tinted（浅主色）/ ghost（透明）/ field（输入区样式）/ danger（危险）
    """

    HEIGHT = {"accent": 34, "tinted": 32, "ghost": 30, "field": 32, "danger": 30}

    def __init__(
        self, parent: tk.Misc, text: str = "",
        command: Optional[Callable[[], None]] = None,
        kind: str = "ghost", width: Optional[int] = None,
        size: int = 10, bold: bool = False, on_card: bool = False,
        glyph: str = "", glyph_pos: str = "leading",
    ):
        self._text = text
        self._command = command
        self._kind = kind
        self._on_card = on_card
        self._glyph = glyph if glyph in GLYPHS else ""
        self._glyph_pos = glyph_pos if glyph_pos in ("leading", "trailing") else "leading"
        self._fnt = ui_font(size, bold=bold)
        self._height = self.HEIGHT.get(kind, 30)
        self._hover_t = 0.0
        self._pressed = False
        self._disabled = False

        super().__init__(
            parent, height=self._height, highlightthickness=0, bd=0,
            bg=self._base_bg(),
        )
        if width:
            self.configure(width=width)
        else:
            gap = 18 if self._glyph and self._glyph_pos == "leading" else 0
            self.configure(width=self._fnt.measure(text) + 36 + gap)

        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        register_palette_aware(self.set_palette)

    # ---- 状态 ----

    def _base_bg(self) -> str:
        return PAL.card if self._on_card else PAL.bg

    def set_state(self, state: str) -> None:
        self._disabled = state != "normal"
        if self._disabled:
            self._hover_t = 0.0
            self._pressed = False
        self._draw()

    def set_text(self, text: str) -> None:
        self._text = text
        self._draw()

    def set_command(self, command: Optional[Callable[[], None]]) -> None:
        self._command = command

    def set_palette(self, p: Palette) -> None:
        self.configure(bg=self._base_bg())
        self._draw()

    # ---- 交互 ----

    def _on_enter(self, _e: tk.Event) -> None:
        if self._disabled:
            return
        Animator(self).animate(
            f"hover-{id(self)}", self._hover_t, 1.0, 120,
            ease_out_cubic, lambda v: (setattr(self, "_hover_t", v), self._draw()),
        )

    def _on_leave(self, _e: tk.Event) -> None:
        Animator(self).animate(
            f"hover-{id(self)}", self._hover_t, 0.0, 140,
            ease_out_cubic, lambda v: (setattr(self, "_hover_t", v), self._draw()),
        )

    def _on_press(self, _e: tk.Event) -> None:
        if self._disabled:
            return
        self._pressed = True
        self._draw()

    def _on_release(self, _e: tk.Event) -> None:
        was_pressed = self._pressed
        self._pressed = False
        self._draw()
        if was_pressed and not self._disabled and self._command:
            self._command()

    # ---- 绘制 ----

    def _colors(self) -> tuple[str, str]:
        p = PAL
        t = self._hover_t
        if self._disabled:
            # ghost/field 类工具按钮禁用时只淡化，不出现填充灰块
            if self._kind in ("ghost", "field"):
                return self._base_bg(), p.text3
            return p.track, p.text3
        if self._kind == "accent":
            fill = mix(p.accent, p.accent_hover, t)
            if self._pressed:
                fill = p.accent_press
            return fill, p.accent_contrast
        if self._kind == "tinted":
            fill = mix(p.accent_soft, p.accent_soft_hover, t)
            return fill, p.accent
        if self._kind == "field":
            fill = p.input_bg
            if t:
                fill = mix(p.input_bg, p.text, 0.03 * t)
            return fill, p.text
        if self._kind == "danger":
            fill = mix(self._base_bg(), p.danger_soft, t)
            return fill, p.danger
        hover = p.hover_card if self._on_card else p.hover_bg
        return (mix(self._base_bg(), hover, t), p.text2)

    def _draw(self) -> None:
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= 2 or h <= 2:
            return
        fill, fg = self._colors()
        r = h / 2 if PAL.radius_control < 0 else min(PAL.radius_control, h / 2)
        pts = _squircle_points(0.5, 0.5, w - 0.5, h - 0.5, r)
        outline = PAL.border if self._kind == "field" and not self._disabled else ""
        self.create_polygon(pts, fill=fill, outline=outline)

        label = _truncate(self._text, self._fnt, w - 28)
        tw = self._fnt.measure(label)
        if self._glyph and self._glyph_pos == "leading":
            gw = 11
            group = gw + 5 + tw
            gx = w / 2 - group / 2 + gw / 2
            draw_glyph(self, self._glyph, gx, h / 2 + 0.5, fg, s=0.82)
            self.create_text(gx + gw / 2 + 5, h / 2, text=label, fill=fg,
                             font=self._fnt, anchor="w")
        elif self._glyph and self._glyph_pos == "trailing":
            self.create_text(w / 2, h / 2, text=label, fill=fg, font=self._fnt)
            draw_glyph(self, self._glyph, w - 16, h / 2 + 0.5,
                       PAL.text3 if not self._disabled else fg, s=0.8)
        else:
            self.create_text(w / 2, h / 2, text=label, fill=fg, font=self._fnt)


class IconButton(tk.Canvas):
    """圆形图标按钮：统一单色符号库（暂停/播放/关闭/外观）。"""

    def __init__(
        self, parent: tk.Misc, glyph: str = "close",
        command: Optional[Callable[[], None]] = None,
        size: int = 28, on_card: bool = False,
    ):
        self._glyph = glyph if glyph in GLYPHS else "close"
        self._command = command
        self._on_card = on_card
        self._size = size
        self._hover_t = 0.0
        self._pressed = False
        self._disabled = False
        self._visible = True

        super().__init__(
            parent, width=size, height=size,
            highlightthickness=0, bd=0, bg=self._base_bg(),
        )
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        register_palette_aware(self.set_palette)

    def _base_bg(self) -> str:
        return PAL.card if self._on_card else PAL.bg

    def set_state(self, state: str) -> None:
        self._disabled = state != "normal"
        self._hover_t = 0.0
        self._draw()

    def set_glyph(self, glyph: str) -> None:
        if glyph in GLYPHS:
            self._glyph = glyph
            self._draw()

    def set_visible(self, visible: bool) -> None:
        self._visible = visible
        self._draw()

    def set_palette(self, p: Palette) -> None:
        self.configure(bg=self._base_bg())
        self._draw()

    def _on_enter(self, _e: tk.Event) -> None:
        if self._disabled:
            return
        Animator(self).animate(
            f"hover-{id(self)}", self._hover_t, 1.0, 110,
            ease_out_cubic, lambda v: (setattr(self, "_hover_t", v), self._draw()),
        )

    def _on_leave(self, _e: tk.Event) -> None:
        Animator(self).animate(
            f"hover-{id(self)}", self._hover_t, 0.0, 130,
            ease_out_cubic, lambda v: (setattr(self, "_hover_t", v), self._draw()),
        )

    def _on_press(self, _e: tk.Event) -> None:
        if self._disabled:
            return
        self._pressed = True
        self._draw()

    def _on_release(self, _e: tk.Event) -> None:
        was = self._pressed
        self._pressed = False
        self._draw()
        if was and not self._disabled and self._command:
            self._command()

    def _draw(self) -> None:
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= 2 or h <= 2:
            return
        p = PAL
        cx, cy, r = w / 2, h / 2, w / 2 - 4

        fg = p.text3 if self._disabled else p.text2
        hover = p.hover_card if self._on_card else p.hover_bg
        if self._pressed:
            hover = mix(hover, p.text, 0.06)
        self.create_oval(
            cx - r, cy - r, cx + r, cy + r,
            fill=mix(self._base_bg(), hover, self._hover_t),
            outline="",
        )

        if not self._visible:
            return

        draw_glyph(self, self._glyph, cx, cy, fg, s=self._size / 30.0 * 1.05)


class Field(tk.Canvas):
    """圆角输入框：squircle 底 + 无边框 Entry + 占位符 + 焦点光环。"""

    def __init__(
        self, parent: tk.Misc, placeholder: str = "", text: str = "",
        on_return: Optional[Callable[[], None]] = None,
        trailing: bool = False,
        on_trailing: Optional[Callable[[], None]] = None,
        on_card: bool = False,
        size: int = 11,
    ):
        self.placeholder = placeholder
        self._on_return = on_return
        self._trailing = trailing
        self._on_trailing = on_trailing
        self._on_card = on_card
        self._ph_active = False
        self._focused = False
        self._focus_t = 0.0

        super().__init__(
            parent, height=34, highlightthickness=0, bd=0,
            bg=PAL.card if on_card else PAL.bg,
        )
        self.var = tk.StringVar(value=text)
        self.entry = tk.Entry(
            self, textvariable=self.var, relief=tk.FLAT, bd=0,
            highlightthickness=0, font=ui_font(size),
            bg=PAL.input_bg, fg=PAL.text, insertbackground=PAL.text,
        )
        self._win = self.create_window(12, 17, window=self.entry, anchor="w")

        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<FocusOut>", self._on_focus_out)
        if on_return:
            self.entry.bind("<Return>", lambda e: on_return())
        self.bind("<Configure>", self._draw)
        self.bind("<Button-1>", self._on_canvas_click)
        register_palette_aware(self.set_palette)
        self._init_placeholder()

    # ---- 值 ----

    def get(self) -> str:
        return "" if self._ph_active else self.var.get()

    def set(self, value: str) -> None:
        self._ph_active = False
        self.var.set(value)
        self.entry.configure(fg=PAL.text)
        self._draw()

    # ---- 占位符 ----

    def _init_placeholder(self) -> None:
        if not self.var.get() and self.placeholder:
            self._ph_active = True
            self.var.set(self.placeholder)
            self.entry.configure(fg=PAL.text3)

    def _on_focus_in(self, _e: tk.Event) -> None:
        self._focused = True
        if self._ph_active:
            self._ph_active = False
            self.var.set("")
            self.entry.configure(fg=PAL.text)
        Animator(self).animate(
            f"focus-{id(self)}", self._focus_t, 1.0, 140,
            ease_out_cubic, lambda v: (setattr(self, "_focus_t", v), self._draw()),
        )

    def _on_focus_out(self, _e: tk.Event) -> None:
        self._focused = False
        if not self.var.get() and self.placeholder:
            self._ph_active = True
            self.var.set(self.placeholder)
            self.entry.configure(fg=PAL.text3)
        Animator(self).animate(
            f"focus-{id(self)}", self._focus_t, 0.0, 160,
            ease_out_cubic, lambda v: (setattr(self, "_focus_t", v), self._draw()),
        )

    def _on_canvas_click(self, event: tk.Event) -> None:
        if self._trailing and event.x > self.winfo_width() - 26:
            if self._on_trailing:
                self._on_trailing()
            return
        self.entry.focus_set()

    # ---- 绘制 ----

    def set_palette(self, p: Palette) -> None:
        self.configure(bg=p.card if self._on_card else p.bg)
        self.entry.configure(
            bg=p.input_bg,
            fg=p.text3 if self._ph_active else p.text,
            insertbackground=p.text,
        )
        self._draw()

    def _draw(self, _e: Optional[tk.Event] = None) -> None:
        # 只删除自绘外观（chrome），绝不能 delete("all")：
        # 内嵌 Entry 是 window item，delete all 会将其一并卸载（Tk 9.0 实测）
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= 2 or h <= 2:
            return
        self.delete("chrome")
        p = PAL
        entry_w = w - 24 - (18 if self._trailing else 0)
        self.itemconfig(self._win, width=max(entry_w, 10))

        border = p.border
        if self._focus_t > 0:
            border = mix(p.border, p.accent, self._focus_t)
        r = h / 2 if p.radius_control < 0 else min(p.radius_control, h / 2)
        pts = _squircle_points(0.5, 0.5, w - 0.5, h - 0.5, r)
        self.create_polygon(pts, fill=p.input_bg, outline=border, tags="chrome")
        self.tag_lower("chrome")
        if self._trailing:
            existed = set(self.find_all())
            draw_glyph(self, "chevron", w - 15, h / 2 + 1.5, p.text3, s=0.85)
            for item in self.find_all():
                if item not in existed:
                    self.addtag_withtag("chrome", item)


class Select(PillButton):
    """下拉选择：胶囊按钮 + 原生弹出菜单。"""

    def __init__(
        self, parent: tk.Misc, values: Optional[list[str]] = None,
        value: str = "全部", on_change: Optional[Callable[[str], None]] = None,
        width: int = 132, on_card: bool = False, size: int = 10,
    ):
        self._values = list(values or [])
        self._value = value
        self._on_change = on_change
        self._menu: Optional[tk.Menu] = None
        super().__init__(
            parent, text="", kind="field", width=width,
            on_card=on_card, size=size,
            glyph="chevron", glyph_pos="trailing",
        )
        self.bind("<Button-1>", self._popup)
        self._refresh_text()

    def _refresh_text(self) -> None:
        self.set_text(self._value)

    def _popup(self, event: tk.Event) -> None:
        if self._disabled:
            return
        p = PAL
        menu = tk.Menu(
            self, tearoff=0, bd=0, relief=tk.FLAT,
            bg=p.card, fg=p.text,
            activebackground=p.accent_soft, activeforeground=p.text,
            font=ui_font(10),
        )
        self._menu_var = tk.StringVar(value=self._value)
        for v in self._values:
            menu.add_radiobutton(
                label=v, variable=self._menu_var, value=v,
                command=lambda v=v: self._choose(v),
            )
        self._menu = menu
        try:
            menu.tk_popup(
                self.winfo_rootx(), self.winfo_rooty() + self.winfo_height() + 3,
            )
        finally:
            menu.grab_release()
            self._pressed = False
            self._draw()

    def _choose(self, value: str) -> None:
        self._value = value
        self._refresh_text()
        if self._on_change:
            self._on_change(value)

    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        self._value = value
        self._refresh_text()

    def set_values(self, values: list[str]) -> None:
        self._values = list(values)
        if self._value not in self._values:
            self._value = self._values[0] if self._values else ""
            self._refresh_text()


class StatusDot(tk.Canvas):
    """状态指示点：状态栏左侧小圆点。"""

    KINDS = {"ok": 0, "busy": 1, "warn": 2, "err": 3, "info": 4}

    def __init__(self, parent: tk.Misc, on_card: bool = False):
        self._kind = "info"
        self._on_card = on_card
        super().__init__(
            parent, width=18, height=18, highlightthickness=0, bd=0,
            bg=PAL.card if on_card else PAL.bg,
        )
        register_palette_aware(self.set_palette)
        self._draw()

    def set_kind(self, kind: str) -> None:
        self._kind = kind
        self._draw()

    def set_palette(self, p: Palette) -> None:
        self.configure(bg=p.card if self._on_card else p.bg)
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        p = PAL
        color = {
            "ok": p.status["completed"], "busy": p.accent,
            "warn": p.status["paused"], "err": p.status["failed"],
            "info": p.text3,
        }.get(self._kind, p.text3)
        self.create_oval(5, 5, 13, 13, fill=color, outline="")


# ==================== 下载任务行 ====================


class TaskRow(tk.Canvas):
    """任务面板中的一行：状态点 + 歌名 + 状态文字 + 圆角进度条 + 图标按钮。"""

    ROW_H = TASK_ROW_HEIGHT

    def __init__(
        self, parent: tk.Misc, task: DownloadTask,
        on_pause_resume: Callable[[DownloadTask], None],
        on_cancel: Callable[[DownloadTask], None],
    ):
        self.task = task
        self._on_pause_resume = on_pause_resume
        self._on_cancel = on_cancel

        self._status = "pending"
        self._fade_t = 0.0
        self._hover_t = 0.0
        self._bar_value = 0.0
        self._indet_after: Optional[str] = None
        self._phase = 0.0

        super().__init__(
            parent, height=self.ROW_H, highlightthickness=0, bd=0,
            bg=PAL.card,
        )
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        register_palette_aware(self.set_palette)

        Animator(self).animate(
            f"fade-{id(self)}", 0.0, 1.0, 180,
            ease_out_cubic, lambda v: (setattr(self, "_fade_t", v), self._draw()),
        )

    # ---- 状态 ----

    def set_palette(self, p: Palette) -> None:
        self.configure(bg=p.card)
        self._draw()

    def update_from_task(self) -> None:
        task = self.task
        self._status = task.status.value

        if self._status == "fetching":
            self._ensure_indeterminate()
        else:
            self._stop_indeterminate()

        if self._status == "downloading":
            self._animate_bar(task.progress_pct)
        elif self._status == "paused":
            self._animate_bar(task.progress_pct)
        elif self._status == "completed":
            self._animate_bar(100.0)
        elif self._status == "pending":
            self._animate_bar(0.0)
        else:
            self._animate_bar(self._bar_value)
        self._draw()

    def _animate_bar(self, target: float) -> None:
        if abs(target - self._bar_value) < 0.4:
            self._bar_value = target
            self._draw()
            return
        Animator(self).animate(
            f"bar-{id(self)}", self._bar_value, target, 200,
            ease_out_cubic, lambda v: (setattr(self, "_bar_value", v), self._draw()),
        )

    def _ensure_indeterminate(self) -> None:
        if self._indet_after is not None:
            return

        def loop() -> None:
            if self._status != "fetching":
                self._indet_after = None
                return
            self._phase = (self._phase + 0.10) % (2 * math.pi)
            self._draw()
            self._indet_after = self.after(30, loop)

        self._indet_after = self.after(0, loop)

    def _stop_indeterminate(self) -> None:
        if self._indet_after is not None:
            try:
                self.after_cancel(self._indet_after)
            except Exception:
                pass
            self._indet_after = None

    # ---- 交互 ----

    def _on_enter(self, _e: tk.Event) -> None:
        Animator(self).animate(
            f"hover-{id(self)}", self._hover_t, 1.0, 120,
            ease_out_cubic, lambda v: (setattr(self, "_hover_t", v), self._draw()),
        )

    def _on_leave(self, _e: tk.Event) -> None:
        Animator(self).animate(
            f"hover-{id(self)}", self._hover_t, 0.0, 140,
            ease_out_cubic, lambda v: (setattr(self, "_hover_t", v), self._draw()),
        )

    def _on_click(self, event: tk.Event) -> None:
        w = self.winfo_width()
        x, y = event.x, event.y
        cy = self.ROW_H / 2
        cancel_cx = w - 16 - 14
        pause_cx = cancel_cx - 32
        if self._cancel_visible() and (x - cancel_cx) ** 2 + (y - cy) ** 2 <= 16 ** 2:
            self._on_cancel(self.task)
            return
        if self._pause_visible() and (x - pause_cx) ** 2 + (y - cy) ** 2 <= 16 ** 2:
            self._on_pause_resume(self.task)
            return

    def _pause_visible(self) -> bool:
        return self._status in ("downloading", "paused")

    def _cancel_visible(self) -> bool:
        return self._status not in ("completed", "failed", "cancelled")

    # ---- 绘制 ----

    def _status_text(self) -> str:
        task = self.task
        if self._status == "pending":
            return "等待中"
        if self._status == "fetching":
            return "获取链接"
        if self._status == "downloading":
            return f"{task.progress_pct:.0f}%"
        if self._status == "paused":
            return f"{task.progress_pct:.0f}%"
        if self._status == "completed":
            return format_size(task.total_size)
        if self._status == "failed":
            return "失败"
        if self._status == "cancelled":
            return "已取消"
        return ""

    def _draw(self) -> None:
        self.delete("all")
        w = self.winfo_width()
        h = self.ROW_H
        if w <= 2:
            return
        p = PAL
        fade = self._fade_t
        status_color = p.status.get(self._status, p.text3)

        # 背景（悬停层 + 淡入）
        row_bg = mix(p.card, p.hover_card, self._hover_t)
        bg = mix(p.card, row_bg, fade)
        self.create_rectangle(0, 0, w, h, fill=bg, outline="")

        # 状态点
        dot = mix(p.card, status_color, 0.25 + 0.75 * fade)
        self.create_oval(14, 16, 24, 26, fill=dot, outline="")

        # 歌名
        name = f"{self.task.artist} - {self.task.title}"
        right_reserved = 128 if self._pause_visible() or self._cancel_visible() else 76
        name_w = max(w - 36 - right_reserved, 40)
        name_fg = p.text if self._status not in ("completed", "cancelled") else p.text2
        name_fg = mix(p.card, name_fg, fade)
        self.create_text(
            34, 17, text=_truncate(name, ui_font(10), name_w),
            fill=name_fg, font=ui_font(10), anchor="w",
        )

        # 状态文字
        st = self._status_text()
        st_fg = mix(p.card, status_color, 0.4 + 0.6 * fade)
        st_x = w - 16 - (66 if (self._pause_visible() or self._cancel_visible()) else 0)
        self.create_text(
            st_x, 17, text=st, fill=st_fg, font=ui_font(9), anchor="e",
        )

        # 进度条
        bar_x0, bar_x1, bar_y = 34, w - 16, 40
        bar_w = bar_x1 - bar_x0
        br = p.radius_track
        track_pts = _squircle_points(bar_x0, bar_y, bar_x1, bar_y + 5, br)
        self.create_polygon(track_pts, fill=p.track, outline="")

        if self._status == "fetching":
            seg = bar_w * 0.36
            x = ((math.sin(self._phase) + 1) / 2) * (bar_w - seg)
            fill_pts = _squircle_points(
                bar_x0 + x, bar_y, bar_x0 + x + seg, bar_y + 5, br,
            )
            self.create_polygon(fill_pts, fill=status_color, outline="")
        else:
            fill_w = bar_w * (self._bar_value / 100.0)
            if fill_w > 1.5:
                fill_pts = _squircle_points(
                    bar_x0, bar_y, bar_x0 + fill_w, bar_y + 5, br,
                )
                self.create_polygon(fill_pts, fill=status_color, outline="")

        # 图标按钮（统一符号）
        cy = h / 2
        if self._cancel_visible():
            cx = w - 16 - 14
            self._draw_icon_bg(cx, cy, p)
            draw_glyph(self, "close", cx, cy, p.text3, s=0.9)
        if self._pause_visible():
            cx = w - 16 - 14 - 32
            self._draw_icon_bg(cx, cy, p)
            glyph = "play" if self._status == "paused" else "pause"
            draw_glyph(self, glyph, cx, cy, p.text2, s=0.9)

    def _draw_icon_bg(self, cx: float, cy: float, p: Palette) -> None:
        self.create_oval(
            cx - 12, cy - 12, cx + 12, cy + 12,
            fill=mix(p.card, p.hover_card, self._hover_t), outline="",
        )

    def destroy_row(self) -> None:
        self._stop_indeterminate()
        self.destroy()


# ==================== 历史管理 ====================


class SearchHistory:
    """搜索历史管理类（持久化到 JSON 文件）"""

    def __init__(self, history_file: str = "search_history.json", max_items: int = 20):
        self.history_file = history_file
        self.max_items = max_items
        self.history: list[str] = self._load_history()

    def _load_history(self) -> list[str]:
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
            except Exception:
                pass
        return []

    def _save_history(self) -> None:
        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def add(self, keyword: str) -> None:
        if not keyword or not keyword.strip():
            return
        keyword = keyword.strip()
        if keyword in self.history:
            self.history.remove(keyword)
        self.history.insert(0, keyword)
        if len(self.history) > self.max_items:
            self.history = self.history[:self.max_items]
        self._save_history()

    def get_all(self) -> list[str]:
        return self.history.copy()

    def clear(self) -> None:
        self.history = []
        self._save_history()


class ArtistHistory:
    """歌手历史管理类（持久化到 artist_history.json）"""

    def __init__(self, history_file: str = "artist_history.json", max_items: int = 50):
        self.history_file = history_file
        self.max_items = max_items
        self.history: list[str] = self._load_history()

    def _load_history(self) -> list[str]:
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
            except Exception:
                pass
        return []

    def _save_history(self) -> None:
        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def add(self, artist: str) -> None:
        if not artist or not artist.strip():
            return
        artist = artist.strip()
        if artist in self.history:
            self.history.remove(artist)
        self.history.insert(0, artist)
        if len(self.history) > self.max_items:
            self.history = self.history[:self.max_items]
        self._save_history()

    def get_all(self) -> list[str]:
        return self.history.copy()

    def clear(self) -> None:
        self.history = []
        self._save_history()


# ==================== 主 GUI 类 ====================


class MusicDownloaderGUI:
    """音乐下载器图形界面 v3.1 — 多方案自适应设计系统"""

    def __init__(self, root: tk.Tk, demo: bool = False):
        self.root = root
        self.demo = demo
        self.root.title(APP_TITLE + (" · 设计预览" if demo else ""))
        self.root.geometry(f"{WIN_WIDTH}x{WIN_HEIGHT}")
        self.root.resizable(True, True)
        self.root.minsize(MIN_WIDTH, MIN_HEIGHT)

        # 用户偏好：设计方案 + 外观模式（auto / light / dark）
        self.settings = load_settings()
        self.scheme_key: str = self.settings["scheme"]
        self.theme_mode: str = self.settings["theme_mode"]
        self._detected_dark = system_prefers_dark()
        apply_palette(self._active_palette())

        self.search_results: list[dict[str, Any]] = []
        self.filtered_results: list[dict[str, Any]] = []

        self.search_history = SearchHistory()
        self.artist_history = ArtistHistory()

        self.download_dir: str = ensure_download_dir(DEFAULT_DOWNLOAD_DIR)

        self._queue: Optional[DownloadQueue] = None
        self._task_rows: dict[str, TaskRow] = {}
        self._queue_running: bool = False

        self._setup_theme()
        self._setup_ui()
        self._apply_palette_to_static()

        self.root.bind("<FocusIn>", self._on_window_focus)
        self._set_status("准备就绪", "info")

        if demo:
            self._seed_demo()

    def _active_palette(self) -> Palette:
        """根据方案 + 外观模式（环境探测或手动指定）取生效调色板"""
        dark = self._detected_dark if self.theme_mode == "auto" else self.theme_mode == "dark"
        return SCHEMES[self.scheme_key]["dark" if dark else "light"]

    def _theme_glyph(self) -> str:
        return {"auto": "half", "light": "sun", "dark": "moon"}[self.theme_mode]

    # ---- 主题 ----

    def _setup_theme(self) -> None:
        style = ttk.Style(self.root)
        self.style = style
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

    def _apply_palette_to_static(self) -> None:
        p = PAL
        style = self.style

        style.configure(
            "Treeview", font=ui_font(10), rowheight=32,
            background=p.card, fieldbackground=p.card,
            foreground=p.text, borderwidth=0, relief=tk.FLAT,
            bordercolor=p.card, lightcolor=p.card, darkcolor=p.card,
            insertcolor=p.text,
        )
        style.configure(
            "Treeview.Heading", font=ui_font(10),
            background=p.card, foreground=p.text2,
            relief=tk.FLAT, borderwidth=0, padding=(8, 8),
            bordercolor=p.card, lightcolor=p.card, darkcolor=p.card,
        )
        style.map(
            "Treeview",
            background=[("selected", p.accent)],
            foreground=[("selected", p.accent_contrast)],
        )
        # 表头悬浮/按压不出现凸起浮雕
        style.map(
            "Treeview.Heading",
            relief=[("active", tk.FLAT), ("pressed", tk.FLAT)],
            background=[("active", p.card), ("pressed", p.card)],
            foreground=[("active", p.text), ("pressed", p.text)],
        )
        style.configure(
            "Vertical.TScrollbar",
            troughcolor=p.card, background=p.track,
            bordercolor=p.card, darkcolor=p.card, lightcolor=p.card,
            arrowcolor=p.card, troughbordercolor=p.card,
            gripcount=0, relief=tk.FLAT, borderwidth=0,
            width=10, arrowsize=0,
        )
        style.map(
            "Vertical.TScrollbar",
            background=[("active", p.text3), ("pressed", p.text2)],
            arrowcolor=[("active", p.card), ("pressed", p.card)],
        )
        self.tree.tag_configure("even", background=p.card)
        self.tree.tag_configure("odd", background=p.row_alt)
        if self._count_lbl is not None:
            self._count_lbl.configure(fg=p.text2)
        if self._hint_lbl is not None:
            self._hint_lbl.configure(fg=p.text3)

    def _apply_palette(self) -> None:
        p = PAL
        self.root.configure(bg=p.bg)
        self.main.configure(bg=p.bg)
        self.header.configure(bg=p.bg)
        self.action_row.configure(bg=p.bg)
        self.status_row.configure(bg=p.bg)

        # 顶部
        self._icon_canvas.configure(bg=p.bg)
        self._draw_header_icon()
        self.title_lbl.configure(bg=p.bg, fg=p.text)
        self.subtitle_lbl.configure(bg=p.bg, fg=p.text3)
        self.version_lbl.configure(bg=p.bg, fg=p.text3)

        # 控制卡 / 任务卡 / 日志卡静态元素
        for w in (self._ctrl_lbl1, self._ctrl_lbl2, self._ctrl_lbl3):
            w.configure(bg=p.card, fg=p.text2)
        self._filter_row.configure(bg=p.card)
        self._filter_spacer.configure(bg=p.card)
        self._ctrl_div.configure(bg=p.divider)
        self._result_head.configure(bg=p.card)
        self._result_title_lbl.configure(bg=p.card, fg=p.text)
        self._task_head.configure(bg=p.card)
        self._task_head_lbl.configure(bg=p.card, fg=p.text)
        self._log_head.configure(bg=p.card)
        self._log_title_lbl.configure(bg=p.card, fg=p.text)
        self._log_body.configure(bg=p.card)

        # 状态与任务区
        self.status_lbl.configure(bg=p.bg, fg=p.text2)
        self._status_dot.set_palette(p)
        self._rows_holder.configure(bg=p.card)
        if self._empty_lbl is not None:
            self._empty_lbl.configure(bg=p.card, fg=p.text3)
        self._task_canvas.configure(bg=p.card)
        self.log_text.configure(bg=p.card, fg=p.text2, insertbackground=p.text2)

        self._apply_palette_to_static()
        apply_palette(p)  # 通知全部注册组件重绘

    def set_theme_mode(self, mode: str) -> None:
        self.theme_mode = mode
        self.settings["theme_mode"] = mode
        save_settings(self.settings)
        self._refresh_theme()

    def set_scheme(self, key: str) -> None:
        if key not in SCHEMES or key == self.scheme_key:
            return
        self.scheme_key = key
        self.settings["scheme"] = key
        save_settings(self.settings)
        self._refresh_theme()
        self._log(f"设计方案已切换: {SCHEMES[key]['name']}")

    def _refresh_theme(self) -> None:
        if self.theme_mode == "auto":
            self._detected_dark = system_prefers_dark()
        apply_palette(self._active_palette())
        self._apply_palette()
        self.theme_btn.set_glyph(self._theme_glyph())

    def _on_window_focus(self, _e: tk.Event) -> None:
        if self.theme_mode == "auto":
            dark = system_prefers_dark()
            if dark != self._detected_dark:
                self._detected_dark = dark
                self._refresh_theme()

    def _show_theme_menu(self) -> None:
        p = PAL
        menu = tk.Menu(
            self.root, tearoff=0, bd=0, relief=tk.FLAT,
            bg=p.card, fg=p.text,
            activebackground=p.accent_soft, activeforeground=p.text,
            font=ui_font(10),
        )
        # 段一：设计方案
        menu.add_command(label="设计方案", state=tk.DISABLED)
        scheme_var = tk.StringVar(value=self.scheme_key)
        for key, meta in SCHEMES.items():
            menu.add_radiobutton(
                label="  " + meta["name"], variable=scheme_var, value=key,
                command=lambda k=key: self.set_scheme(k),
            )
        menu.add_separator()
        # 段二：外观模式（环境自适应 / 手动覆盖）
        menu.add_command(label="外观模式", state=tk.DISABLED)
        mode_var = tk.StringVar(value=self.theme_mode)
        for mode, label in THEME_MODES:
            menu.add_radiobutton(
                label="  " + label, variable=mode_var, value=mode,
                command=lambda m=mode: self.set_theme_mode(m),
            )
        self._theme_menu = menu
        try:
            menu.tk_popup(
                self.theme_btn.winfo_rootx(),
                self.theme_btn.winfo_rooty() + self.theme_btn.winfo_height() + 3,
            )
        finally:
            menu.grab_release()

    # ---- UI 构建 ----

    def _setup_ui(self) -> None:
        self.main = tk.Frame(self.root, bg=PAL.bg)
        self.main.grid(row=0, column=0, sticky="nsew", padx=18, pady=14)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.main.columnconfigure(0, weight=1)
        self.main.rowconfigure(3, weight=5)   # 结果
        self.main.rowconfigure(5, weight=3)   # 任务

        # === 0. 顶部（标题 + 外观切换）===
        self.header = tk.Frame(self.main, bg=PAL.bg)
        self.header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.header.columnconfigure(1, weight=1)

        self._icon_canvas = tk.Canvas(
            self.header, width=34, height=34, highlightthickness=0, bd=0,
            bg=PAL.bg,
        )
        self._icon_canvas.grid(row=0, column=0, padx=(2, 10))
        self._draw_header_icon()

        title_box = tk.Frame(self.header, bg=PAL.bg)
        title_box.grid(row=0, column=1, sticky="w")
        self.title_lbl = tk.Label(
            title_box, text=APP_TITLE, bg=PAL.bg, fg=PAL.text,
            font=ui_font(15, bold=True),
        )
        self.title_lbl.pack(anchor="w")
        self.subtitle_lbl = tk.Label(
            title_box, text=APP_SUBTITLE, bg=PAL.bg, fg=PAL.text3,
            font=ui_font(9),
        )
        self.subtitle_lbl.pack(anchor="w")

        self.version_lbl = tk.Label(
            self.header, text=APP_VERSION, bg=PAL.bg, fg=PAL.text3,
            font=ui_font(9),
        )
        self.version_lbl.grid(row=0, column=2, padx=(0, 8), sticky="e")

        self.theme_btn = IconButton(
            self.header, glyph=self._theme_glyph(),
            command=self._show_theme_menu, size=30,
        )
        self.theme_btn.grid(row=0, column=3, sticky="e")

        # === 1. 搜索卡 ===
        search_card = Card(self.main)
        search_card.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        search_card.inner.columnconfigure(0, weight=1)

        self.search_field = Field(
            search_card.inner, placeholder="搜索歌曲、歌手…",
            on_return=self._on_search, trailing=True,
            on_trailing=self._show_search_history_menu, on_card=True,
        )
        self.search_field.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        self.search_btn = PillButton(
            search_card.inner, text="搜索", command=self._on_search,
            kind="accent", on_card=True, bold=True, width=104,
            glyph="search",
        )
        self.search_btn.grid(row=0, column=1, sticky="e")

        # === 2. 目录 + 筛选卡 ===
        ctrl_card = Card(self.main)
        ctrl_card.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        ctrl_card.inner.columnconfigure(1, weight=1)

        self._ctrl_lbl1 = tk.Label(
            ctrl_card.inner, text="目录", bg=PAL.card, fg=PAL.text2,
            font=ui_font(10),
        )
        self._ctrl_lbl1.grid(row=0, column=0, sticky="w", padx=(2, 8))
        self.path_field = Field(
            ctrl_card.inner, text=self.download_dir,
            on_return=self._on_dir_changed, on_card=True, size=10,
        )
        self.path_field.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self.browse_btn = PillButton(
            ctrl_card.inner, text="浏览", command=self._browse_dir,
            kind="ghost", on_card=True, glyph="folder",
        )
        self.browse_btn.grid(row=0, column=2)

        self._ctrl_div = tk.Frame(ctrl_card.inner, bg=PAL.divider, height=1)
        self._ctrl_div.grid(row=1, column=0, columnspan=3, sticky="ew", pady=9)

        # 筛选行：独立 Frame，避免与目录行的网格权重互相干扰
        filter_row = tk.Frame(ctrl_card.inner, bg=PAL.card)
        filter_row.grid(row=2, column=0, columnspan=3, sticky="ew")
        self._filter_row = filter_row

        self._ctrl_lbl2 = tk.Label(
            filter_row, text="歌手", bg=PAL.card, fg=PAL.text2,
            font=ui_font(10),
        )
        self._ctrl_lbl2.pack(side=tk.LEFT, padx=(2, 8))
        self.artist_filter = Select(
            filter_row, values=["全部"] + self.artist_history.get_all(),
            value="全部", on_change=self._on_artist_select,
            on_card=True, width=132,
        )
        self.artist_filter.pack(side=tk.LEFT)

        self._ctrl_lbl3 = tk.Label(
            filter_row, text="平台", bg=PAL.card, fg=PAL.text2,
            font=ui_font(10),
        )
        self._ctrl_lbl3.pack(side=tk.LEFT, padx=(16, 8))
        self.source_filter = Select(
            filter_row, values=["全部"] + list(PLATFORM_NAMES),
            value="全部", on_change=self._on_filter_change,
            on_card=True, width=132,
        )
        self.source_filter.pack(side=tk.LEFT)

        self._filter_spacer = tk.Frame(filter_row, bg=PAL.card)
        self._filter_spacer.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.clear_filter_btn = PillButton(
            filter_row, text="清除筛选", command=self._clear_filter,
            kind="ghost", on_card=True, size=9,
        )
        self.clear_filter_btn.pack(side=tk.LEFT)

        # === 3. 搜索结果卡 ===
        results_card = Card(self.main, pad_x=10, pad_y=8)
        results_card.grid(row=3, column=0, sticky="nsew", pady=(0, 10))
        results_card.inner.columnconfigure(0, weight=1)
        results_card.inner.rowconfigure(1, weight=1)

        result_head = tk.Frame(results_card.inner, bg=PAL.card)
        result_head.grid(row=0, column=0, sticky="ew", pady=(2, 6))
        result_head.columnconfigure(1, weight=1)
        self._result_head = result_head
        self._result_title_lbl = tk.Label(
            result_head, text="搜索结果", bg=PAL.card, fg=PAL.text,
            font=ui_font(11, bold=True),
        )
        self._result_title_lbl.grid(row=0, column=0, sticky="w")
        self._count_lbl = tk.Label(
            result_head, text="", bg=PAL.card, fg=PAL.text2, font=ui_font(9),
        )
        self._count_lbl.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self._hint_lbl = tk.Label(
            result_head, text="⌘/Ctrl 多选 · 双击下载", bg=PAL.card,
            fg=PAL.text3, font=ui_font(9),
        )
        self._hint_lbl.grid(row=0, column=2, sticky="e")

        columns = ("index", "title", "artist", "source", "quality")
        self.tree = ttk.Treeview(
            results_card.inner, columns=columns, show="headings",
            height=10, selectmode="extended",
        )
        self.tree.heading("index", text="序号")
        self.tree.heading("title", text="歌曲名")
        self.tree.heading("artist", text="歌手")
        self.tree.heading("source", text="来源")
        self.tree.heading("quality", text="音质")
        self.tree.column("index", width=52, anchor=tk.CENTER)
        self.tree.column("title", width=300)
        self.tree.column("artist", width=180)
        self.tree.column("source", width=110)
        self.tree.column("quality", width=76, anchor=tk.CENTER)

        tree_scroll = ttk.Scrollbar(
            results_card.inner, orient=tk.VERTICAL, style="Vertical.TScrollbar",
            command=self.tree.yview,
        )
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.grid(row=1, column=0, sticky="nsew")
        tree_scroll.grid(row=1, column=1, sticky="ns")
        self.tree.bind("<Double-1>", lambda e: self._on_download_selected())

        # === 4. 操作行 ===
        self.action_row = tk.Frame(self.main, bg=PAL.bg)
        self.action_row.grid(row=4, column=0, sticky="ew", pady=(0, 10))
        self.action_row.columnconfigure(5, weight=1)

        self.download_sel_btn = PillButton(
            self.action_row, text="下载选中", command=self._on_download_selected,
            kind="accent", bold=True, width=124, glyph="download",
        )
        self.download_sel_btn.grid(row=0, column=0, padx=(0, 8))
        self.download_sel_btn.set_state("disabled")

        self.download_all_btn = PillButton(
            self.action_row, text="全部下载", command=self._on_download_all,
            kind="tinted", width=124, glyph="download",
        )
        self.download_all_btn.grid(row=0, column=1, padx=(0, 8))
        self.download_all_btn.set_state("disabled")

        self.open_dir_btn = PillButton(
            self.action_row, text="打开目录", command=self._open_download_dir,
            kind="ghost", glyph="folder",
        )
        self.open_dir_btn.grid(row=0, column=2, padx=(0, 8))

        self.clear_results_btn = PillButton(
            self.action_row, text="清空结果", command=self._clear_results,
            kind="ghost", glyph="trash",
        )
        self.clear_results_btn.grid(row=0, column=3, padx=(0, 8))

        self.clear_history_btn = PillButton(
            self.action_row, text="清空历史", command=self._clear_history,
            kind="ghost", glyph="clock",
        )
        self.clear_history_btn.grid(row=0, column=4, padx=(0, 0))

        # === 5. 下载任务卡 ===
        tasks_card = Card(self.main, pad_x=10, pad_y=8)
        tasks_card.grid(row=5, column=0, sticky="nsew", pady=(0, 10))
        tasks_card.inner.columnconfigure(0, weight=1)
        tasks_card.inner.rowconfigure(1, weight=1)

        task_head = tk.Frame(tasks_card.inner, bg=PAL.card)
        task_head.grid(row=0, column=0, sticky="ew", pady=(2, 6))
        task_head.columnconfigure(0, weight=1)
        self._task_head = task_head
        self._task_head_lbl = tk.Label(
            task_head, text="下载任务", bg=PAL.card, fg=PAL.text,
            font=ui_font(11, bold=True),
        )
        self._task_head_lbl.grid(row=0, column=0, sticky="w")

        self.pause_all_btn = PillButton(
            task_head, text="暂停全部", command=self._pause_all_tasks,
            kind="ghost", on_card=True, size=9,
        )
        self.pause_all_btn.grid(row=0, column=1, padx=(0, 4))
        self.pause_all_btn.set_state("disabled")

        self.cancel_all_btn = PillButton(
            task_head, text="取消全部", command=self._cancel_all_tasks,
            kind="ghost", on_card=True, size=9,
        )
        self.cancel_all_btn.grid(row=0, column=2, padx=(0, 4))
        self.cancel_all_btn.set_state("disabled")

        self.clear_done_btn = PillButton(
            task_head, text="清除已完成", command=self._clear_completed_tasks,
            kind="ghost", on_card=True, size=9,
        )
        self.clear_done_btn.grid(row=0, column=3)
        self.clear_done_btn.set_state("disabled")

        # 可滚动任务区
        self._task_canvas = tk.Canvas(
            tasks_card.inner, height=MAX_TASK_PANEL_HEIGHT,
            highlightthickness=0, bd=0, bg=PAL.card,
        )
        self._task_canvas.grid(row=1, column=0, sticky="nsew")

        task_scroll = ttk.Scrollbar(
            tasks_card.inner, orient=tk.VERTICAL, style="Vertical.TScrollbar",
            command=self._task_canvas.yview,
        )
        task_scroll.grid(row=1, column=1, sticky="ns")
        self._task_canvas.configure(yscrollcommand=task_scroll.set)

        self._rows_holder = tk.Frame(self._task_canvas, bg=PAL.card)
        self._task_canvas_window = self._task_canvas.create_window(
            (0, 0), window=self._rows_holder, anchor="nw",
        )
        self._rows_holder.bind("<Configure>", self._on_holder_configure)
        self._task_canvas.bind("<Configure>", self._on_task_canvas_configure)
        self._task_canvas.bind("<Enter>", self._bind_mousewheel)
        self._task_canvas.bind("<Leave>", self._unbind_mousewheel)

        self._empty_lbl = tk.Label(
            self._rows_holder, text="暂无下载任务", bg=PAL.card, fg=PAL.text3,
            font=ui_font(10),
        )
        self._empty_lbl.pack(pady=18)

        # === 6. 状态行 ===
        self.status_row = tk.Frame(self.main, bg=PAL.bg)
        self.status_row.grid(row=6, column=0, sticky="ew", pady=(0, 6))
        self._status_dot = StatusDot(self.status_row)
        self._status_dot.pack(side=tk.LEFT, padx=(2, 6))
        self.status_lbl = tk.Label(
            self.status_row, text="", bg=PAL.bg, fg=PAL.text2,
            font=ui_font(9),
        )
        self.status_lbl.pack(side=tk.LEFT)

        # === 7. 日志卡 ===
        log_card = Card(self.main, pad_x=10, pad_y=8)
        log_card.grid(row=7, column=0, sticky="ew")
        log_card.inner.columnconfigure(0, weight=1)
        log_card.inner.rowconfigure(1, weight=1)

        log_head = tk.Frame(log_card.inner, bg=PAL.card)
        log_head.grid(row=0, column=0, sticky="ew", pady=(2, 4))
        self._log_head = log_head
        self._log_title_lbl = tk.Label(
            log_head, text="日志", bg=PAL.card, fg=PAL.text,
            font=ui_font(11, bold=True),
        )
        self._log_title_lbl.pack(side=tk.LEFT)

        log_body = tk.Frame(log_card.inner, bg=PAL.card)
        log_body.grid(row=1, column=0, sticky="nsew")
        self._log_body = log_body
        log_body.columnconfigure(0, weight=1)
        log_body.rowconfigure(0, weight=1)

        self.log_text = tk.Text(
            log_body, height=4, wrap=tk.WORD, state=tk.DISABLED,
            font=mono_font(10), bg=PAL.card, fg=PAL.text2,
            relief=tk.FLAT, highlightthickness=0, borderwidth=0,
            insertbackground=PAL.text2,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(
            log_body, orient=tk.VERTICAL, style="Vertical.TScrollbar",
            command=self.log_text.yview,
        )
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)

    def _draw_header_icon(self) -> None:
        p = PAL
        self._icon_canvas.delete("all")
        w = 34
        pts = _squircle_points(1, 1, w - 1, w - 1, p.radius_icon)
        self._icon_canvas.create_polygon(
            pts, fill=p.accent,
            outline=mix(p.accent, p.accent_contrast, 0.25),
        )
        draw_glyph(
            self._icon_canvas, "note", w / 2, w / 2 + 1,
            p.accent_contrast, s=1.05,
        )

    # ---- Canvas 滚动适配 ----

    def _on_holder_configure(self, _e: tk.Event) -> None:
        self._task_canvas.configure(scrollregion=self._task_canvas.bbox("all"))

    def _on_task_canvas_configure(self, event: tk.Event) -> None:
        self._task_canvas.itemconfig(
            self._task_canvas_window, width=event.width,
        )

    def _bind_mousewheel(self, _e: tk.Event) -> None:
        self._task_canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self._task_canvas.bind_all("<Button-4>", self._on_mousewheel)
        self._task_canvas.bind_all("<Button-5>", self._on_mousewheel)

    def _unbind_mousewheel(self, _e: tk.Event) -> None:
        self._task_canvas.unbind_all("<MouseWheel>")
        self._task_canvas.unbind_all("<Button-4>")
        self._task_canvas.unbind_all("<Button-5>")

    def _on_mousewheel(self, event: tk.Event) -> None:
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            delta = -1 * (event.delta / 120)
        self._task_canvas.yview_scroll(int(delta), "units")

    # ---- 状态与日志 ----

    def _set_status(self, text: str, kind: str = "info") -> None:
        self.status_lbl.configure(text=text)
        self._status_dot.set_kind(kind)

    def _log(self, message: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    # ---- 设计预览（--demo，供 UX 测试，不写历史文件）----

    def _seed_demo(self) -> None:
        demo_songs = [
            ("晴天", "周杰伦", "咪咕音乐", "320K"),
            ("晴天", "周杰伦", "网易云音乐", "LOSSLESS"),
            ("晴天", "周杰伦", "QQ音乐", "320K"),
            ("富士山下", "陈奕迅", "网易云音乐", "LOSSLESS"),
            ("江南", "林俊杰", "QQ音乐", "320K"),
            ("光年之外", "G.E.M. 邓紫棋", "酷我音乐", "LOSSLESS"),
            ("起风了", "买辣椒也用券", "咪咕音乐", "320K"),
            ("夜曲", "周杰伦", "酷我音乐", "320K"),
        ]
        self.search_results = [
            {"title": t, "artist": a, "source_name": s, "quality": q}
            for t, a, s, q in demo_songs
        ]
        self.filtered_results = list(self.search_results)
        self._populate_tree(self.search_results)
        self.artist_filter.set_values(
            ["全部"] + sorted({s[1] for s in demo_songs})
        )
        self.source_filter.set_values(["全部"] + list(PLATFORM_NAMES))
        self.download_sel_btn.set_state("normal")
        self.download_all_btn.set_state("normal")

        demo_tasks = [
            ("晴天", "周杰伦", "咪咕音乐", "320K",
             TaskStatus.DOWNLOADING, 8_400_000, 5_800_000),
            ("富士山下", "陈奕迅", "网易云音乐", "LOSSLESS",
             TaskStatus.FETCHING, 0, 0),
            ("江南", "林俊杰", "QQ音乐", "320K",
             TaskStatus.PAUSED, 5_200_000, 1_560_000),
            ("光年之外", "G.E.M. 邓紫棋", "酷我音乐", "LOSSLESS",
             TaskStatus.COMPLETED, 26_300_000, 26_300_000),
        ]
        for i, (title, artist, source, quality, status, total, done) in enumerate(demo_tasks):
            task = DownloadTask(
                task_id=f"demo-{i}", title=title, artist=artist,
                source=source, quality=quality,
                audio_url="https://example.invalid/demo.mp3",
            )
            task.status = status
            task.total_size = total
            task.downloaded = done
            self._add_task_row(task)

        self._set_status("设计预览：演示数据已载入（搜索/下载不会真正发起）", "info")
        self._log("已进入设计预览模式")
        self._log(f"当前方案: {SCHEMES[self.scheme_key]['name']} · "
                  f"外观: {dict(THEME_MODES)[self.theme_mode]}")
        self._log("点击右上角圆形按钮可切换 3 套设计方案与浅色/深色外观")

    # ---- 搜索历史 / 目录 ----

    def _show_search_history_menu(self) -> None:
        history = self.search_history.get_all()
        if not history:
            self._log("暂无搜索历史")
            return
        p = PAL
        menu = tk.Menu(
            self.root, tearoff=0, bd=0, relief=tk.FLAT,
            bg=p.card, fg=p.text,
            activebackground=p.accent_soft, activeforeground=p.text,
            font=ui_font(10),
        )
        for item in history:
            menu.add_command(
                label=item,
                command=lambda k=item: self._apply_history_keyword(k),
            )
        menu.add_separator()
        menu.add_command(label="清空历史", command=self._clear_history)
        self._history_menu = menu
        try:
            menu.tk_popup(
                self.search_field.winfo_rootx(),
                self.search_field.winfo_rooty() + self.search_field.winfo_height() + 3,
            )
        finally:
            menu.grab_release()

    def _apply_history_keyword(self, keyword: str) -> None:
        self.search_field.set(keyword)
        self._on_search()

    def _browse_dir(self) -> None:
        dir_path = filedialog.askdirectory(initialdir=self.download_dir)
        if dir_path:
            self.download_dir = dir_path
            self.path_field.set(dir_path)
            self._log(f"下载目录已切换: {dir_path}")

    def _on_dir_changed(self) -> None:
        new_dir = self.path_field.get().strip()
        if new_dir and os.path.isdir(new_dir):
            self.download_dir = new_dir
            self._log(f"下载目录已切换: {new_dir}")
        elif new_dir:
            try:
                self.download_dir = ensure_download_dir(new_dir)
                self.path_field.set(self.download_dir)
                self._log(f"下载目录已创建: {self.download_dir}")
            except Exception as e:
                self._log(f"无法创建目录: {e}")
                self.path_field.set(self.download_dir)

    def _open_download_dir(self) -> None:
        if os.path.exists(self.download_dir):
            subprocess.run(["open", self.download_dir])

    def _clear_history(self) -> None:
        self.search_history.clear()
        messagebox.showinfo("提示", "搜索历史已清空")

    # ---- 筛选 ----

    def _on_artist_select(self, value: str) -> None:
        if not value or value == "全部":
            self._on_filter_change("全部")
            return
        current_artists = {
            song.get("artist", "") or song.get("singer", "")
            for song in self.search_results
        }
        if value in current_artists:
            self._on_filter_change(self.source_filter.get())
        else:
            self._log(f"选择历史歌手: {value}，按歌手搜索")
            self.search_field.set(value)
            self._on_search()

    def _update_filter_options(self) -> None:
        artists: set[str] = set(self.artist_history.get_all())
        for song in self.search_results:
            artist = song.get("artist", "") or song.get("singer", "")
            if artist:
                self.artist_history.add(artist)
                artists.add(artist)

        artist_values = ["全部"] + sorted(artists)
        source_values = ["全部"] + list(PLATFORM_NAMES)
        self.artist_filter.set_values(artist_values)
        self.source_filter.set_values(source_values)

    def _on_filter_change(self, _value: Optional[str] = None) -> None:
        artist_filter = self.artist_filter.get()
        source_filter = self.source_filter.get()

        self.filtered_results = []
        for song in self.search_results:
            if artist_filter != "全部":
                artist = song.get("artist", "") or song.get("singer", "")
                if artist_filter not in artist:
                    continue
            if source_filter != "全部":
                if source_filter != song.get("source_name", ""):
                    continue
            self.filtered_results.append(song)

        self._populate_tree(self.filtered_results)
        self._set_status(f"筛选结果: {len(self.filtered_results)} 首歌曲")

    def _clear_filter(self) -> None:
        self.artist_filter.set("全部")
        self.source_filter.set("全部")
        self.filtered_results = self.search_results.copy()
        self._on_filter_change()

    def _clear_results(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.search_results = []
        self.filtered_results = []
        self._count_lbl.configure(text="")
        self.download_sel_btn.set_state("disabled")
        self.download_all_btn.set_state("disabled")
        self._set_status("准备就绪", "info")

    # ---- 搜索 ----

    def _on_search(self) -> None:
        keyword = self.search_field.get().strip()
        if not keyword:
            messagebox.showwarning("提示", "请输入要搜索的歌曲名")
            return

        self.search_history.add(keyword)
        self.search_btn.set_state("disabled")
        self._clear_results()
        self._log(f"正在搜索: {keyword}")
        self._set_status("正在搜索…", "busy")

        threading.Thread(
            target=self._search_thread, args=(keyword,), daemon=True,
        ).start()

    def _search_thread(self, keyword: str) -> None:
        try:
            results = search_all_platforms(keyword)
            self.search_results = results
            self.filtered_results = results.copy()

            if results:
                self.root.after(0, self._populate_tree, results)
                self.root.after(0, self._update_filter_options)
                self.root.after(
                    0, lambda: self._set_status(f"找到 {len(results)} 首歌曲", "ok"),
                )
                self.root.after(0, self.download_sel_btn.set_state, "normal")
                self.root.after(0, self.download_all_btn.set_state, "normal")
                self._log(f"搜索完成: 共 {len(results)} 首歌曲（四平台交错排列）")
            else:
                self._log("未找到相关歌曲，请更换关键词")
                self.root.after(
                    0, lambda: self._set_status("未找到相关歌曲", "warn"),
                )
        except Exception as e:
            self._log(f"搜索出错: {e}")
            self.root.after(0, lambda: self._set_status("搜索出错", "err"))
        finally:
            self.root.after(0, self.search_btn.set_state, "normal")

    def _populate_tree(self, songs: list[dict[str, Any]]) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

        for idx, song in enumerate(songs, 1):
            title = song.get("title", "") or song.get("name", "")
            artist = song.get("artist", "") or song.get("singer", "")
            source = song.get("source_name", song.get("source", "?"))
            quality = song.get("quality", "?")

            self.tree.insert(
                "", tk.END, values=(idx, title, artist, source, quality),
                tags=("even",) if idx % 2 == 0 else ("odd",),
            )

        self._count_lbl.configure(text=f"{len(songs)} 首")

    # ---- 下载（加入队列）----

    def _on_download_selected(self) -> None:
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning("提示", "请先在表格中选择要下载的歌曲")
            return

        songs: list[dict[str, Any]] = []
        for item in selected_items:
            idx = int(self.tree.item(item, "values")[0]) - 1
            if 0 <= idx < len(self.filtered_results):
                songs.append(self.filtered_results[idx])

        if songs:
            self._add_songs_to_queue(songs)

    def _on_download_all(self) -> None:
        if not self.filtered_results:
            messagebox.showwarning("提示", "没有可下载的歌曲")
            return
        self._add_songs_to_queue(list(self.filtered_results))

    def _add_songs_to_queue(self, songs: list[dict[str, Any]]) -> None:
        if self._queue is None:
            self._queue = DownloadQueue(directory=self.download_dir)
            self._queue.on_progress = self._on_queue_progress
            self._queue.on_status_change = self._on_queue_status_change

        self._queue.directory = ensure_download_dir(self.download_dir)

        added = 0
        for song in songs:
            title = song.get("title", "") or song.get("name", "")
            artist = song.get("artist", "") or song.get("singer", "")
            source = song.get("source_name", song.get("source", "?"))
            quality = song.get("quality", "?")
            audio_url = song.get("audio_url", "")

            if not audio_url:
                detail = get_song_detail(song)
                if detail:
                    audio_url = detail.get("audio_url", "")
                    title = detail.get("title", title)
                    artist = detail.get("artist", artist)
                    quality = detail.get("quality", quality)

            if not audio_url:
                self._log(f"无法获取下载链接: {artist} - {title}")
                continue

            task = self._queue.add_task(
                title=title, artist=artist, audio_url=audio_url,
                quality=quality, source=source,
            )
            self._add_task_row(task)
            added += 1

        if added == 0:
            self._log("没有可下载的歌曲（无法获取链接）")
            return

        self._log(f"已添加 {added} 首到下载队列")
        self._update_queue_buttons()

        if not self._queue_running:
            self._queue_running = True
            self._queue.start_async()

    # ---- 任务面板 ----

    def _add_task_row(self, task: DownloadTask) -> None:
        if self._empty_lbl is not None:
            self._empty_lbl.pack_forget()

        row = TaskRow(
            self._rows_holder, task,
            on_pause_resume=self._on_task_pause_resume,
            on_cancel=self._on_task_cancel,
        )
        row.pack(fill=tk.X, pady=(0, 6))
        self._task_rows[task.task_id] = row
        row.update_from_task()

    def _find_task(self, task_id: str) -> Optional[DownloadTask]:
        if self._queue is None:
            return None
        for t in self._queue.tasks:
            if t.task_id == task_id:
                return t
        return None

    def _clear_all_task_rows(self) -> None:
        for row in self._task_rows.values():
            row.destroy_row()
        self._task_rows.clear()
        if self._empty_lbl is not None and not self._empty_lbl.winfo_ismapped():
            self._empty_lbl.pack(pady=18)

    # ---- 队列回调 ----

    def _on_queue_progress(self, task: DownloadTask) -> None:
        self.root.after(0, self._safe_update_task_row, task.task_id)

    def _on_queue_status_change(self, task: DownloadTask) -> None:
        self.root.after(0, self._safe_update_task_row, task.task_id)
        self.root.after(0, self._check_queue_done)

    def _safe_update_task_row(self, task_id: str) -> None:
        row = self._task_rows.get(task_id)
        if row is None:
            return
        task = self._find_task(task_id)
        if task is None:
            return
        row.update_from_task()

    def _check_queue_done(self) -> None:
        if self._queue is None:
            return
        active = sum(
            1 for t in self._queue.tasks
            if t.status.value in ("pending", "fetching", "downloading", "paused")
        )
        if active == 0:
            self._queue_running = False
            self._log("下载队列全部完成")
            self._set_status("下载队列全部完成", "ok")
        self._update_queue_buttons()

    def _update_queue_buttons(self) -> None:
        if self._queue is None or not self._task_rows:
            self.pause_all_btn.set_state("disabled")
            self.cancel_all_btn.set_state("disabled")
            self.clear_done_btn.set_state("disabled")
            return

        tasks = self._queue.tasks if self._queue else []
        has_active = any(t.status.value in ("fetching", "downloading") for t in tasks)
        has_paused = any(t.status.value == "paused" for t in tasks)
        has_done = any(
            t.status.value in ("completed", "failed", "cancelled") for t in tasks
        )

        self.pause_all_btn.set_state("normal" if (has_active or has_paused) else "disabled")
        self.cancel_all_btn.set_state("normal" if self._task_rows else "disabled")
        self.clear_done_btn.set_state("normal" if has_done else "disabled")

    # ---- 任务操作 ----

    def _on_task_pause_resume(self, task: DownloadTask) -> None:
        if task.status == TaskStatus.DOWNLOADING:
            task.pause()
            self._log(f"暂停: {task.display_name}")
        elif task.status == TaskStatus.PAUSED:
            task.resume_after_pause()
            self._log(f"恢复: {task.display_name}")

        self._safe_update_task_row(task.task_id)
        self._update_queue_buttons()

    def _on_task_cancel(self, task: DownloadTask) -> None:
        task.cancel()
        self._log(f"取消: {task.display_name}")
        self._safe_update_task_row(task.task_id)
        self._update_queue_buttons()

    def _pause_all_tasks(self) -> None:
        if self._queue is None:
            return
        paused = 0
        for t in self._queue.tasks:
            if t.status == TaskStatus.DOWNLOADING:
                t.pause()
                paused += 1
        self._log(f"已暂停 {paused} 个任务")
        self._refresh_task_panel()
        self._update_queue_buttons()

    def _cancel_all_tasks(self) -> None:
        if self._queue is None:
            return
        cancelled = 0
        for t in self._queue.tasks:
            if t.status.value not in ("completed", "failed", "cancelled"):
                t.cancel()
                cancelled += 1
        self._log(f"已取消 {cancelled} 个任务")
        self._refresh_task_panel()
        self._queue_running = False
        self._update_queue_buttons()

    def _refresh_task_panel(self) -> None:
        for task_id, row in list(self._task_rows.items()):
            task = self._find_task(task_id)
            if task:
                row.update_from_task()

    def _clear_completed_tasks(self) -> None:
        to_remove: list[str] = []
        for task_id, row in list(self._task_rows.items()):
            task = self._find_task(task_id)
            if task is None or task.status.value in ("completed", "failed", "cancelled"):
                row.destroy_row()
                to_remove.append(task_id)

        for task_id in to_remove:
            del self._task_rows[task_id]

        if self._queue:
            self._queue.clear_completed()

        if not self._task_rows and self._empty_lbl is not None:
            if not self._empty_lbl.winfo_ismapped():
                self._empty_lbl.pack(pady=18)

        self._log(f"已清除 {len(to_remove)} 个已完成任务")
        self._update_queue_buttons()


# ==================== 程序入口 ====================


def main() -> None:
    demo = "--demo" in sys.argv
    root = tk.Tk()
    app = MusicDownloaderGUI(root, demo=demo)
    root.mainloop()


if __name__ == "__main__":
    main()
