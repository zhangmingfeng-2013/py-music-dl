#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""设计系统：调色板、色彩运算与系统外观探测。

本模块是 GUI 的纯数据 / 纯函数部分，不依赖 Tkinter 或 PyQt：

* :class:`Palette` —— 冻结调色板，包含颜色与圆角/玻璃材质令牌；
* Liquid / Mono / Aurora 三套方案 × 明暗两种外观；
* :func:`palette_for` / :func:`glyph_for` —— 方案 + 外观模式 → 调色板 / 符号，
  两个前端共用同一套解析规则，避免各自复制映射表；
* :func:`system_prefers_dark` —— 探测操作系统外观（带缓存）；
* :class:`AppearanceWatcher` —— 后台线程监视系统外观变化，GUI 线程零阻塞；
* 色彩混合工具供 Tkinter 版绘制半透明材质复用。

Qt 版与 Tkinter 版共用同一份主题定义，避免两套界面视觉漂移。
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Final, Optional

# ---------------------------------------------------------------------------
# 色彩工具
# ---------------------------------------------------------------------------


def _rgb(hex_color: str) -> tuple[int, int, int]:
    """``#RRGGBB`` → ``(r, g, b)``。"""
    value = hex_color.lstrip("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def _hex(r: int, g: int, b: int) -> str:
    """``(r, g, b)`` → ``#RRGGBB``，分量自动钳制到 0–255。"""
    return (
        f"#{max(0, min(255, int(r))):02x}"
        f"{max(0, min(255, int(g))):02x}"
        f"{max(0, min(255, int(b))):02x}"
    )


def mix(first: str, second: str, ratio: float) -> str:
    """``first`` 向 ``second`` 混合 ``ratio``（0–1）。"""
    red_a, green_a, blue_a = _rgb(first)
    red_b, green_b, blue_b = _rgb(second)
    return _hex(
        red_a + (red_b - red_a) * ratio,
        green_a + (green_b - green_a) * ratio,
        blue_a + (blue_b - blue_a) * ratio,
    )


def blend(over: str, under: str, alpha: float) -> str:
    """把 ``over`` 以 ``alpha`` 透明度叠在 ``under`` 上。"""
    return mix(under, over, alpha)


# ---------------------------------------------------------------------------
# 调色板
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Palette:
    """一套完整的设计令牌。"""

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
    # ---- 液态玻璃材质令牌 ----
    glass: bool = False         # 是否启用玻璃质感（高光/光晕/材质叠层）
    glass_strength: float = 0.0  # 质感强度 0~1（liquid=1，aurora=0.65，mono=0）


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
    glass: bool = False, glass_strength: float = 0.0,
) -> Palette:
    """按语义令牌生成调色板，统一派生描边 / 悬浮 / 半透明主色。"""
    danger = "#FF453A" if dark else "#FF3B30"
    # 语义统一：以下均为「基底色（card/bg）混入少量 text 压暗」,
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
        glass=glass,
        glass_strength=glass_strength,
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
            glass=True, glass_strength=1.0,
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
        glass=True, glass_strength=1.0,
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
            glass=True, glass_strength=0.65,
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
        glass=True, glass_strength=0.65,
    )


#: key → 展示名 / 明暗调色板
SCHEMES: Final[dict[str, dict[str, Any]]] = {
    "liquid": {
        "name": "液态玻璃 Liquid",
        "light": _liquid_palette(False),
        "dark": _liquid_palette(True),
    },
    "mono": {
        "name": "单色极简 Mono",
        "light": _mono_palette(False),
        "dark": _mono_palette(True),
    },
    "aurora": {
        "name": "极光柔彩 Aurora",
        "light": _aurora_palette(False),
        "dark": _aurora_palette(True),
    },
}

#: 外观模式 key → 展示名（顺序即菜单顺序）
THEME_MODES: Final[tuple[tuple[str, str], ...]] = (
    ("auto", "自动（跟随系统）"),
    ("light", "浅色"),
    ("dark", "深色"),
)

#: 外观模式 key → 主题按钮符号名
THEME_GLYPHS: Final[dict[str, str]] = {
    "auto": "half", "light": "sun", "dark": "moon",
}

#: 合法的外观模式集合（含 "auto"）
THEME_MODE_KEYS: Final[frozenset[str]] = frozenset(key for key, _ in THEME_MODES)

#: 未知方案 key 的兜底方案
FALLBACK_SCHEME: Final = "liquid"


# ---------------------------------------------------------------------------
# 模式 → 调色板 / 符号（两个前端共用同一套解析规则）
# ---------------------------------------------------------------------------


def normalize_mode(theme_mode: str) -> str:
    """把任意输入收敛成合法外观模式；未知值按 ``auto`` 处理。"""
    return theme_mode if theme_mode in THEME_MODE_KEYS else "auto"


def resolve_dark(theme_mode: str, *, system_dark: Optional[bool] = None) -> bool:
    """按外观模式判定是否深色；``auto`` 时采用系统外观。"""
    mode = normalize_mode(theme_mode)
    if mode == "auto":
        if system_dark is None:
            system_dark = system_prefers_dark()
        return bool(system_dark)
    return mode == "dark"


def glyph_for(theme_mode: str) -> str:
    """外观模式对应的主题按钮符号名。"""
    return THEME_GLYPHS[normalize_mode(theme_mode)]


def mode_label(theme_mode: str) -> str:
    """外观模式的中文展示名。"""
    return dict(THEME_MODES)[normalize_mode(theme_mode)]


def palette_for(
    scheme: str, theme_mode: str = "auto", *,
    system_dark: Optional[bool] = None,
) -> Palette:
    """按方案 + 外观模式取生效调色板（未知方案回退 Liquid）。"""
    entry = SCHEMES.get(scheme) or SCHEMES[FALLBACK_SCHEME]
    dark = resolve_dark(theme_mode, system_dark=system_dark)
    pal = entry["dark" if dark else "light"]
    return pal


# ---------------------------------------------------------------------------
# 系统外观探测（带缓存 + 后台监视）
# ---------------------------------------------------------------------------

#: 缓存有效期（秒）：必须显著大于 :class:`AppearanceWatcher` 的轮询间隔，
#: 否则 GUI 线程每次查询都恰好落在过期边界，仍会同步拉起子进程
APPEARANCE_TTL: Final = 10.0

_lock = threading.Lock()
_cached_dark: Optional[bool] = None
_cached_at: float = 0.0


def _probe_system_dark() -> bool:
    """真正执行系统外观探测；可能阻塞（子进程超时 2 秒），不得在 GUI 线程频繁调用。"""
    try:
        if sys.platform == "darwin":
            result = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True, text=True, timeout=2, check=False,
            )
            return result.stdout.strip() == "Dark"
        if sys.platform == "win32":
            # winreg 仅 Windows 存在，macOS/Linux 静态检查误报
            import winreg  # type: ignore # pylint: disable=import-error

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            return bool(winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0)
        result = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
            capture_output=True, text=True, timeout=2, check=False,
        )
        return "dark" in result.stdout
    except Exception:  # noqa: BLE001  外观探测失败时回退浅色
        return False


def _store_appearance(dark: bool) -> None:
    """写入探测缓存（后台线程与主线程共用）。"""
    global _cached_dark, _cached_at  # pylint: disable=global-statement
    with _lock:
        _cached_dark = bool(dark)
        _cached_at = time.monotonic()


def cached_appearance() -> Optional[bool]:
    """读取缓存中的系统外观；从未探测或已过期时返回 ``None``（不阻塞）。"""
    with _lock:
        if _cached_dark is None or time.monotonic() - _cached_at >= APPEARANCE_TTL:
            return None
        return _cached_dark


def invalidate_appearance_cache() -> None:
    """丢弃缓存，下次查询重新探测（系统外观已变化、测试隔离时使用）。"""
    global _cached_dark, _cached_at  # pylint: disable=global-statement
    with _lock:
        _cached_dark = None
        _cached_at = 0.0


def system_prefers_dark(refresh: bool = False) -> bool:
    """探测系统外观是否为深色；探测失败按浅色处理。

    结果带 :data:`APPEARANCE_TTL` 秒缓存：焦点、菜单、重绘等高频查询
    直接命中缓存，不会反复拉起 ``defaults``/``gsettings`` 子进程。
    ``refresh=True`` 强制绕过缓存重新探测。
    """
    if not refresh:
        cached = cached_appearance()
        if cached is not None:
            return cached
    dark = _probe_system_dark()
    _store_appearance(dark)
    return dark


class AppearanceWatcher:
    """后台线程轮询系统外观，变化时回调。

    让 GUI 主线程不再为“系统外观是否变了”付出子进程开销：主线程只读缓存
    （:func:`cached_appearance`），昂贵探测全部落在守护线程里。

    ``on_change`` 在**后台线程**被调用，GUI 必须自行切回主线程
    （Tk 用 ``root.after``，Qt 用信号）。
    """

    def __init__(self, interval: float = 3.0, on_change=None) -> None:
        self.interval = max(0.5, float(interval))
        self._on_change = on_change
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._known: Optional[bool] = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """启动监视线程（重复调用无副作用）。"""
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="appearance-watcher", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """停止监视线程并等待其退出（最多一个轮询间隔）。"""
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=self.interval + 1.0)

    def _notify(self, dark: bool) -> None:
        if self._on_change is None:
            return
        try:
            self._on_change(dark)
        except Exception:  # noqa: BLE001  回调异常不得终止监视线程
            pass

    def _run(self) -> None:
        while not self._stop.is_set():
            dark = _probe_system_dark()
            _store_appearance(dark)
            if self._known is None:
                self._known = dark
            elif dark != self._known:
                self._known = dark
                self._notify(dark)
            self._stop.wait(self.interval)
