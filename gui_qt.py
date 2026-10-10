# -*- coding: utf-8 -*-

"""
音乐下载器 GUI（PyQt6 · pyglass-qt 液态玻璃版）
================================================

在保留原 tkinter 版（gui.py）全部核心功能的前提下，使用 pyglass-qt 框架对
界面进行全面改造，对齐 Apple Liquid Glass 设计语言：

  · 真折射玻璃面板 —— pyglass GlassRenderer：Snell 透镜边缘、色散、
    Fresnel 反射、磨砂散射（numpy 实现，跨平台）；
  · 环境光背景 —— 大尺度柔光光斑作为玻璃折射的"内容"；
  · 玻璃控件体系 —— 按钮 / 输入框 / 下拉 / 表格 / 进度条统一采用
    半透明填充 + 顶部高光（sheen）+ 边缘光晕（rim）绘制，
    悬停 / 按压 / 选中均有动效反馈；
  · 玻璃弹窗 —— 主题菜单 / 搜索历史 / 下拉选项 / 打赏弹窗均以
    带遮罩的折射玻璃 Overlay 呈现，支持展开动画与点击外部关闭。

功能面在原版基础上扩展：
  多平台并发搜索（咪咕/网易云/QQ/酷我）· 结果列表与筛选（歌手/平台/音质）
  · 音质后台识别与展示 · 伴奏/翻唱等版本标记 · 内置音频试听
  · 批量下载队列（进度/暂停/恢复/取消/单任务与全局限速/实时速度）
  · 下载目录与限速设置 · 搜索与歌手历史 · 3 套设计方案 × 自动/浅色/深色外观
  · 开发者打赏 · --demo 设计预览模式

启动：python3 gui_qt.py [--demo]
"""

from __future__ import annotations

from dataclasses import replace

import os
import subprocess
import sys
import threading
import time
import weakref
from typing import Any, Callable, Optional

from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt6.QtCore import (
    QEasingCurve, QEvent, QObject, QPoint, QPointF, QPropertyAnimation, QRectF,
    QSize, Qt, QThreadPool, QTimer, QUrl, QVariantAnimation, QRunnable,
    pyqtProperty, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QIcon, QImage, QLinearGradient,
    QPainter, QPainterPath, QPalette, QPen, QPixmap, QRadialGradient,
)
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QApplication, QCheckBox, QComboBox,
    QDialog, QFileDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QScrollArea, QSizePolicy, QSlider, QSpinBox, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

import numpy as np

from pyglass import (
    GlassMaterial, GlassRenderer, GlassStyle, WidgetBackdrop, paint_glass,
)

# 业务层与主题资产直接复用 tkinter 版实现（纯 Python，不依赖 Tk 运行时）
from gui import (  # noqa: E402
    SCHEMES, THEME_MODES, load_settings, save_settings, system_prefers_dark,
    SearchHistory, ArtistHistory, TipRecordStore,
    TIP_METHODS, TIP_QR_FILES,
)
from api import (  # noqa: E402
    PLATFORM_NAMES, detect_version_risk, fetch_lyrics, resolve_song,
    search_all_platforms, strip_lrc_timestamps,
)
from downloader import DownloadQueue, DownloadTask, RateLimiter, TaskStatus  # noqa: E402
from media import CONVERT_FLAC, CONVERT_MP3, CONVERT_OFF, MP3_BITRATES, PostOptions, ffmpeg_available  # noqa: E402
from utils import (  # noqa: E402
    DEFAULT_DOWNLOAD_DIR, default_download_dir, ensure_download_dir,
    format_speed, quality_tier, resource_path,
    TIER_HQ, TIER_LABELS, TIER_LOSSLESS, TIER_ORDER, TIER_STANDARD,
    TIER_UNKNOWN,
)

# ---- 常量（与原版一致）----

WIN_WIDTH, WIN_HEIGHT = 1040, 820
MIN_WIDTH, MIN_HEIGHT = 940, 680
TASK_ROW_HEIGHT = 54
MAX_TASK_PANEL_HEIGHT = 4 * TASK_ROW_HEIGHT

APP_TITLE = "拾音"
APP_VERSION = "v3.2 · Qt"
APP_SUBTITLE = "多平台聚合 · 咪咕 网易云 QQ音乐 酷我"


def app_icon_path() -> str:
    """图标文件路径。Windows 用多帧 ICO，其余平台用高清 PNG；缺失时返回空串。"""
    if sys.platform == "win32":
        path = resource_path("assets", "icons", "app.ico")
        if os.path.exists(path):
            return path
    path = resource_path("assets", "icons", "icon_512.png")
    if not os.path.exists(path):
        path = resource_path("assets", "icons", "icon_256.png")
    return path if os.path.exists(path) else ""


def app_icon() -> QIcon:
    """应用图标（窗口标题栏/任务栏/Dock）。"""
    path = app_icon_path()
    return QIcon(path) if path else QIcon()


def apply_macos_app_identity() -> None:
    """源码直跑时修正 macOS 应用身份，避免 Dock/菜单栏显示 "Python"。

    打包后的 Shiyin.app 自带 Info.plist，无需处理；仅解释器直跑场景生效。
    必须在创建 QApplication 之前调用——LaunchServices 在 NSApplication
    初始化时读取 CFBundleName/CFBundleDisplayName 注册进程显示名。
    """
    if sys.platform != "darwin" or getattr(sys, "frozen", False):
        return
    try:
        from AppKit import NSBundle  # pyobjc-framework-Cocoa
    except ImportError:
        return  # 未安装 pyobjc 时静默跳过，保持默认行为
    try:
        info = NSBundle.mainBundle().infoDictionary()
        if info is not None:
            info["CFBundleName"] = APP_TITLE
            info["CFBundleDisplayName"] = APP_TITLE
    except Exception:
        pass  # 身份修正为纯外观优化，失败不影响主流程


def apply_macos_dock_icon(icon_path: str) -> None:
    """源码直跑时显式设置 Dock 图标（Qt 一般会从 windowIcon 同步，此处兜底）。"""
    if sys.platform != "darwin" or getattr(sys, "frozen", False) or not icon_path:
        return
    try:
        from AppKit import NSApplication, NSImage  # pyobjc-framework-Cocoa
    except ImportError:
        return
    try:
        img = NSImage.alloc().initWithContentsOfFile_(icon_path)
        if img is not None:
            NSApplication.sharedApplication().setApplicationIconImage_(img)
    except Exception:
        pass  # 同上，纯外观优化


# 音质筛选项（标签 → 最低 tier；"全部" 不过滤）
QUALITY_FILTER_ALL = "全部"
QUALITY_FILTERS: list[tuple[str, str]] = [
    (QUALITY_FILTER_ALL, ""),
    ("标准及以上", TIER_STANDARD),
    ("高清及以上", TIER_HQ),
    ("仅无损", TIER_LOSSLESS),
]
# 详情预取并发数（免费接口，适度保守）
DETAIL_WORKERS = 4

UI_FONT = "PingFang SC"
MONO_FONT = "Menlo"  # macOS 通用等宽字体（SF Mono 不对第三方应用开放）

# 玻璃材质预设：内容面板（可读性优先）与弹窗（视觉优先）
PANEL_MATERIAL = GlassMaterial(thickness=0.5, frost=0.16, bevel=28)
DIALOG_MATERIAL = GlassMaterial(thickness=0.7, frost=0.10, bevel=56)
GLASS_STYLE = GlassStyle()
# 内嵌面板/弹窗面板均为子控件，paintEvent 被裁剪在自身矩形内：
# 默认外扩阴影会在四角被切成灰色直角块，故内嵌渲染一律关闭外扩阴影
# （面板间距与弹窗遮罩本身已提供层次分离）
EMBEDDED_STYLE = replace(GLASS_STYLE, shadow_layers=0)


# ==================== 颜色 / 绘制工具 ====================


def qc(hex_color: str, alpha: int = 255) -> QColor:
    """hex → QColor"""
    c = QColor(hex_color)
    c.setAlpha(alpha)
    return c


def mix_qc(a: QColor, b: QColor, t: float) -> QColor:
    """线性混色：a 向 b 走 t（0~1）"""
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
        round(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


def _rel_lum(c: QColor) -> float:
    """WCAG 相对亮度"""
    def lin(v: float) -> float:
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(c.red()) + 0.7152 * lin(c.green()) + 0.0722 * lin(c.blue())


def contrast_ratio(a: QColor, b: QColor) -> float:
    """WCAG 对比度（1~21）"""
    l1, l2 = sorted((_rel_lum(a), _rel_lum(b)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def wcag_safe_palette(pal):
    """深色方案下将 text3 提亮至对 card 背景 ≥4.5:1（WCAG AA 正文标准）。

    SCHEMES 中的 Palette 为共享缓存对象且 frozen，此处按需返回 replace 副本，
    不影响 tkinter 版与其它方案的既有视觉层次。
    """
    if not pal.dark:
        return pal
    card = qc(pal.card)
    fg = qc(pal.text3)
    if contrast_ratio(fg, card) >= 4.5:
        return pal
    for i in range(1, 16):
        cand = mix_qc(fg, QColor(255, 255, 255), i / 15)
        if contrast_ratio(cand, card) >= 4.5:
            return replace(pal, text3=cand.name())
    return replace(pal, text3=pal.text2)


def sync_app_palette(pal, theme_mode: str = "dark") -> None:
    """把主题配色同步到应用级 QPalette。

    QSS 只覆盖自绘控件；QMessageBox、原生弹层、禁用态等走 QPalette 渲染，
    不设置会在深色模式下回退为系统浅色（白底）。
    """
    app = QApplication.instance()
    if app is None:
        return
    qp = QPalette()
    qp.setColor(QPalette.ColorRole.Window, qc(pal.bg))
    qp.setColor(QPalette.ColorRole.WindowText, qc(pal.text))
    qp.setColor(QPalette.ColorRole.Base, qc(pal.input_bg))
    qp.setColor(QPalette.ColorRole.AlternateBase, qc(pal.card))
    qp.setColor(QPalette.ColorRole.Text, qc(pal.text))
    qp.setColor(QPalette.ColorRole.Button, qc(pal.card))
    qp.setColor(QPalette.ColorRole.ButtonText, qc(pal.text))
    qp.setColor(QPalette.ColorRole.ToolTipBase, qc(pal.card))
    qp.setColor(QPalette.ColorRole.ToolTipText, qc(pal.text))
    qp.setColor(QPalette.ColorRole.Highlight, qc(pal.accent))
    qp.setColor(QPalette.ColorRole.HighlightedText, qc(pal.accent_contrast))
    qp.setColor(QPalette.ColorRole.Link, qc(pal.accent))
    qp.setColor(QPalette.ColorRole.PlaceholderText, qc(pal.text3, 170))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText):
        qp.setColor(QPalette.ColorGroup.Disabled, role, qc(pal.text3, 150))
    app.setPalette(qp)
    # 同步原生窗口外观（macOS 标题栏等）：auto 跟随系统，其余显式指定
    try:
        hints = QApplication.styleHints()
        if theme_mode == "auto":
            hints.setColorScheme(Qt.ColorScheme.Unknown)
        else:
            hints.setColorScheme(
                Qt.ColorScheme.Dark if pal.dark else Qt.ColorScheme.Light)
    except (AttributeError, RuntimeError):
        pass


def qt_font(px: int, bold: bool = False) -> QFont:
    f = QFont(UI_FONT)
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def mono_qfont(px: int) -> QFont:
    f = QFont(MONO_FONT)
    if not f.exactMatch():
        f = QFont("Menlo")
    f.setPixelSize(px)
    return f


def draw_icon(p: QPainter, name: str, cx: float, cy: float,
              size: float, color: QColor, width: float = 1.6) -> None:
    """单色矢量小图标（与原版自绘符号体系对应）"""
    p.save()
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    s = size / 2.0
    if name == "search":
        p.drawEllipse(QPointF(cx - s * 0.15, cy - s * 0.15), s * 0.62, s * 0.62)
        p.drawLine(QPointF(cx + s * 0.30, cy + s * 0.30),
                   QPointF(cx + s * 0.85, cy + s * 0.85))
    elif name == "download":
        p.drawLine(QPointF(cx, cy - s * 0.85), QPointF(cx, cy + s * 0.35))
        p.drawLine(QPointF(cx - s * 0.45, cy - s * 0.05), QPointF(cx, cy + 0.38 * s))
        p.drawLine(QPointF(cx + s * 0.45, cy - s * 0.05), QPointF(cx, cy + 0.38 * s))
        p.drawLine(QPointF(cx - s * 0.8, cy + s * 0.8), QPointF(cx + s * 0.8, cy + s * 0.8))
    elif name == "folder":
        path = QPainterPath()
        path.moveTo(cx - s * 0.85, cy - s * 0.45)
        path.lineTo(cx - s * 0.25, cy - s * 0.45)
        path.lineTo(cx + 0.05 * s, cy - s * 0.12)
        path.lineTo(cx + s * 0.85, cy - s * 0.12)
        path.quadTo(cx + s * 0.85, cy + s * 0.6, cx + s * 0.55, cy + s * 0.6)
        path.lineTo(cx - s * 0.55, cy + s * 0.6)
        path.quadTo(cx - s * 0.85, cy + s * 0.6, cx - s * 0.85, cy + s * 0.3)
        path.closeSubpath()
        p.drawPath(path)
    elif name == "trash":
        p.drawLine(QPointF(cx - s * 0.7, cy - s * 0.5), QPointF(cx + s * 0.7, cy - s * 0.5))
        p.drawLine(QPointF(cx, cy - s * 0.8), QPointF(cx, cy - s * 0.5))
        p.drawRoundedRect(QRectF(cx - s * 0.55, cy - s * 0.5, s * 1.1, s * 1.35), 3, 3)
        p.drawLine(QPointF(cx - s * 0.2, cy - s * 0.15), QPointF(cx - s * 0.2, cy + s * 0.5))
        p.drawLine(QPointF(cx + s * 0.2, cy - s * 0.15), QPointF(cx + s * 0.2, cy + s * 0.5))
    elif name == "clock":
        p.drawEllipse(QPointF(cx, cy), s * 0.8, s * 0.8)
        p.drawLine(QPointF(cx, cy - s * 0.45), QPointF(cx, cy))
        p.drawLine(QPointF(cx, cy), QPointF(cx + s * 0.35, cy + s * 0.2))
    elif name == "heart":
        path = QPainterPath()
        path.moveTo(cx, cy + s * 0.75)
        path.cubicTo(cx - s * 1.35, cy - s * 0.25, cx - s * 0.45, cy - s * 1.05, cx, cy - s * 0.25)
        path.cubicTo(cx + s * 0.45, cy - s * 1.05, cx + s * 1.35, cy - s * 0.25, cx, cy + s * 0.75)
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(path)
    elif name == "sun":
        p.drawEllipse(QPointF(cx, cy), s * 0.42, s * 0.42)
        for i in range(8):
            a = i * 3.14159265 / 4
            p.drawLine(QPointF(cx + 0.62 * s * _cos(a), cy + 0.62 * s * _sin(a)),
                       QPointF(cx + 0.88 * s * _cos(a), cy + 0.88 * s * _sin(a)))
    elif name == "moon":
        path = QPainterPath()
        path.addEllipse(QPointF(cx, cy), s * 0.8, s * 0.8)
        cut = QPainterPath()
        cut.addEllipse(QPointF(cx + s * 0.42, cy - s * 0.34), s * 0.72, s * 0.72)
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(path.subtracted(cut))
    elif name == "half":
        p.drawEllipse(QPointF(cx, cy), s * 0.8, s * 0.8)
        path = QPainterPath()
        path.moveTo(cx, cy - s * 0.8)
        path.arcTo(QRectF(cx - s * 0.8, cy - s * 0.8, s * 1.6, s * 1.6), 90, -180)
        path.closeSubpath()
        p.setBrush(color)
        p.drawPath(path)
    elif name == "pause":
        p.drawLine(QPointF(cx - s * 0.3, cy - s * 0.65), QPointF(cx - s * 0.3, cy + s * 0.65))
        p.drawLine(QPointF(cx + s * 0.3, cy - s * 0.65), QPointF(cx + s * 0.3, cy + s * 0.65))
    elif name == "play":
        path = QPainterPath()
        path.moveTo(cx - s * 0.4, cy - s * 0.7)
        path.lineTo(cx + s * 0.65, cy)
        path.lineTo(cx - s * 0.4, cy + s * 0.7)
        path.closeSubpath()
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(path)
    elif name == "close":
        p.drawLine(QPointF(cx - s * 0.55, cy - s * 0.55), QPointF(cx + s * 0.55, cy + s * 0.55))
        p.drawLine(QPointF(cx - s * 0.55, cy + s * 0.55), QPointF(cx + s * 0.55, cy - s * 0.55))
    elif name == "chevron":
        p.drawLine(QPointF(cx - s * 0.55, cy - s * 0.2), QPointF(cx, cy + s * 0.3))
        p.drawLine(QPointF(cx, cy + s * 0.3), QPointF(cx + s * 0.55, cy - s * 0.2))
    elif name == "note":
        p.drawLine(QPointF(cx + s * 0.35, cy - s * 0.75), QPointF(cx + s * 0.35, cy + s * 0.45))
        p.drawLine(QPointF(cx + s * 0.35, cy - s * 0.75), QPointF(cx - s * 0.45, cy - s * 0.55))
        p.drawEllipse(QPointF(cx - s * 0.1, cy + s * 0.45), s * 0.42, s * 0.34)
    elif name == "stop":
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(cx - s * 0.5, cy - s * 0.5, s, s), 2, 2)
    elif name == "gear":
        # 八齿齿轮
        import math as _m
        for i in range(8):
            a = i * _m.pi / 4
            p.drawLine(
                QPointF(cx + 0.52 * s * _cos(a), cy + 0.52 * s * _sin(a)),
                QPointF(cx + 0.82 * s * _cos(a), cy + 0.82 * s * _sin(a)),
            )
        p.drawEllipse(QPointF(cx, cy), s * 0.52, s * 0.52)
        p.drawEllipse(QPointF(cx, cy), s * 0.22, s * 0.22)
    p.restore()


def _cos(a: float) -> float:
    import math
    return math.cos(a)


def _sin(a: float) -> float:
    import math
    return math.sin(a)


def paint_glass_surface(
    p: QPainter, rect: QRectF, radius: float, *,
    fill: Optional[QColor] = None, hover: float = 0.0, pressed: float = 0.0,
    sheen: float = 1.0, rim: tuple[float, float] = (0.32, 0.10),
    border: Optional[QColor] = None, focus: Optional[QColor] = None,
    disabled: bool = False,
) -> None:
    """内层控件通用"液态玻璃"绘制：半透明填充 + 顶部高光 + 边缘光晕。"""

    def _rr_path(r: QRectF, rad: float) -> QPainterPath:
        q = QPainterPath()
        q.addRoundedRect(r, max(0.0, rad), max(0.0, rad))
        return q

    if disabled:
        p.setOpacity(0.45)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    path = _rr_path(rect, radius)

    # 本体填充
    if fill is not None:
        p.fillPath(path, fill)
    # 悬停提亮 / 按压压暗（操作状态视觉反馈）
    if hover > 0 and fill is not None:
        p.fillPath(path, QColor(255, 255, 255, int(26 * hover)))
    if pressed > 0:
        p.fillPath(path, QColor(0, 0, 0, int(30 * pressed)))
    # 顶部光泽（sheen）
    if sheen > 0:
        g = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.top() + rect.height() * 0.55))
        g.setColorAt(0.0, QColor(255, 255, 255, int(30 * sheen)))
        g.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillPath(path, QBrush(g))
    # 边缘光晕：上亮下暗 1px 内描边
    rg = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    rg.setColorAt(0.0, QColor(255, 255, 255, int(255 * rim[0])))
    rg.setColorAt(1.0, QColor(0, 0, 0, int(255 * rim[1])))
    p.setPen(QPen(QBrush(rg), 1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(_rr_path(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius - 0.5))
    if border is not None:
        p.setPen(QPen(border, 1))
        p.drawPath(_rr_path(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius - 0.5))
    # 焦点光圈
    if focus is not None:
        p.setPen(QPen(focus, 1.5))
        p.drawPath(_rr_path(rect.adjusted(-0.8, -0.8, 0.8, 0.8), radius + 0.8))
    if disabled:
        p.setOpacity(1.0)


# ==================== 主题管理 ====================


class ThemeManager(QObject):
    """设计方案 + 外观模式；持久化沿用 gui.py 的 settings.json。"""

    changed = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        settings = load_settings()
        self.scheme_key: str = settings.get("scheme", "liquid")
        self.theme_mode: str = settings.get("theme_mode", "auto")
        self._detected_dark = system_prefers_dark()

    @property
    def dark(self) -> bool:
        if self.theme_mode == "auto":
            return self._detected_dark
        return self.theme_mode == "dark"

    @property
    def palette(self):
        pal = SCHEMES[self.scheme_key]["dark" if self.dark else "light"]
        return wcag_safe_palette(pal)

    @property
    def glyph(self) -> str:
        return {"auto": "half", "light": "sun", "dark": "moon"}[self.theme_mode]

    def set_scheme(self, key: str) -> None:
        if key in SCHEMES and key != self.scheme_key:
            self.scheme_key = key
            self._persist()
            self.changed.emit()

    def set_mode(self, mode: str) -> None:
        if mode in ("auto", "light", "dark") and mode != self.theme_mode:
            self.theme_mode = mode
            self._persist()
            self.changed.emit()

    def _persist(self) -> None:
        save_settings({"scheme": self.scheme_key, "theme_mode": self.theme_mode})


# ==================== 环境光背景 + 共享折射源 ====================


class _RefractSignals(QObject):
    """工作线程 → GUI 线程的结果回传。"""
    done = pyqtSignal(object, int, object)  # panel_ref, gen, QImage|None


class _RefractJob(QRunnable):
    """在工作线程中完成单面板的 numpy 折射计算（kernel 构建/霜化 blur 均在此）。

    输入（背景数组、renderer、几何令牌）在提交时抓取为局部只读引用，
    即使 GUI 线程随后重建 kernel 也互不干扰；产出为独立 QImage（已 detach），
    QPixmap 合成留给 GUI 线程。"""

    def __init__(self, panel_ref, gen: int, arr, origin: QPoint, dpr: float,
                 fast: bool) -> None:
        super().__init__()
        self._panel_ref = panel_ref
        self._gen = gen
        self._arr = arr
        self._origin = QPoint(origin)
        self._dpr = dpr
        self._fast = fast
        self.signals = _RefractSignals()

    def run(self) -> None:
        result: Optional[QImage] = None
        panel = self._panel_ref()
        try:
            if panel is not None:
                result = panel._refract_compute(
                    self._arr, self._origin, self._dpr, self._fast)
        except Exception:
            result = None
        # 跨线程投递为自动队列连接（信号发对象属于无父 QObject，槽在 GUI 线程）
        try:
            self.signals.done.emit(self._panel_ref, self._gen, result)
        except RuntimeError:
            pass  # 应用关闭阶段信号对象已析构，结果无需回收


class AmbientBackground(QWidget):
    """中央背景：柔光光斑环境（玻璃折射的"内容"），并持有唯一的
    WidgetBackdrop —— 所有玻璃面板/弹窗共享一次采集，各自折射。"""

    def __init__(self, theme: ThemeManager, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.theme = theme
        self._pm: Optional[QPixmap] = None
        self._pm_key: tuple = ()
        # 协作式背景源：仅返回背景像素（不含子控件），采集零闪烁
        self.backdrop = WidgetBackdrop(self, scene_provider=self.scene_pixmap)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(90)
        self._refresh_timer.timeout.connect(lambda: self.refresh_glass(fast=False))
        # 折射线程池：numpy 内核计算（gather/box-blur/kernel 构建）并行执行，
        # 不再阻塞 UI 线程；QPixmap 合成仍在 GUI 线程
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max(2, min(8, os.cpu_count() or 2)))
        self._gen = 0
        self._flight: dict = {}   # signals QObject -> _RefractJob（跨线程投递期间保活）

    # ---- 背景绘制 ----

    def _rebuild(self) -> None:
        dpr = self.devicePixelRatioF() or 1.0
        w, h = max(2, self.width()), max(2, self.height())
        pm = QPixmap(int(w * dpr), int(h * dpr))
        pm.setDevicePixelRatio(dpr)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(0, 0, w, h, qc(self.theme.palette.bg))
        pal = self.theme.palette
        # 三团柔光：主色调 ×2 + 中性光 ×1（浅/深色下均成立）
        blobs = [
            (0.16, 0.10, 0.55, mix_qc(qc(pal.accent), qc(pal.bg), 0.35), 78),
            (0.88, 0.26, 0.48, mix_qc(qc(pal.accent), qc(pal.bg), 0.55), 64),
            (0.42, 0.92, 0.60, mix_qc(qc(pal.text), qc(pal.bg), 0.22), 46),
        ]
        for rx, ry, rr, color, alpha in blobs:
            radius = min(w, h) * rr
            g = QRadialGradient(rx * w, ry * h, radius)
            c = QColor(color)
            c.setAlpha(alpha)
            g.setColorAt(0.0, c)
            c2 = QColor(color)
            c2.setAlpha(0)
            g.setColorAt(1.0, c2)
            p.fillRect(0, 0, w, h, QBrush(g))
        # 顶部冷光（玻璃高光来源）
        top = QLinearGradient(0, 0, 0, h * 0.5)
        top.setColorAt(0.0, QColor(255, 255, 255, 26 if pal.dark else 58))
        top.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(0, 0, w, h, QBrush(top))
        p.end()
        self._pm = pm
        self._pm_key = (w, h, dpr, self.theme.scheme_key, self.theme.theme_mode, self.theme.dark)

    def scene_pixmap(self) -> QPixmap:
        """WidgetBackdrop 协作源：当前背景像素。"""
        key = (self.width(), self.height(), self.devicePixelRatioF() or 1.0,
               self.theme.scheme_key, self.theme.theme_mode, self.theme.dark)
        if self._pm is None or key != self._pm_key:
            self._rebuild()
        return self._pm

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        pm = self.scene_pixmap()
        if pm is not None:
            p.drawPixmap(0, 0, pm)
        p.end()

    def resizeEvent(self, _e) -> None:  # noqa: N802
        self.update()
        self.schedule_refresh()

    # ---- 共享折射采集（主线程采集 + 线程池并行折射） ----

    def refresh_glass(self, *, fast: bool = False) -> None:
        """采集一次背景（GUI 线程，约 20ms）→ 为每块可见玻璃面板派发并行折射。

        本方法立即返回；numpy 计算（kernel 构建/gather/霜化 blur）在工作线程
        完成，结果就绪后逐块增量上屏，切换/缩放期间 UI 线程不被阻塞。
        """
        if not self.isVisible():
            return
        self.backdrop.refresh()
        arr = self.backdrop.array()
        if arr is None:
            return
        dpr = self.backdrop.dpr()
        panels = [w for w in self.findChildren(GlassPanel) if w.isVisible()]
        if not panels:
            return
        self._gen += 1
        gen = self._gen
        for panel in panels:
            origin = panel.mapTo(self, QPoint(0, 0))
            job = _RefractJob(
                weakref.ref(panel), gen, arr, origin, dpr, fast)
            job.signals.done.connect(self._on_job_done)
            self._flight[job.signals] = job   # 保活至结果回到 GUI 线程
            self._pool.start(job)

    def _on_job_done(self, panel_ref, gen: int, image: Optional[QImage]) -> None:
        self._flight.pop(self.sender(), None)
        panel = panel_ref()
        if panel is None or gen != self._gen or image is None:
            return
        dpr = self.backdrop.dpr()
        scale = panel._render_scale(dpr)
        fw, fh = panel._geom_token(dpr)[:2]
        # 结果在途期间几何已变化（缩放/改圆角）→ 丢弃并安排一次刷新
        if (image.width(), image.height()) != (int(fw * scale), int(fh * scale)):
            self.schedule_refresh()
            return
        pm = QPixmap.fromImage(image)
        if scale < 0.99:
            # 不做 CPU 全尺寸放大：半分辨率纹理直接上传（1/4 字节），
            # 由 QPainter 平滑变换在 GPU 侧放大，降低主线程合成耗时
            pm.setDevicePixelRatio(dpr * scale)
        else:
            pm.setDevicePixelRatio(dpr)
        panel._set_refracted(pm)

    def schedule_refresh(self) -> None:
        """防抖：连续 resize/theme 切换只触发最终一次全量采集。"""
        self._refresh_timer.start()


# ==================== 玻璃面板（内嵌真折射） ====================


class GlassPanel(QWidget):
    """内嵌于背景之上的真折射玻璃面板；内容放进 .content 布局。"""

    def __init__(self, ambient: AmbientBackground, *, radius: int = 18,
                 material: GlassMaterial = PANEL_MATERIAL,
                 pad: tuple[int, int, int, int] = (14, 12, 14, 12),
                 spacing: int = 8) -> None:
        super().__init__(ambient)
        self.ambient = ambient
        self._radius = radius
        self._material = material
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._renderer = GlassRenderer(material, 10, 10, radius)
        self._refracted: Optional[QPixmap] = None
        self._style = EMBEDDED_STYLE

        self.content = QVBoxLayout(self)
        self.content.setContentsMargins(*pad)
        self.content.setSpacing(spacing)

        # 折射由 AmbientBackground.refresh_glass 统一批量派发（线程池并行），
        # 不再各自监听 backdrop.changed 做 UI 线程同步折射

    # ---- 折射 ----

    # 设备像素超过该阈值即在半分辨率缓冲计算折射（玻璃内容为柔光斑、
    # 且霜化本身带模糊，半分辨率视觉无损），gather/霜化/kernel 计算量降至 1/4
    _HALF_RES_PX = 300_000

    def _render_scale(self, dpr: float) -> float:
        pw = int(max(10, self.width()) * dpr)
        ph = int(max(10, self.height()) * dpr)
        return 0.5 if pw * ph > self._HALF_RES_PX else 1.0

    def _geom_token(self, dpr: float) -> tuple[int, int, int]:
        """提交/回传一致性校验用的几何令牌（全设备像素宽高 + 逻辑圆角）。"""
        return (int(max(10, self.width()) * dpr),
                int(max(10, self.height()) * dpr), self._radius)

    def set_radius(self, radius: int) -> None:
        # 仅标记几何脏：kernel 重建在工作线程完成，不再用旧背景立即同步折射
        # （方案切换原先因此重复折射一整轮）。调用方随后统一 refresh_glass。
        if radius != self._radius:
            self._radius = radius
            self._renderer.set_geometry(
                max(10, self.width()), max(10, self.height()), radius)
            self.update()

    def _refract_full(self) -> None:
        """兼容入口：请求一次批量异步折射。"""
        self.ambient.refresh_glass()

    @staticmethod
    def _slice_scaled(arr, gx: int, gy: int, gw: int, gh: int,
                      step: int) -> "np.ndarray":
        """从全分辨率背景数组取 (gy..gy+gh, gx..gx+gw) 区域并降采样 step 倍。

        step=1 为直接取视图；step=2 为跨步抽样（零拷贝视图）。玻璃折射内容
        为低频柔光斑且后续还有霜化 blur，最近邻抽样无可见锯齿，
        远快于 2×2 均值（后者需整块 uint16 累加）。"""
        h, w = arr.shape[:2]
        if step == 1:
            if 0 <= gx <= w - gw and 0 <= gy <= h - gh:
                return arr[gy:gy + gh, gx:gx + gw]
            xs = np.clip(np.arange(gx, gx + gw), 0, w - 1)
            ys = np.clip(np.arange(gy, gy + gh), 0, h - 1)
            return arr[np.ix_(ys, xs)]
        if 0 <= gx <= w - gw * step and 0 <= gy <= h - gh * step:
            return arr[gy:gy + gh * step:step, gx:gx + gw * step:step]
        xs = np.clip(np.arange(gx, gx + gw * step, step), 0, w - 1)
        ys = np.clip(np.arange(gy, gy + gh * step, step), 0, h - 1)
        return arr[np.ix_(ys, xs)]

    def _refract_compute(self, arr, origin: QPoint, dpr: float,
                         fast: bool) -> Optional[QImage]:
        """工作线程执行：kernel 构建 + numpy 折射，返回已 detach 的 QImage。

        大面板走半分辨率缓冲（柔光斑 + 霜化模糊下视觉无损），主线程上屏前
        平滑放大到全尺寸。kernel 按 (尺寸, 圆角, dpr) 缓存——模式切换
        （仅配色变化）直接复用，零重建。"""
        scale = self._render_scale(dpr)
        lw, lh = max(10, self.width()), max(10, self.height())
        edpr = dpr * scale
        pw, ph = int(lw * edpr), int(lh * edpr)
        rad_px = self._radius * edpr
        key = (pw, ph, rad_px, edpr)
        ck = getattr(self, "_lk", None)
        if ck is None or ck[0] != key:
            kernel = self._material.build_kernel(pw, ph, rad_px, edpr)
            self._lk = (key, kernel)
        else:
            kernel = ck[1]
        pad = self._material.pad_px(edpr)
        gw, gh = pw + 2 * pad, ph + 2 * pad
        step = 2 if scale < 0.99 else 1
        gx = int(origin.x() * edpr) - pad
        gy = int(origin.y() * edpr) - pad
        padded = self._slice_scaled(arr, gx * step, gy * step, gw, gh, step)
        out = kernel.apply(padded, scatter=not fast)
        img = QImage(out.data, pw, ph, pw * 4, QImage.Format.Format_RGBA8888)
        img.setDevicePixelRatio(edpr)
        return img.copy()  # 脱离 numpy 缓冲区，可安全跨线程传递

    def _set_refracted(self, pm: Optional[QPixmap]) -> None:
        self._refracted = pm
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # 半分辨率折射纹理由 paint_glass 内的 SmoothPixmapTransform 平滑放大
        paint_glass(p, QRectF(self.rect()), self._radius,
                    self._refracted, style=self._style)
        p.end()

    def showEvent(self, _e) -> None:  # noqa: N802
        self._renderer.set_geometry(max(10, self.width()), max(10, self.height()), self._radius)
        QTimer.singleShot(0, self.ambient.schedule_refresh)

    def resizeEvent(self, _e) -> None:  # noqa: N802
        self._renderer.set_geometry(max(10, self.width()), max(10, self.height()), self._radius)
        # 不再用旧背景做 UI 线程同步折射（拖拽时同样卡帧）；
        # 防抖 90ms 后线程池批量出新结果，期间旧折射图保留，无闪烁
        self.ambient.schedule_refresh()


# ==================== 玻璃弹窗基类（遮罩 + 折射面板） ====================


class GlassOverlay(QWidget):
    """覆盖背景的玻璃弹窗：暗化遮罩 + 折射玻璃面板 + 展开动画，
    Esc / 点击面板外部关闭。"""

    closed = pyqtSignal()

    def __init__(self, ambient: AmbientBackground, panel_w: int, panel_h: int, *,
                 radius: int = 24, scrim: int = 46,
                 material: GlassMaterial = DIALOG_MATERIAL,
                 pad: tuple[int, int, int, int] = (26, 22, 26, 22),
                 spacing: int = 10) -> None:
        super().__init__(ambient)
        self.ambient = ambient
        self._radius = radius
        self._scrim = scrim
        self._reveal = 0.0
        self._closing = False

        self._renderer = GlassRenderer(material, panel_w, panel_h, radius)
        self._refracted: Optional[QPixmap] = None

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.hide()

        self.panel = QWidget(self)
        self.panel.setFixedSize(panel_w, panel_h)
        self.panel.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._opacity = QGraphicsOpacityEffect(self.panel)
        self._opacity.setOpacity(0.0)
        self.panel.setGraphicsEffect(self._opacity)

        self.body = QVBoxLayout(self.panel)
        self.body.setContentsMargins(*pad)
        self.body.setSpacing(spacing)

        self._anim = QPropertyAnimation(self, b"reveal", self)
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._on_anim_done)

    # ---- 内容 ----

    def content(self) -> QVBoxLayout:
        return self.body

    # ---- 打开 / 关闭 ----

    def open_at(self, global_pos: Optional[QPoint] = None) -> None:
        """在 ambient 内定位并展开；global_pos 为面板左上角的全局坐标。"""
        self.setGeometry(self.ambient.rect())
        self._place(global_pos)
        self.raise_()
        self.show()
        self.setFocus()
        self._refract()
        self._closing = False
        self._anim.stop()
        self._anim.setStartValue(self._reveal)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _place(self, global_pos: Optional[QPoint]) -> None:
        if global_pos is None:
            x = (self.width() - self.panel.width()) // 2
            y = (self.height() - self.panel.height()) // 2
        else:
            tl = self.mapFromGlobal(global_pos)
            x, y = tl.x(), tl.y()
        x = max(6, min(x, self.width() - self.panel.width() - 6))
        y = max(6, min(y, self.height() - self.panel.height() - 6))
        self._home = QPoint(x, y)
        self._apply_reveal()

    def close(self) -> None:  # noqa: N802
        if self._closing:
            return
        self._closing = True
        self._anim.stop()
        self._anim.setStartValue(self._reveal)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def _on_anim_done(self) -> None:
        if self._reveal <= 0.001:
            self.hide()
            self.closed.emit()
        self._closing = False

    def _apply_reveal(self) -> None:
        dy = int((1.0 - self._reveal) * 12)
        self.panel.move(self._home.x() if hasattr(self, "_home") else 0,
                        (self._home.y() if hasattr(self, "_home") else 0) + dy)
        self._opacity.setOpacity(max(0.0, min(1.0, self._reveal)))

    # ---- 折射 ----

    def _refract(self) -> None:
        # 弹窗独立同步折射（仅本面板、打开频率低），直接采集即可，
        # 不触发主窗口面板的异步批量折射
        self.ambient.backdrop.refresh()
        arr = self.ambient.backdrop.array()
        if arr is None:
            self._refracted = None
            return
        origin = self.panel.mapTo(self.ambient, QPoint(0, 0))
        self._refracted = self._renderer.refract(
            arr, origin, self.ambient.backdrop.dpr())

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = self._reveal
        p.fillRect(self.rect(), QColor(6, 8, 16, int(self._scrim * r)))
        paint_glass(p, QRectF(self.panel.geometry()), self._radius,
                    self._refracted, style=GLASS_STYLE, reveal=r)
        p.end()

    # ---- 交互 ----

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if not self.panel.geometry().contains(e.position().toPoint()):
            self.close()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    # ---- reveal 属性 ----

    def get_reveal(self) -> float:
        return self._reveal

    def set_reveal(self, v: float) -> None:
        self._reveal = v
        self._apply_reveal()
        self.update()

    reveal = pyqtProperty(float, fget=get_reveal, fset=set_reveal)


# ==================== 玻璃菜单（折射下拉） ====================


class _MenuRow(QAbstractButton):
    """菜单行：悬停玻璃高亮 + 选中圆点。"""

    def __init__(self, text: str, checked: bool, pal, on_pick: Callable[[], None],
                 parent: QWidget) -> None:
        super().__init__(parent)
        self._text = text
        self._checked = checked
        self._pal = pal
        self._hover = 0.0
        self._pressed = 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(38)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # clicked 会带 checked 参数，统一包装为无参回调，避免污染带默认参的 lambda
        self.clicked.connect(lambda *_a: on_pick())

    def apply_theme(self, pal) -> None:
        self._pal = pal
        self.update()

    def enterEvent(self, _e) -> None:  # noqa: N802
        self._hover = 1.0
        self.update()

    def leaveEvent(self, _e) -> None:  # noqa: N802
        self._hover = 0.0
        self.update()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        super().mousePressEvent(e)  # 必须：让 QAbstractButton 进入 down 状态，clicked 才会发射
        self._pressed = 1.0
        self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._pressed = 0.0
        self.update()
        super().mouseReleaseEvent(e)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(3, 2, -3, -2)
        pal = self._pal
        base = qc(pal.card, 0)
        paint_glass_surface(p, rect, 9, fill=base,
                            hover=self._hover, pressed=self._pressed,
                            sheen=0.0, rim=(0.0, 0.0))
        # 文本：左侧 18px 内边距，右侧为选中点预留 40px，超长省略号收尾
        p.setPen(qc(pal.text))
        f = qt_font(12, bold=self._checked)
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 102)
        p.setFont(f)
        text_rect = rect.adjusted(18, 0, -40, 0)
        elided = p.fontMetrics().elidedText(
            self._text, Qt.TextElideMode.ElideRight, int(text_rect.width()))
        p.drawText(text_rect,
                   int(Qt.AlignmentFlag.AlignVCenter) | int(Qt.AlignmentFlag.AlignLeft),
                   elided)
        # 选中指示点
        if self._checked:
            cx = rect.right() - 20
            cy = rect.center().y()
            p.setBrush(qc(pal.accent))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx, cy), 4, 4)
        p.end()


class GlassMenu(GlassOverlay):
    """折射玻璃菜单：sections = [(标题|None, [(value, label, checked), …])]"""

    ITEM_H = 38
    SECTION_H = 26
    MAX_H = 440
    MAX_TEXT_W = 320  # 文本区最大宽度，超出省略号收尾

    def __init__(self, ambient: AmbientBackground, pal,
                 sections: list[tuple[Optional[str], list[tuple[str, str, bool]]]],
                 on_pick: Callable[[str], None], *, min_width: int = 190) -> None:
        items = sum(len(g) for _t, g in sections)
        heads = sum(1 for t, _g in sections if t)
        rows = items + heads
        # 面板宽度按最长文本计算：左缩进 18 + 右侧选中点区 40 + 行内边距 6 + 布局外边距 24
        fm = QFontMetrics(qt_font(12))
        text_w = 0
        for _t, group in sections:
            for _v, label, _c in group:
                text_w = max(text_w, fm.horizontalAdvance(label))
        text_w = min(text_w, self.MAX_TEXT_W)
        panel_w = max(min_width, 220, text_w + 18 + 40 + 6 + 24)
        height = items * self.ITEM_H + heads * self.SECTION_H + max(0, rows - 1) * 4 + 24
        super().__init__(ambient, panel_w, min(height, self.MAX_H),
                         radius=18, scrim=18)
        self._on_pick = on_pick
        self._pal = pal
        lay = self.content()
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(0)
        # 内容超出 MAX_H 时进入滚动区，行高保持 ITEM_H 不被压缩
        scroll = QScrollArea(self.panel)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {pal.card}; }}"
            f"QScrollArea > QWidget > QWidget {{ background: {pal.card}; }}"
            "QScrollBar:vertical { width: 6px; background: transparent; }"
            "QScrollBar::handle:vertical { background: rgba(128,128,128,90);"
            " border-radius: 3px; min-height: 28px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }")
        holder = QWidget()
        holder.setStyleSheet(f"background: {pal.card};")
        hold_lay = QVBoxLayout(holder)
        hold_lay.setContentsMargins(0, 0, 0, 0)
        hold_lay.setSpacing(4)
        for title, group in sections:
            if title:
                lbl = QLabel(title, holder)
                lbl.setFont(qt_font(10))
                lbl.setFixedHeight(self.SECTION_H)
                self._style_label(lbl, pal)
                hold_lay.addWidget(lbl)
            for value, label, checked in group:
                row = _MenuRow(label, checked, pal,
                               lambda v=value: (self.close(), self._on_pick(v)),
                               holder)
                hold_lay.addWidget(row)
                self._rows = getattr(self, "_rows", [])
                self._rows.append(row)
        scroll.setWidget(holder)
        lay.addWidget(scroll)

    def paintEvent(self, _e) -> None:  # noqa: N802
        """绘制：菜单面板用主题 card 不透明色填充，不再走折射渲染，确保文字可读。"""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = self._reveal
        # 遮罩暗化
        p.fillRect(self.rect(), QColor(6, 8, 16, int(self._scrim * r)))
        # 面板：主题 card 不透明圆角矩形
        c = qc(self._pal.card)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.panel.geometry()), self._radius, self._radius)
        p.setOpacity(r)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c.red(), c.green(), c.blue(), 255))
        p.drawPath(path)
        # 细边框保持视觉层次
        p.setPen(QPen(qc(self._pal.text, 40), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.setOpacity(1.0)
        p.end()

    @staticmethod
    def _style_label(lbl: QLabel, pal) -> None:
        lbl.setStyleSheet(f"color: {pal.text3}; background: transparent;")
        lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)


# ==================== 玻璃控件 ====================


class GlassButton(QAbstractButton):
    """液态玻璃按钮。kind: accent / tinted / ghost / danger"""

    def __init__(self, text: str = "", *, kind: str = "ghost", glyph: Optional[str] = None,
                 width: Optional[int] = None, small: bool = False,
                 command: Optional[Callable[[], None]] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._text = text
        self._kind = kind
        self._glyph = glyph
        self._small = small
        self._hover = 0.0
        self._press_t = 0.0
        self._selected = False
        self._pal = None  # 由 apply_theme 注入
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(120)
        self._anim.valueChanged.connect(self._on_press_anim)
        if command:
            # clicked(bool) 的 checked 参数不得泄漏给业务回调
            self.clicked.connect(lambda *_a: command())
        if width is not None:
            self.setFixedWidth(width)
        h = 26 if small else 34
        self.setFixedHeight(h)

    # ---- 兼容原版 API ----

    def set_state(self, state: str) -> None:
        self.setEnabled(state == "normal")
        self.update()

    def set_text(self, text: str) -> None:
        self._text = text
        self.update()
        self.updateGeometry()

    def set_command(self, cb: Callable[[], None]) -> None:
        self.clicked.disconnect()
        self.clicked.connect(lambda *_a: cb())

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.update()

    def set_glyph(self, glyph: Optional[str]) -> None:
        self._glyph = glyph
        self.update()

    def apply_theme(self, pal) -> None:
        self._pal = pal
        self.update()

    # ---- 尺寸 ----

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = QFontMetrics(qt_font(12, bold=self._kind == "accent"))
        w = fm.horizontalAdvance(self._text) if self._text else 0
        pad = 20 if not self._glyph else 14
        if self._glyph:
            w += 16
        return QSize(int(w + pad * 2 + 4), 26 if self._small else 34)

    # ---- 动效 ----

    def _on_press_anim(self, v) -> None:
        self._press_t = float(v)
        self.update()

    def enterEvent(self, _e) -> None:  # noqa: N802
        self._hover = 1.0
        self.update()

    def leaveEvent(self, _e) -> None:  # noqa: N802
        self._hover = 0.0
        self.update()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        super().mousePressEvent(e)  # 必须：让 QAbstractButton 进入 down 状态，clicked 才会发射
        self._anim.stop()
        self._anim.setStartValue(self._press_t)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._anim.stop()
        self._anim.setStartValue(self._press_t)
        self._anim.setEndValue(0.0)
        self._anim.start()
        super().mouseReleaseEvent(e)

    # ---- 绘制 ----

    def _radius(self, pal) -> float:
        rc = pal.radius_control
        return rc if rc >= 0 else self.height() / 2.0

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = self._pal
        if pal is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = self._radius(pal)
        dark = pal.dark
        disabled = not self.isEnabled()

        if self._kind == "accent":
            fill = qc(pal.accent, 235)
            if self._hover and not disabled:
                fill = mix_qc(fill, QColor(255, 255, 255), 0.10 * self._hover)
            paint_glass_surface(p, rect, radius, fill=fill, hover=0, pressed=self._press_t,
                                sheen=0.9, rim=(0.42, 0.06), disabled=disabled)
            fg = qc(pal.accent_contrast)
        elif self._kind == "tinted":
            fill = qc(pal.accent_soft, 200)
            if self._hover and not disabled:
                fill = qc(pal.accent_soft_hover, 220)
            paint_glass_surface(p, rect, radius, fill=fill, hover=0, pressed=self._press_t,
                                sheen=0.7, rim=(0.26, 0.10), disabled=disabled)
            fg = mix_qc(qc(pal.accent), qc(pal.text), 0.35)
        elif self._kind == "danger":
            fill = qc(pal.danger, 215)
            paint_glass_surface(p, rect, radius, fill=fill, hover=0, pressed=self._press_t,
                                sheen=0.7, rim=(0.30, 0.08), disabled=disabled)
            fg = QColor(255, 255, 255)
        else:  # ghost —— 透明玻璃
            base_a = 40 if dark else 110
            base_c = QColor(255, 255, 255) if dark else QColor(255, 255, 255)
            fill = QColor(base_c)
            fill.setAlpha(base_a)
            if self._selected:
                fill = qc(pal.accent_soft_hover, 225)
            paint_glass_surface(p, rect, radius, fill=fill, hover=self._hover,
                                pressed=self._press_t, sheen=0.8,
                                rim=(0.30, 0.10), disabled=disabled)
            fg = qc(pal.text)
            if self._selected:
                fg = mix_qc(qc(pal.accent), qc(pal.text), 0.2)

        # 内容（图标 + 文本）
        x = rect.left()
        fm = p.fontMetrics()
        if self._glyph:
            icon_c = fg if self._kind == "accent" else mix_qc(fg, qc(pal.text3), 0.15)
            draw_icon(p, self._glyph, x + 15, rect.center().y(), 13, icon_c)
            x += 26
        if self._text:
            p.setFont(qt_font(12, bold=self._kind == "accent"))
            tw = fm.horizontalAdvance(self._text)
            tx = x + ((rect.width() - (x - rect.left()) - tw) / 2)
            p.setPen(fg)
            p.drawText(QRectF(tx, rect.top(), tw, rect.height()),
                       int(Qt.AlignmentFlag.AlignVCenter), self._text)
        p.end()


class GlassIconButton(QAbstractButton):
    """圆形玻璃图标按钮（头部主题/打赏、任务行操作）。"""

    def __init__(self, glyph: str, *, size: int = 30, accent: bool = False,
                 command: Optional[Callable[[], None]] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._glyph = glyph
        self._accent = accent
        self._hover = 0.0
        self._press_t = 0.0
        self._pal = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(size, size)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(120)
        self._anim.valueChanged.connect(self._on_anim)
        if command:
            # clicked(bool) 的 checked 参数不得泄漏给业务回调
            self.clicked.connect(lambda *_a: command())

    def set_state(self, state: str) -> None:
        self.setEnabled(state == "normal")
        self.update()

    def set_glyph(self, glyph: str) -> None:
        self._glyph = glyph
        self.update()

    def apply_theme(self, pal) -> None:
        self._pal = pal
        self.update()

    def _on_anim(self, v) -> None:
        self._press_t = float(v)
        self.update()

    def enterEvent(self, _e) -> None:  # noqa: N802
        self._hover = 1.0
        self.update()

    def leaveEvent(self, _e) -> None:  # noqa: N802
        self._hover = 0.0
        self.update()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        super().mousePressEvent(e)  # 必须：让 QAbstractButton 进入 down 状态，clicked 才会发射
        self._anim.stop()
        self._anim.setStartValue(self._press_t)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._anim.stop()
        self._anim.setStartValue(self._press_t)
        self._anim.setEndValue(0.0)
        self._anim.start()
        super().mouseReleaseEvent(e)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = self._pal
        if pal is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        disabled = not self.isEnabled()
        if self._accent:
            fill = qc(pal.accent, 235)
            fg = qc(pal.accent_contrast)
            rim = (0.42, 0.06)
        else:
            base = QColor(255, 255, 255)
            base.setAlpha(44 if pal.dark else 120)
            fill = base
            fg = qc(pal.text2)
            rim = (0.32, 0.10)
        paint_glass_surface(p, rect, rect.width() / 2, fill=fill,
                            hover=self._hover, pressed=self._press_t,
                            sheen=0.85, rim=rim, disabled=disabled)
        draw_icon(p, self._glyph, rect.center().x(), rect.center().y(),
                  rect.width() * 0.48, fg)
        p.end()


class GlassField(QWidget):
    """玻璃输入框：QLineEdit + 自绘玻璃容器（含焦点光圈）。"""

    returnPressed = pyqtSignal()

    def __init__(self, *, placeholder: str = "", text: str = "",
                 trailing: bool = False, on_trailing: Optional[Callable[[], None]] = None,
                 small: bool = False, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._pal = None
        self._focus = False
        h = 30 if small else 38
        self.setFixedHeight(h)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(13, 0, 9, 0)
        lay.setSpacing(4)
        self.edit = QLineEdit(text, self)
        self.edit.setPlaceholderText(placeholder)
        self.edit.setFrame(False)
        self.edit.setFixedHeight(h - 8)
        self.edit.setStyleSheet("background: transparent; border: none;")
        self.edit.returnPressed.connect(self.returnPressed)
        self.edit.installEventFilter(self)
        lay.addWidget(self.edit, 1)

        if trailing:
            self.trailing_btn = GlassIconButton("clock", size=24, parent=self)
            if on_trailing:
                self.trailing_btn.clicked.connect(on_trailing)
            lay.addWidget(self.trailing_btn, 0, Qt.AlignmentFlag.AlignVCenter)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.edit and event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self._focus = event.type() == QEvent.Type.FocusIn
            self.update()
        return super().eventFilter(obj, event)

    # 兼容原版 API
    def get(self) -> str:
        return self.edit.text()

    def set(self, value: str) -> None:
        self.edit.setText(value)

    def apply_theme(self, pal) -> None:
        self._pal = pal
        self.edit.setStyleSheet(
            "background: transparent; border: none;"
            f"color: {pal.text};"
            f"selection-background-color: {pal.accent_soft};"
        )
        # 占位文字颜色走 QPalette（QLineEdit 内置支持）
        pl = self.edit.palette()
        pl.setColor(QPalette.ColorRole.PlaceholderText, qc(pal.text3, 170))
        self.edit.setPalette(pl)
        self.update()
        if hasattr(self, "trailing_btn"):
            self.trailing_btn.apply_theme(pal)

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = self._pal
        if pal is None:
            return
        p = QPainter(self)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = pal.radius_control if pal.radius_control >= 0 else rect.height() / 2
        fill = qc(pal.input_bg, 225 if pal.dark else 245)
        paint_glass_surface(
            p, rect, radius, fill=fill, sheen=0.6,
            rim=(0.20, 0.08),
            border=qc(pal.border, 110),
            focus=qc(pal.accent, 200) if self._focus else None,
        )
        p.end()


class GlassSelect(QAbstractButton):
    """玻璃下拉选择（弹出折射菜单）。"""

    def __init__(self, ambient: AmbientBackground, values: list[str], value: str, *,
                 on_change: Optional[Callable[[str], None]] = None,
                 width: int = 132, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.ambient = ambient
        self._values = list(values)
        self._value = value
        self._on_change = on_change
        self._hover = 0.0
        self._press_t = 0.0
        self._pal = None
        self._popup: Optional[GlassMenu] = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(30)
        self.setFixedWidth(width)

    # ---- 数据 ----

    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        if value != self._value:
            self._value = value
            self.update()

    def set_values(self, values: list[str]) -> None:
        self._values = list(values)
        if self._value not in self._values:
            self._value = self._values[0] if self._values else ""
        self.update()

    def apply_theme(self, pal) -> None:
        self._pal = pal
        self.update()

    # ---- 交互 ----

    def enterEvent(self, _e) -> None:  # noqa: N802
        self._hover = 1.0
        self.update()

    def leaveEvent(self, _e) -> None:  # noqa: N802
        self._hover = 0.0
        self.update()

    def mousePressEvent(self, _e) -> None:  # noqa: N802
        self._press_t = 1.0
        self.update()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._press_t = 0.0
        self.update()
        super().mouseReleaseEvent(e)
        self._show_popup()

    def _show_popup(self) -> None:
        if self._pal is None:
            return
        self._popup = GlassMenu(
            self.ambient, self._pal,
            [(None, [(v, v, v == self._value) for v in self._values])],
            self._pick, min_width=self.width(),
        )
        gl = self.mapToGlobal(QPoint(0, self.height() + 4))
        self._popup.open_at(gl)

    def _pick(self, value: str) -> None:
        self.set(value)
        if self._on_change:
            self._on_change(value)

    # ---- 绘制 ----

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = self._pal
        if pal is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        fill = QColor(255, 255, 255)
        fill.setAlpha(40 if pal.dark else 120)
        paint_glass_surface(p, rect, rect.height() / 2, fill=fill,
                            hover=self._hover, pressed=self._press_t,
                            sheen=0.7, rim=(0.28, 0.10))
        p.setFont(qt_font(11))
        p.setPen(qc(pal.text))
        p.drawText(rect.adjusted(13, 0, -26, 0),
                   int(Qt.AlignmentFlag.AlignVCenter) | int(Qt.AlignmentFlag.AlignLeft),
                   self._value)
        draw_icon(p, "chevron", rect.right() - 14, rect.center().y(), 10,
                  qc(pal.text3))
        p.end()


class StatusDot(QWidget):
    """状态圆点。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(9, 9)
        self._kind = "info"
        self._pal = None

    def set_kind(self, kind: str) -> None:
        self._kind = kind
        self.update()

    def apply_theme(self, pal) -> None:
        self._pal = pal
        self.update()

    def _color(self, pal) -> QColor:
        s = pal.status
        return {
            "ok": qc(s.get("completed", "#30B55A")),
            "busy": qc(pal.accent),
            "warn": qc(s.get("paused", "#FF9F0A")),
            "err": qc(s.get("failed", "#FF3B30")),
            "info": qc(pal.text3),
        }.get(self._kind, qc(pal.text3))

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = self._pal
        if pal is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setBrush(self._color(pal))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        p.end()


class _ProgressBar(QWidget):
    """玻璃进度条：轨道 + 主色渐变填充；支持不确定态流动动画。"""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedHeight(6)
        self._value = 0.0
        self._indeterminate = False
        self._pos = 0.0
        self._pal = None
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(1300)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._on_tick)

    def _on_tick(self, v) -> None:
        self._pos = float(v)
        self.update()

    def set_value(self, pct: float) -> None:
        self._value = max(0.0, min(100.0, pct))
        self.update()

    def set_indeterminate(self, on: bool) -> None:
        if on == self._indeterminate:
            return
        self._indeterminate = on
        if on:
            self._anim.start()
        else:
            self._anim.stop()
            self._pos = 0.0
        self.update()

    def apply_theme(self, pal) -> None:
        self._pal = pal
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = self._pal
        if pal is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())
        track = qc(pal.track, 190)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(rect, 3, 3)
        if self._indeterminate:
            w = rect.width() * 0.32
            x = rect.left() + (rect.width() + w) * self._pos - w
            g = QLinearGradient(x, 0, x + w, 0)
            g.setColorAt(0.0, qc(pal.accent, 40))
            g.setColorAt(0.5, qc(pal.accent, 220))
            g.setColorAt(1.0, qc(pal.accent, 40))
            p.setBrush(QBrush(g))
            p.drawRoundedRect(QRectF(max(rect.left(), x), rect.top(),
                                     min(w, rect.right() - x), rect.height()), 3, 3)
        elif self._value > 0:
            g = QLinearGradient(rect.topLeft(), rect.topRight())
            g.setColorAt(0.0, qc(pal.accent))
            g.setColorAt(1.0, qc(pal.accent_hover))
            p.setBrush(QBrush(g))
            p.drawRoundedRect(
                QRectF(rect.left(), rect.top(),
                       rect.width() * self._value / 100.0, rect.height()), 3, 3)
        # 高光
        sheen = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.bottom()))
        sheen.setColorAt(0.0, QColor(255, 255, 255, 60))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(sheen))
        p.drawRoundedRect(rect, 3, 3)
        p.end()


class TaskRow(QWidget):
    """单个下载任务行（玻璃子卡 + 进度 + 暂停/恢复/取消）。"""

    STATUS_TEXT = {
        TaskStatus.PENDING: "等待中",
        TaskStatus.FETCHING: "获取链接…",
        TaskStatus.DOWNLOADING: "下载中",
        TaskStatus.PAUSED: "已暂停",
        TaskStatus.COMPLETED: "已完成",
        TaskStatus.FAILED: "失败",
        TaskStatus.CANCELLED: "已取消",
    }

    def __init__(self, task: DownloadTask, ambient: AmbientBackground,
                 on_pause_resume: Callable[[DownloadTask], None],
                 on_cancel: Callable[[DownloadTask], None],
                 parent: QWidget) -> None:
        super().__init__(parent)
        self.task = task
        self._pal = None
        self._hover = 0.0
        self.setFixedHeight(TASK_ROW_HEIGHT - 6)
        self.setCursor(Qt.CursorShape.ArrowCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 7, 8, 7)
        lay.setSpacing(10)

        # 状态图标芯片
        self.icon_chip = QLabel(self)
        self.icon_chip.setFixedSize(30, 30)
        self.icon_chip.setAlignment(int(Qt.AlignmentFlag.AlignCenter).__index__()
                                    if False else Qt.AlignmentFlag.AlignCenter)

        # 名称 + 进度
        mid = QVBoxLayout()
        mid.setSpacing(3)
        self.name_lbl = QLabel(self._display_name(), self)
        self.name_lbl.setFont(qt_font(11, bold=True))
        self.meta_lbl = QLabel("", self)
        self.meta_lbl.setFont(qt_font(9))
        self.bar = _ProgressBar(self)
        mid.addWidget(self.name_lbl)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.bar, 1)
        row.addWidget(self.meta_lbl, 0)
        mid.addLayout(row)
        lay.addLayout(mid, 1)

        # 操作按钮
        self.pause_btn = GlassIconButton("pause", size=26, parent=self)
        self.pause_btn.clicked.connect(lambda: on_pause_resume(self.task))
        self.cancel_btn = GlassIconButton("close", size=26, parent=self)
        self.cancel_btn.clicked.connect(lambda: on_cancel(self.task))
        lay.addWidget(self.pause_btn)
        lay.addWidget(self.cancel_btn)

        self.update_from_task()

    def _display_name(self) -> str:
        return f"{self.task.artist} - {self.task.title}"

    # ---- 状态刷新 ----

    def update_from_task(self) -> None:
        t = self.task
        self.name_lbl.setText(self._display_name())
        status = t.status
        if status == TaskStatus.DOWNLOADING and t.remark:
            # 下载已结束、后处理进行中（转码/歌词/元数据）
            meta = t.remark
        elif status == TaskStatus.DOWNLOADING and t.total_size > 0:
            meta = (f"{t.progress_pct:.1f}% · {format_speed(t.speed_bps)} · "
                    f"{t.downloaded // (1024 * 1024)}MB / {t.total_size // (1024 * 1024)}MB")
        elif status == TaskStatus.DOWNLOADING:
            meta = f"下载中 · {format_speed(t.speed_bps)}"
        elif status == TaskStatus.COMPLETED:
            meta = "已保存到下载目录"
        elif status == TaskStatus.FAILED and t.error:
            meta = t.error[:60]
        else:
            meta = self.STATUS_TEXT.get(status, "")
        self.meta_lbl.setText(meta)
        self.bar.set_indeterminate(status in (TaskStatus.FETCHING, TaskStatus.DOWNLOADING)
                                   and t.total_size <= 0)
        self.bar.set_value(t.progress_pct)
        can_pause = status in (TaskStatus.DOWNLOADING, TaskStatus.PAUSED)
        self.pause_btn.setVisible(can_pause)
        self.pause_btn.set_glyph("pause" if status == TaskStatus.DOWNLOADING else "play")
        self.cancel_btn.setVisible(status not in (TaskStatus.COMPLETED, TaskStatus.CANCELLED))
        self._chip_color()

    def _chip_color(self) -> None:
        if self._pal is None:
            return
        s = self._pal.status
        color = {
            TaskStatus.PENDING: s.get("pending", "#8E8E93"),
            TaskStatus.FETCHING: s.get("fetching", "#32ADE6"),
            TaskStatus.DOWNLOADING: s.get("downloading", "#0A84FF"),
            TaskStatus.PAUSED: s.get("paused", "#FF9F0A"),
            TaskStatus.COMPLETED: s.get("completed", "#30B55A"),
            TaskStatus.FAILED: s.get("failed", "#FF3B30"),
            TaskStatus.CANCELLED: s.get("pending", "#8E8E93"),
        }[self.task.status]
        pm = QPixmap(30, 30)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setBrush(QColor(color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(0, 0, 30, 30), 9, 9)
        draw_icon(p, "note", 15, 15, 13, QColor(255, 255, 255, 235))
        p.end()
        self.icon_chip.setPixmap(pm)

    def apply_theme(self, pal) -> None:
        self._pal = pal
        self.name_lbl.setStyleSheet(f"color: {pal.text}; background: transparent;")
        self.meta_lbl.setStyleSheet(f"color: {pal.text3}; background: transparent;")
        self.pause_btn.apply_theme(pal)
        self.cancel_btn.apply_theme(pal)
        self.bar.apply_theme(pal)
        self._chip_color()
        self.update()

    def enterEvent(self, _e) -> None:  # noqa: N802
        self._hover = 1.0
        self.update()

    def leaveEvent(self, _e) -> None:  # noqa: N802
        self._hover = 0.0
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = self._pal
        if pal is None:
            return
        p = QPainter(self)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        base = QColor(255, 255, 255)
        base.setAlpha(26 if pal.dark else 90)
        if self._hover:
            base = mix_qc(base, QColor(255, 255, 255), 0.35 * self._hover)
        paint_glass_surface(p, rect, 12, fill=base, sheen=0.6, rim=(0.20, 0.08))
        p.end()


# ==================== 打赏弹窗（玻璃） ====================


class TipDialogQ(GlassOverlay):
    """开发者打赏：渠道切换 → 收款码 → 状态反馈（与原版状态机一致）。"""

    WELL = 224

    def __init__(self, ambient: AmbientBackground, pal, store: TipRecordStore,
                 on_record: Optional[Callable[[str], None]] = None,
                 on_view_records: Optional[Callable[[], None]] = None,
                 on_close: Optional[Callable[[], None]] = None) -> None:
        super().__init__(ambient, 380, 566)
        self.store = store
        self.on_record = on_record
        self.on_close_cb = on_close
        self.closed.connect(self._emit_close)

        self._method = "wechat"
        self._phase = "pending"
        self._timer: Optional[QTimer] = None
        self._photos: dict[str, Optional[QPixmap]] = {}

        lay = self.content()
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(8)

        title = QLabel("支持开发者", self.panel)
        title.setFont(qt_font(15, bold=True))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub = QLabel("如果这款软件对你有帮助，欢迎请开发者喝杯咖啡", self.panel)
        sub.setFont(qt_font(9))
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 渠道切换
        chips = QHBoxLayout()
        chips.setSpacing(8)
        self._chips: dict[str, GlassButton] = {}
        for key, label in TIP_METHODS.items():
            chip = GlassButton(label, kind="ghost", small=True, width=150,
                               command=lambda k=key: self._select_method(k),
                               parent=self.panel)
            self._chips[key] = chip
            chips.addWidget(chip)

        # 白色扫码槽
        self.qr_lbl = QLabel(self.panel)
        self.qr_lbl.setFixedSize(self.WELL, self.WELL)
        self.qr_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.guide_lbl = QLabel("", self.panel)
        self.guide_lbl.setFont(qt_font(9))
        self.guide_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.guide_lbl.setWordWrap(True)

        self.status_lbl = QLabel("", self.panel)
        self.status_lbl.setFont(qt_font(10, bold=True))
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.confirm_btn = GlassButton("我已完成支付", kind="accent", width=150,
                                       command=self._confirm, parent=self.panel)
        self.fail_btn = GlassButton("支付遇到问题", kind="ghost",
                                    command=self._mark_failed, parent=self.panel)
        actions.addStretch(1)
        actions.addWidget(self.confirm_btn)
        actions.addWidget(self.fail_btn)
        actions.addStretch(1)

        footer = QHBoxLayout()
        self.records_btn = GlassButton("打赏记录", kind="ghost", small=True, glyph="clock",
                                       command=on_view_records, parent=self.panel)
        footer.addWidget(self.records_btn)
        footer.addStretch(1)

        note = QLabel("安全提示：仅展示个人收款码，全程离线完成，不收集任何支付信息；记录仅保存在本机。",
                      self.panel)
        note.setFont(qt_font(8))
        note.setWordWrap(True)
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)

        for w in (title, sub):
            lay.addWidget(w)
        lay.addSpacing(2)
        lay.addLayout(chips)
        lay.addWidget(self.qr_lbl, 0, Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.guide_lbl)
        lay.addWidget(self.status_lbl)
        lay.addLayout(actions)
        lay.addSpacing(4)
        lay.addLayout(footer)
        lay.addWidget(note)

        self._rows_themed = [title, sub, self.guide_lbl, self.status_lbl, note]
        self.apply_theme(pal)
        self._select_method(self._method)
        self._set_status("扫码后请在手机上确认金额并完成支付", "pending")

    # ---- 主题 ----

    def apply_theme(self, pal) -> None:
        self._pal = pal
        for w in self._rows_themed:
            w.setStyleSheet(f"color: {pal.text if w is self._rows_themed[0] else pal.text3};"
                            "background: transparent;")
        self.guide_lbl.setStyleSheet(f"color: {pal.text2}; background: transparent;")
        for chip in self._chips.values():
            chip.apply_theme(pal)
        self.confirm_btn.apply_theme(pal)
        self.fail_btn.apply_theme(pal)
        self.records_btn.apply_theme(pal)

    # ---- 状态机（与原版一致）----

    def _set_status(self, text: str, level: str) -> None:
        pal = self._pal
        color_map = {
            "pending": pal.text3,
            "processing": pal.status["paused"],
            "success": pal.status["completed"],
            "failed": pal.status["failed"],
        }
        self.status_lbl.setText(text)
        self.status_lbl.setStyleSheet(
            f"color: {color_map.get(level, pal.text2)}; background: transparent;")

    def _update_guide(self) -> None:
        app_name = "微信" if self._method == "wechat" else "支付宝"
        self.guide_lbl.setText(
            f"1. 打开{app_name}「扫一扫」扫描下方二维码\n"
            f"2. 在手机上自行输入金额并完成支付")

    def _select_method(self, method: str) -> None:
        if self._phase in ("processing", "success"):
            return
        self._method = method
        for key, chip in self._chips.items():
            chip.set_selected(key == method)
        self._show_qr(method)
        self._update_guide()

    def _load_qr(self, method: str) -> Optional[QPixmap]:
        if method in self._photos:
            return self._photos[method]
        path = TIP_QR_FILES.get(method, "")
        pm: Optional[QPixmap] = None
        if path and os.path.exists(path):
            pm = QPixmap(path)
            if pm.isNull():
                pm = None
        self._photos[method] = pm
        return pm

    def _show_qr(self, method: str) -> None:
        """白色物理扫码面：深浅色下均为纯白圆角槽。"""
        pm = self._load_qr(method)
        well = QPixmap(self.WELL, self.WELL)
        well.fill(Qt.GlobalColor.transparent)
        p = QPainter(well)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setBrush(QColor("#FFFFFF"))
        p.setPen(QPen(QColor(0, 0, 0, 30), 1))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.WELL - 1, self.WELL - 1), 14, 14)
        if pm is None:
            p.setPen(QColor("#3C3C43"))
            p.setFont(qt_font(9))
            p.drawText(QRectF(16, 0, self.WELL - 32, self.WELL),
                       int(Qt.AlignmentFlag.AlignCenter),
                       f"未找到{TIP_METHODS[method]}收款码图片\n应位于 assets/tip/ 目录")
        else:
            scaled = pm.scaled(self.WELL - 32, self.WELL - 32,
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap((self.WELL - scaled.width()) // 2,
                         (self.WELL - scaled.height()) // 2, scaled)
        p.end()
        self.qr_lbl.setPixmap(well)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for chip in self._chips.values():
            chip.setEnabled(enabled)
            chip.update()

    def _confirm(self) -> None:
        if self._phase == "success":
            self.close()
            return
        if self._phase == "failed":
            self._reset_pending()
            return
        if self._phase == "processing":
            return
        self._phase = "processing"
        self._set_controls_enabled(False)
        self.fail_btn.setEnabled(False)
        self.fail_btn.update()
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.update()
        self._set_status(f"支付确认中…{TIP_METHODS[self._method]}", "processing")
        self._timer = QTimer.singleShot(700, self._finish_success)

    def _finish_success(self) -> None:
        record = self.store.add(self._method, "success")
        if record is None:
            self._phase = "pending"
            self._set_status("记录保存失败，请检查程序目录写入权限", "failed")
            self.confirm_btn.setEnabled(True)
            self.fail_btn.setEnabled(True)
            self._set_controls_enabled(True)
            return
        self._phase = "success"
        self._set_status("已按你的确认记录本次打赏，感谢支持！", "success")
        self.guide_lbl.setText("如手机端实际未完成扣款，本条记录可在「打赏记录」中核对。")
        self.confirm_btn.setText("完成")
        self.confirm_btn.setEnabled(True)
        self.confirm_btn.update()
        self.fail_btn.setVisible(False)
        if self.on_record:
            self.on_record(f"收到一笔{TIP_METHODS[self._method]}打赏（本地记录）")

    def _mark_failed(self) -> None:
        if self._phase != "pending":
            return
        self.store.add(self._method, "failed")
        self._phase = "failed"
        self._set_status("支付未完成，已记录本次状态，可重新扫码或关闭", "failed")
        self.confirm_btn.setText("重新扫码")
        self.confirm_btn.setEnabled(True)
        self.confirm_btn.update()
        self.fail_btn.setVisible(False)
        if self.on_record:
            self.on_record("一笔打赏未完成（本地记录）")

    def _reset_pending(self) -> None:
        self._phase = "pending"
        self._set_controls_enabled(True)
        self.confirm_btn.setText("我已完成支付")
        self.confirm_btn.setEnabled(True)
        self.confirm_btn.update()
        self.fail_btn.setVisible(True)
        self.fail_btn.setEnabled(True)
        self._select_method(self._method)
        self._set_status("扫码后请在手机上确认金额并完成支付", "pending")

    def _emit_close(self) -> None:
        if self._timer is not None:
            self._timer = None
        if self.on_close_cb:
            self.on_close_cb()


class TipRecordsQ(GlassOverlay):
    """打赏登记记录窗口。"""

    def __init__(self, ambient: AmbientBackground, pal, store: TipRecordStore) -> None:
        super().__init__(ambient, 470, 420)
        self.store = store
        lay = self.content()
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("打赏记录", self.panel)
        title.setFont(qt_font(12, bold=True))
        self.summary_lbl = QLabel("", self.panel)
        self.summary_lbl.setFont(qt_font(9))
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.summary_lbl)
        lay.addLayout(head)

        self.tree = QTreeWidget(self.panel)
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["时间", "渠道", "状态"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tree.setFixedHeight(250)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(1, 120)
        self.tree.setColumnWidth(2, 80)
        lay.addWidget(self.tree)

        footer = QHBoxLayout()
        self.clear_btn = GlassButton("清空记录", kind="danger", small=True, glyph="trash",
                                     command=self._clear, parent=self.panel)
        self.close_btn = GlassButton("关闭", kind="ghost", small=True, width=90,
                                     command=self.close, parent=self.panel)
        footer.addWidget(self.clear_btn)
        footer.addStretch(1)
        footer.addWidget(self.close_btn)
        lay.addLayout(footer)

        self._title = title
        self.apply_theme(pal)
        self._reload()

    def apply_theme(self, pal) -> None:
        self._pal = pal
        self._title.setStyleSheet(f"color: {pal.text}; background: transparent;")
        self.summary_lbl.setStyleSheet(f"color: {pal.text2}; background: transparent;")
        self.tree.setStyleSheet(build_tree_qss(pal))
        self.clear_btn.apply_theme(pal)
        self.close_btn.apply_theme(pal)

    def _reload(self) -> None:
        self.tree.clear()
        for r in self.store.records:
            t_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ts"]))
            status_text = "成功" if r["status"] == "success" else "未完成"
            item = QTreeWidgetItem([t_str, TIP_METHODS.get(r["method"], r["method"]),
                                    status_text])
            item.setForeground(
                2, qc(self._pal.status.get("completed" if r["status"] == "success"
                                           else "failed", "#888888")))
            self.tree.addTopLevelItem(item)
        ok_n, fail_n = self.store.summary()
        total_n = ok_n + fail_n
        self.summary_lbl.setText(
            f"共 {total_n} 笔 · 成功 {ok_n} 笔"
            + (f" · 未完成 {fail_n} 笔" if fail_n else ""))

    def _clear(self) -> None:
        if not self.store.records:
            return
        ret = QMessageBox.question(
            self, "清空记录", "确定清空全部本地打赏记录吗？此操作不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ret == QMessageBox.StandardButton.Yes:
            self.store.clear()
            self._reload()


# ==================== 表格 / 日志 QSS ====================


def build_tree_qss(pal) -> str:
    # QHeaderView::section 置为 transparent 时 Qt 会回退到基础样式原生绘制
    # （浅色调色板 → 白底），必须显式给出与面板一致的半透明底色
    sec = qc(pal.card)
    sec_bg = f"rgba({sec.red()},{sec.green()},{sec.blue()},{110 if pal.dark else 160})"
    return f"""
    QTreeWidget {{
        background: transparent; border: none;
        color: {pal.text}; font-family: "{UI_FONT}"; font-size: 12px;
        outline: none;
    }}
    QTreeWidget::item {{ height: 30px; border-radius: 7px; padding: 0 4px; }}
    QTreeWidget::item:hover {{ background: rgba(127,127,127,{40 if pal.dark else 30}); }}
    QTreeWidget::item:selected {{
        background: {pal.accent_soft}; color: {pal.text};
    }}
    QHeaderView::section {{
        background: {sec_bg}; border: none;
        border-bottom: 1px solid {pal.divider};
        color: {pal.text2}; font-size: 11px; font-weight: 600;
        padding: 5px 6px;
    }}
    QHeaderView {{ background: transparent; border: none; }}
    QScrollBar:vertical {{
        background: transparent; width: 9px; margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: rgba(127,127,127,{90 if pal.dark else 70});
        border-radius: 3px; min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: rgba(127,127,127,130); }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    """


def build_log_qss(pal) -> str:
    return f"""
    QPlainTextEdit {{
        background: transparent; border: none;
        color: {pal.text2}; font-family: "{MONO_FONT}", "Menlo";
        font-size: 10px;
    }}
    QScrollBar:vertical {{ background: transparent; width: 8px; }}
    QScrollBar::handle:vertical {{
        background: rgba(127,127,127,{80 if pal.dark else 60});
        border-radius: 3px; min-height: 20px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    """


def build_scroll_qss() -> str:
    return """
    QScrollArea { background: transparent; border: none; }
    QScrollArea > QWidget > QWidget { background: transparent; }
    QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
    QScrollBar::handle:vertical {
        background: rgba(127,127,127,80); border-radius: 3px; min-height: 24px;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    """


def build_slider_qss(pal) -> str:
    """试听进度滑杆样式（槽 + 圆形手柄）。"""
    return f"""
    QSlider::groove:horizontal {{
        height: 4px; border-radius: 2px; background: {pal.divider};
    }}
    QSlider::sub-page:horizontal {{
        height: 4px; border-radius: 2px; background: {pal.accent};
    }}
    QSlider::handle:horizontal {{
        width: 12px; height: 12px; margin: -5px 0; border-radius: 6px;
        background: {pal.accent}; border: none;
    }}
    QSlider::handle:horizontal:hover {{
        width: 14px; height: 14px; margin: -6px 0; border-radius: 7px;
    }}
    """


class _HeaderIcon(QWidget):
    """品牌图标：优先使用品牌图标 PNG，缺失时退回 accent 圆角方块 + 音符。"""

    _brand_cache: Optional[QPixmap] = None

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(34, 34)
        self._pal = None

    @classmethod
    def _brand(cls) -> Optional[QPixmap]:
        if cls._brand_cache is None:
            pm = QPixmap(resource_path("assets", "icons", "icon_64.png"))
            cls._brand_cache = (
                pm.scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
                if not pm.isNull() else QPixmap()
            )
        return cls._brand_cache if not cls._brand_cache.isNull() else None

    def apply_theme(self, pal) -> None:
        self._pal = pal
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        brand = self._brand()
        if brand is not None:
            p.drawPixmap(1, 1, brand)
            p.end()
            return
        pal = self._pal
        if pal is None:
            p.end()
            return
        path = QPainterPath()
        path.addRoundedRect(QRectF(1, 1, 32, 32), pal.radius_icon, pal.radius_icon)
        p.fillPath(path, qc(pal.accent))
        draw_icon(p, "note", 17, 18, 16, qc(pal.accent_contrast))
        p.end()


class _GlassLabel(QLabel):
    """主题化文本标签。"""

    def __init__(self, text: str, *, px: int = 11, bold: bool = False,
                 role: str = "text", parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self._px, self._bold, self._role = px, bold, role
        self.setFont(qt_font(px, bold))
        self._pal = None

    def apply_theme(self, pal) -> None:
        self._pal = pal
        color = {"text": pal.text, "text2": pal.text2, "text3": pal.text3,
                 "accent": pal.accent}[self._role]
        self.setStyleSheet(f"color: {color}; background: transparent;")


# ==================== 线程信号总线 ====================


class _Bus(QObject):
    """后台线程 → UI 线程信号（跨线程自动排队）。"""

    search_ok = pyqtSignal(list)
    search_err = pyqtSignal(str)
    task_changed = pyqtSignal(str)
    tip_record = pyqtSignal(str)
    file_exists = pyqtSignal(object)  # DownloadTask，由下载线程触发，UI 线程处理
    detail_ready = pyqtSignal(object)  # (generation, uid)：音源详情已解析
    preview_ready = pyqtSignal(object)  # (url, title)
    preview_err = pyqtSignal(str)
    lyrics_ready = pyqtSignal(object)   # (generation, title, lrc_text|None)


# ==================== 下载设置弹窗 ====================


_CONVERT_LABELS = [
    ("不转码（保留原始格式）", CONVERT_OFF),
    ("自动转为 MP3", CONVERT_MP3),
    ("自动转为 FLAC", CONVERT_FLAC),
]


class SettingsDialog(QDialog):
    """下载设置：限速 + 转码 + 元数据/歌词。"""

    def __init__(self, parent: QWidget, pal, *, cfg: dict) -> None:
        super().__init__(parent)
        self.setWindowTitle("下载设置")
        self.setModal(True)
        self.setMinimumWidth(380)
        self._pal = pal
        self._build(cfg)
        self._apply_qss()

    def _build(self, cfg: dict) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)

        # ---- 限速 ----
        lay.addWidget(self._section_title("下载速度限制"))
        self.per_spin = self._spin_row(
            lay, "单任务限速", int(cfg.get("per_task_speed", 0) or 0))
        self.global_spin = self._spin_row(
            lay, "全局总限速", int(cfg.get("global_speed", 0) or 0))

        lay.addWidget(self._hline())

        # ---- 转码 ----
        lay.addWidget(self._section_title("音频格式转换（下载完成后自动执行）"))
        convert_mode = str(cfg.get("convert_mode", CONVERT_OFF) or CONVERT_OFF)
        self.convert_combo = QComboBox(self)
        for label, value in _CONVERT_LABELS:
            self.convert_combo.addItem(label, value)
        idx = max(0, self.convert_combo.findData(convert_mode))
        self.convert_combo.setCurrentIndex(idx)
        self.convert_combo.currentIndexChanged.connect(self._sync_bitrate_enabled)
        self._combo_row(lay, "转码格式", self.convert_combo)

        self.bitrate_combo = QComboBox(self)
        for br in MP3_BITRATES:
            self.bitrate_combo.addItem(f"{br} kbps", br)
        cur_br = int(cfg.get("mp3_bitrate", 320) or 320)
        self.bitrate_combo.setCurrentIndex(max(0, self.bitrate_combo.findData(cur_br)))
        self._combo_row(lay, "MP3 码率", self.bitrate_combo)
        self._sync_bitrate_enabled()

        ffmpeg_ok = ffmpeg_available()
        ff_hint = QLabel(
            "已检测到 ffmpeg，转码功能可用。" if ffmpeg_ok
            else "⚠ 未检测到 ffmpeg，转码将被跳过（可执行 brew install ffmpeg 安装）。",
            self,
        )
        ff_hint.setWordWrap(True)
        ff_hint.setFont(qt_font(9))
        lay.addWidget(ff_hint)

        lay.addWidget(self._hline())

        # ---- 元数据 / 歌词 ----
        lay.addWidget(self._section_title("元数据与歌词"))
        self.tags_chk = self._check_row(
            lay, "自动写入歌曲信息（歌名/歌手/专辑/年份）",
            bool(cfg.get("write_tags", True)))
        self.cover_chk = self._check_row(
            lay, "内嵌专辑封面到音频文件", bool(cfg.get("embed_cover", True)))
        self.lrc_chk = self._check_row(
            lay, "同步下载歌词并保存同名 .lrc 文件",
            bool(cfg.get("save_lrc", True)))
        self.embed_lrc_chk = self._check_row(
            lay, "歌词内嵌到音频标签（ID3 USLT / FLAC LYRICS）",
            bool(cfg.get("embed_lyrics", True)))

        row = QHBoxLayout()
        row.addStretch(1)
        from PyQt6.QtWidgets import QDialogButtonBox
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        lay.addLayout(row)

    def _section_title(self, text: str) -> QLabel:
        lbl = QLabel(text, self)
        lbl.setFont(qt_font(12, bold=True))
        return lbl

    def _hline(self) -> QFrame:
        div = QFrame(self)
        div.setFixedHeight(1)
        return div

    def _sync_bitrate_enabled(self) -> None:
        self.bitrate_combo.setEnabled(
            self.convert_combo.currentData() == CONVERT_MP3)

    def _spin_row(self, parent_lay: QVBoxLayout, label: str, value: int) -> QSpinBox:
        row = QHBoxLayout()
        row.setSpacing(10)
        lbl = QLabel(label, self)
        lbl.setFont(qt_font(11))
        spin = QSpinBox(self)
        spin.setRange(0, 102_400)  # 上限 100 MB/s
        spin.setSingleStep(64)
        spin.setSuffix(" KB/s")
        spin.setSpecialValueText("不限速")
        spin.setValue(max(0, int(value)))
        spin.setMinimumWidth(150)
        row.addWidget(lbl)
        row.addStretch(1)
        row.addWidget(spin)
        parent_lay.addLayout(row)
        return spin

    def _combo_row(self, parent_lay: QVBoxLayout,
                   label: str, combo: QComboBox) -> None:
        row = QHBoxLayout()
        row.setSpacing(10)
        lbl = QLabel(label, self)
        lbl.setFont(qt_font(11))
        combo.setMinimumWidth(220)
        row.addWidget(lbl)
        row.addStretch(1)
        row.addWidget(combo)
        parent_lay.addLayout(row)

    def _check_row(self, parent_lay: QVBoxLayout,
                   label: str, checked: bool) -> QCheckBox:
        chk = QCheckBox(label, self)
        chk.setChecked(checked)
        chk.setFont(qt_font(11))
        parent_lay.addWidget(chk)
        return chk

    def _apply_qss(self) -> None:
        pal = self._pal
        surface = pal.surface if hasattr(pal, "surface") else pal.card
        self.setStyleSheet(
            f"QDialog {{ background: {pal.card}; }}"
            f"QLabel {{ color: {pal.text}; background: transparent; }}"
            f"QSpinBox, QComboBox {{ color: {pal.text}; background: {surface};"
            f" border: 1px solid {pal.divider}; border-radius: 8px;"
            f" padding: 4px 8px; font-size: 12px; }}"
            "QSpinBox::up-button, QSpinBox::down-button { width: 18px; }"
            "QComboBox QAbstractItemView {"
            f" background: {surface}; color: {pal.text};"
            f" selection-background-color: {pal.accent_soft if hasattr(pal, 'accent_soft') else '#3a7bd5'};"
            "}"
            f"QCheckBox {{ color: {pal.text}; spacing: 8px; }}"
            "QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px;"
            f" border: 1px solid {pal.divider}; background: {surface}; }}"
            "QCheckBox::indicator:checked {"
            f" background: {getattr(pal, 'accent', '#0A84FF')}; border-color: transparent; }}"
        )

    def values(self) -> dict:
        return {
            "per_task_speed": self.per_spin.value(),
            "global_speed": self.global_spin.value(),
            "convert_mode": self.convert_combo.currentData() or CONVERT_OFF,
            "mp3_bitrate": int(self.bitrate_combo.currentData() or 320),
            "write_tags": self.tags_chk.isChecked(),
            "embed_cover": self.cover_chk.isChecked(),
            "save_lrc": self.lrc_chk.isChecked(),
            "embed_lyrics": self.embed_lrc_chk.isChecked(),
        }


# ==================== 歌词预览弹窗 ====================


class LyricsDialog(QDialog):
    """歌词预览：原始 LRC / 纯文本两种视图切换。"""

    def __init__(self, parent: QWidget, pal, *, title: str,
                 lrc: str, busy: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"歌词预览 · {title}")
        self.setModal(True)
        self.resize(460, 560)
        self._pal = pal
        self._lrc = lrc or ""
        self._plain = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        head = QHBoxLayout()
        name_lbl = QLabel(title, self)
        name_lbl.setFont(qt_font(13, bold=True))
        head.addWidget(name_lbl)
        head.addStretch(1)
        self.toggle_btn = QCheckBox("纯文本", self)
        self.toggle_btn.toggled.connect(self._on_toggle)
        head.addWidget(self.toggle_btn)
        lay.addLayout(head)

        self.view = QPlainTextEdit(self)
        self.view.setReadOnly(True)
        mono = QFont(MONO_FONT, 10)
        self.view.setFont(mono)
        lay.addWidget(self.view, 1)

        row = QHBoxLayout()
        self.hint_lbl = QLabel("", self)
        self.hint_lbl.setFont(qt_font(9))
        row.addWidget(self.hint_lbl)
        row.addStretch(1)
        from PyQt6.QtWidgets import QDialogButtonBox
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.accept)
        row.addWidget(buttons)
        lay.addLayout(row)

        if busy:
            self.view.setPlainText("正在搜索歌词…")
        elif not self._lrc:
            self.view.setPlainText("未找到该歌曲的歌词。")
        else:
            self._render()
        self._apply_qss()

    def set_lyrics(self, lrc: str | None) -> None:
        self._lrc = lrc or ""
        if not self._lrc:
            self.view.setPlainText("未找到该歌曲的歌词。")
            self.hint_lbl.setText("")
            return
        self._render()

    def _on_toggle(self, plain: bool) -> None:
        self._plain = plain
        self._render()

    def _render(self) -> None:
        if not self._lrc:
            return
        text = strip_lrc_timestamps(self._lrc) if self._plain else self._lrc
        self.view.setPlainText(text)
        lines = text.count("\n") + 1
        self.hint_lbl.setText(f"共 {lines} 行")

    def _apply_qss(self) -> None:
        pal = self._pal
        self.setStyleSheet(
            f"QDialog {{ background: {pal.card}; }}"
            f"QLabel {{ color: {pal.text}; background: transparent; }}"
            f"QPlainTextEdit {{ color: {pal.text};"
            f" background: {pal.surface if hasattr(pal, 'surface') else pal.card};"
            f" border: 1px solid {pal.divider}; border-radius: 10px;"
            " padding: 10px; }"
            f"QCheckBox {{ color: {pal.text}; spacing: 8px; }}"
        )


# ==================== 内置试听播放器 ====================


class PreviewPlayer(QObject):
    """QMediaPlayer 封装：网络 URL 直接流式播放。"""

    state_changed = pyqtSignal(int)
    position_changed = pyqtSignal(int)
    duration_changed = pyqtSignal(int)
    error_changed = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.audio_out = QAudioOutput()
        self.audio_out.setVolume(0.9)
        self.media = QMediaPlayer()
        self.media.setAudioOutput(self.audio_out)
        self.media.playbackStateChanged.connect(self.state_changed.emit)
        self.media.positionChanged.connect(self.position_changed.emit)
        self.media.durationChanged.connect(self.duration_changed.emit)
        self.media.errorOccurred.connect(lambda _e, msg: self.error_changed.emit(msg or "播放失败"))

    def play_url(self, url: str) -> None:
        self.media.setSource(QUrl(url))
        self.media.play()

    def toggle(self) -> None:
        if self.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media.pause()
        else:
            self.media.play()

    def stop(self) -> None:
        self.media.stop()

    def seek(self, ms: int) -> None:
        self.media.setPosition(int(ms))

    @property
    def is_playing(self) -> bool:
        return self.media.playbackState() == QMediaPlayer.PlaybackState.PlayingState


# ==================== 主窗口 ====================


class MainWindow(QMainWindow):
    """液态玻璃版音乐下载器主窗口（功能与原 tkinter 版对齐）。"""

    def __init__(self, demo: bool = False) -> None:
        super().__init__()
        self.demo = demo
        self.setWindowTitle(APP_TITLE + (" · 设计预览" if demo else ""))
        self.resize(WIN_WIDTH, WIN_HEIGHT)
        self.setMinimumSize(MIN_WIDTH, MIN_HEIGHT)

        # ---- 状态 ----
        self.theme = ThemeManager()
        self.search_results: list[dict[str, Any]] = []
        self.filtered_results: list[dict[str, Any]] = []
        self.search_history = SearchHistory()
        self.artist_history = ArtistHistory()
        self.tip_store = TipRecordStore()
        self._tip_win: Optional[TipDialogQ] = None
        self._tip_records_win: Optional[TipRecordsQ] = None
        self.download_dir: str = ensure_download_dir(
            load_settings().get("download_dir") or default_download_dir()
        )
        self._queue: Optional[DownloadQueue] = None
        self._task_rows: dict[str, TaskRow] = {}
        self._queue_running = False
        self._themed: list[Any] = []

        # 限速设置（KB/s，0 = 不限速）与全局限流器（跨队列共享）
        saved_cfg = load_settings()
        self._settings_cfg: dict[str, Any] = dict(saved_cfg)
        self.per_task_speed: int = int(saved_cfg.get("per_task_speed", 0) or 0)
        self.global_speed: int = int(saved_cfg.get("global_speed", 0) or 0)
        self._global_limiter = RateLimiter(self.global_speed * 1024)
        # 下载后处理选项（转码 / 歌词 / 元数据）
        self._post_options = PostOptions.from_config(self._settings_cfg)

        # 音源详情后台预取（音质/版本识别），generation 用于作废过期结果
        self._detail_gen = 0
        self._last_keyword = ""

        # 歌词预览
        self._lyrics_gen = 0
        self._lyrics_win: Optional[LyricsDialog] = None

        # 内置试听
        self.player = PreviewPlayer()
        self._preview_uid: Optional[int] = None
        self._preview_gen = 0

        # 同名文件冲突弹窗的跨线程同步（下载线程阻塞等待 UI 选择）
        self._fe_event: Optional[threading.Event] = None
        self._fe_choice: Optional[str] = None

        self.bus = _Bus()
        self.bus.search_ok.connect(self._on_search_ok)
        self.bus.search_err.connect(self._on_search_err)
        self.bus.task_changed.connect(self._on_task_changed)
        self.bus.tip_record.connect(self._on_tip_record)
        self.bus.file_exists.connect(self._on_file_exists_dialog)
        self.bus.detail_ready.connect(self._on_detail_ready)
        self.bus.preview_ready.connect(self._on_preview_ready)
        self.bus.preview_err.connect(self._on_preview_err)
        self.bus.lyrics_ready.connect(self._on_lyrics_ready)
        self.player.state_changed.connect(self._on_player_state)
        self.player.position_changed.connect(self._on_player_position)
        self.player.duration_changed.connect(self._on_player_duration)
        self.player.error_changed.connect(self._on_player_error)

        # ---- 骨架 ----
        self.ambient = AmbientBackground(self.theme)
        self.setCentralWidget(self.ambient)
        root = QVBoxLayout(self.ambient)
        root.setContentsMargins(18, 14, 18, 10)
        root.setSpacing(10)
        self._build_header(root)
        self._build_search(root)
        self._build_ctrl(root)
        self._build_results(root)
        self._build_actions(root)
        self._build_tasks(root)
        self._build_player(root)
        root.addLayout(self._build_status())
        self._build_log(root)

        self.theme.changed.connect(self._apply_theme)
        self._apply_theme()

        # 定时刷新实时速度（每 500ms），避免逐 chunk 刷 UI
        self._speed_timer = QTimer(self)
        self._speed_timer.setInterval(500)
        self._speed_timer.timeout.connect(self._refresh_speeds)
        self._speed_timer.start()

        self._set_status("准备就绪", "info")
        if demo:
            self._seed_demo()

    # ---------- UI 构建 ----------

    def _build_header(self, root: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.header_icon = _HeaderIcon()
        row.addWidget(self.header_icon)
        box = QVBoxLayout()
        box.setSpacing(0)
        self.title_lbl = _GlassLabel(APP_TITLE, px=15, bold=True)
        self.subtitle_lbl = _GlassLabel(APP_SUBTITLE, px=9, role="text3")
        box.addWidget(self.title_lbl)
        box.addWidget(self.subtitle_lbl)
        row.addLayout(box)
        row.addStretch(1)
        self.version_lbl = _GlassLabel(APP_VERSION, px=9, role="text3")
        row.addWidget(self.version_lbl)
        row.addSpacing(4)
        self.tip_btn = GlassIconButton("heart", accent=True, command=self._open_tip_dialog)
        self.settings_btn = GlassIconButton("gear", command=self._open_settings)
        self.theme_btn = GlassIconButton(self.theme.glyph, command=self._show_theme_menu)
        row.addWidget(self.tip_btn)
        row.addWidget(self.settings_btn)
        row.addWidget(self.theme_btn)
        root.addLayout(row)
        self._themed += [self.header_icon, self.title_lbl, self.subtitle_lbl,
                         self.version_lbl, self.tip_btn, self.settings_btn, self.theme_btn]

    def _build_search(self, root: QVBoxLayout) -> None:
        self.search_panel = GlassPanel(self.ambient, pad=(12, 10, 12, 10))
        row = QHBoxLayout()
        row.setSpacing(10)
        self.search_field = GlassField(placeholder="搜索歌曲、歌手…", trailing=True,
                                       on_trailing=self._show_search_history)
        self.search_field.returnPressed.connect(self._on_search)
        self.search_btn = GlassButton("搜索", kind="accent", glyph="search",
                                      width=104, command=self._on_search)
        row.addWidget(self.search_field, 1)
        row.addWidget(self.search_btn)
        self.search_panel.content.addLayout(row)
        root.addWidget(self.search_panel)
        self._themed += [self.search_field, self.search_btn]

    def _build_ctrl(self, root: QVBoxLayout) -> None:
        self.ctrl_panel = GlassPanel(self.ambient, pad=(12, 10, 12, 12), spacing=6)
        lay = self.ctrl_panel.content

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self.dir_lbl = _GlassLabel("目录", px=10, role="text2")
        self.path_field = GlassField(text=self.download_dir, small=True)
        self.path_field.returnPressed.connect(self._on_dir_changed)
        self.browse_btn = GlassButton("浏览", kind="ghost", glyph="folder",
                                      command=self._browse_dir)
        row1.addWidget(self.dir_lbl)
        row1.addWidget(self.path_field, 1)
        row1.addWidget(self.browse_btn)
        lay.addLayout(row1)

        div = QFrame(self.ctrl_panel)
        div.setFixedHeight(1)
        self._divider = div
        lay.addWidget(div)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.artist_lbl = _GlassLabel("歌手", px=10, role="text2")
        self.artist_filter = GlassSelect(self.ambient,
                                         ["全部"] + self.artist_history.get_all(),
                                         "全部", on_change=self._on_artist_select,
                                         width=150)
        self.source_lbl = _GlassLabel("平台", px=10, role="text2")
        self.source_filter = GlassSelect(self.ambient,
                                         ["全部"] + list(PLATFORM_NAMES),
                                         "全部", on_change=self._on_filter_change,
                                         width=124)
        self.quality_lbl = _GlassLabel("音质", px=10, role="text2")
        self.quality_filter = GlassSelect(
            self.ambient, [label for label, _tier in QUALITY_FILTERS],
            QUALITY_FILTER_ALL, on_change=self._on_filter_change, width=118,
        )
        row2.addWidget(self.artist_lbl)
        row2.addWidget(self.artist_filter)
        row2.addSpacing(8)
        row2.addWidget(self.source_lbl)
        row2.addWidget(self.source_filter)
        row2.addSpacing(8)
        row2.addWidget(self.quality_lbl)
        row2.addWidget(self.quality_filter)
        row2.addStretch(1)
        self.clear_filter_btn = GlassButton("清除筛选", kind="ghost", small=True,
                                            command=self._clear_filter)
        row2.addWidget(self.clear_filter_btn)
        lay.addLayout(row2)

        root.addWidget(self.ctrl_panel)
        self._themed += [self.dir_lbl, self.path_field, self.browse_btn,
                         self.artist_lbl, self.artist_filter,
                         self.source_lbl, self.source_filter,
                         self.quality_lbl, self.quality_filter,
                         self.clear_filter_btn]

    def _build_results(self, root: QVBoxLayout) -> None:
        self.results_panel = GlassPanel(self.ambient, pad=(12, 10, 12, 10))
        lay = self.results_panel.content

        head = QHBoxLayout()
        head.setSpacing(8)
        self.results_title = _GlassLabel("搜索结果", px=12, bold=True)
        self.count_lbl = _GlassLabel("", px=9, role="text2")
        head.addWidget(self.results_title)
        head.addWidget(self.count_lbl)
        head.addStretch(1)
        self.hint_lbl = _GlassLabel("⌘/Ctrl 多选 · 双击下载 · 选中后点试听", px=9, role="text3")
        head.addWidget(self.hint_lbl)
        lay.addLayout(head)

        self.tree = QTreeWidget(self.results_panel)
        self.tree.setColumnCount(6)
        self.tree.setHeaderLabels(["序号", "歌曲名", "歌手", "来源", "音质", "版本"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setUniformRowHeights(True)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tree.setColumnWidth(0, 52)
        self.tree.setColumnWidth(3, 104)
        self.tree.setColumnWidth(4, 72)
        self.tree.setColumnWidth(5, 84)
        self.tree.itemDoubleClicked.connect(lambda *_: self._on_download_selected())
        lay.addWidget(self.tree, 1)

        root.addWidget(self.results_panel, 5)
        self._themed += [self.results_title, self.count_lbl, self.hint_lbl,
                         self.results_panel]

    def _build_actions(self, root: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.preview_btn = GlassButton("试听", kind="tinted", glyph="play",
                                       width=84, command=self._on_preview_selected)
        self.lyrics_btn = GlassButton("歌词", kind="ghost", glyph="note",
                                      width=84, command=self._on_lyrics_selected)
        self.download_sel_btn = GlassButton("下载选中", kind="accent",
                                            glyph="download", width=116,
                                            command=self._on_download_selected)
        self.download_all_btn = GlassButton("全部下载", kind="tinted", glyph="download",
                                            width=116, command=self._on_download_all)
        self.open_dir_btn = GlassButton("打开目录", kind="ghost", glyph="folder",
                                        command=self._open_download_dir)
        self.clear_results_btn = GlassButton("清空结果", kind="ghost", glyph="trash",
                                             command=self._clear_results)
        for b in (self.preview_btn, self.lyrics_btn, self.download_sel_btn,
                  self.download_all_btn, self.open_dir_btn, self.clear_results_btn):
            row.addWidget(b)
        row.addStretch(1)
        root.addLayout(row)
        self.preview_btn.setEnabled(False)
        self.lyrics_btn.setEnabled(False)
        self.download_sel_btn.setEnabled(False)
        self.download_all_btn.setEnabled(False)
        self._themed += [self.preview_btn, self.lyrics_btn, self.download_sel_btn,
                         self.download_all_btn, self.open_dir_btn, self.clear_results_btn]

    def _build_tasks(self, root: QVBoxLayout) -> None:
        self.tasks_panel = GlassPanel(self.ambient, pad=(12, 10, 12, 10))
        lay = self.tasks_panel.content

        head = QHBoxLayout()
        head.setSpacing(6)
        self.tasks_title = _GlassLabel("下载任务", px=12, bold=True)
        head.addWidget(self.tasks_title)
        head.addStretch(1)
        self.total_speed_lbl = _GlassLabel("总速度 --", px=10, role="text2")
        head.addWidget(self.total_speed_lbl)
        head.addSpacing(10)
        self.pause_all_btn = GlassButton("暂停全部", kind="ghost", small=True,
                                         command=self._pause_all_tasks)
        self.cancel_all_btn = GlassButton("取消全部", kind="ghost", small=True,
                                          command=self._cancel_all_tasks)
        self.clear_done_btn = GlassButton("清除已完成", kind="ghost", small=True,
                                          command=self._clear_completed_tasks)
        for b in (self.pause_all_btn, self.cancel_all_btn, self.clear_done_btn):
            b.setEnabled(False)
            head.addWidget(b)
        lay.addLayout(head)

        self.task_scroll = QScrollArea(self.tasks_panel)
        self.task_scroll.setWidgetResizable(True)
        self.task_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.task_scroll.setStyleSheet(build_scroll_qss())
        self.rows_holder = QWidget(self.task_scroll)
        self.rows_lay = QVBoxLayout(self.rows_holder)
        self.rows_lay.setContentsMargins(0, 0, 0, 0)
        self.rows_lay.setSpacing(6)
        self.empty_lbl = _GlassLabel("暂无下载任务", px=10, role="text3")
        self.rows_lay.addWidget(self.empty_lbl)
        self.rows_lay.addStretch(1)
        self.task_scroll.setWidget(self.rows_holder)
        self.task_scroll.setFixedHeight(MAX_TASK_PANEL_HEIGHT)
        lay.addWidget(self.task_scroll, 1)

        root.addWidget(self.tasks_panel, 3)
        self._themed += [self.tasks_title, self.total_speed_lbl,
                         self.pause_all_btn, self.cancel_all_btn,
                         self.clear_done_btn, self.empty_lbl, self.tasks_panel]

    def _build_player(self, root: QVBoxLayout) -> None:
        """内置试听迷你播放条（默认隐藏，首次试听时显示）。"""
        self.player_panel = GlassPanel(self.ambient, pad=(10, 7, 10, 7))
        row = QHBoxLayout()
        row.setSpacing(9)

        self.player_note = _GlassLabel("♪", px=14, bold=True)
        self.player_title_lbl = _GlassLabel("未在试听", px=11, bold=True)
        self.player_title_lbl.setMinimumWidth(180)
        self.player_play_btn = GlassIconButton("play", size=28,
                                               command=self._player_toggle)
        self.player_stop_btn = GlassIconButton("stop", size=28,
                                               command=self._player_stop)
        self.player_slider = QSlider(Qt.Orientation.Horizontal, self.player_panel)
        self.player_slider.setRange(0, 0)
        self.player_slider.setFixedHeight(20)
        self._player_seeking = False
        self.player_slider.sliderPressed.connect(self._player_slider_pressed)
        self.player_slider.sliderReleased.connect(self._player_seek)
        self.player_time_lbl = _GlassLabel("00:00 / 00:00", px=9, role="text3")
        self.player_time_lbl.setFixedWidth(96)
        self.player_close_btn = GlassIconButton("close", size=24,
                                                command=self._player_close)

        row.addWidget(self.player_note)
        row.addWidget(self.player_play_btn)
        row.addWidget(self.player_stop_btn)
        row.addWidget(self.player_slider, 1)
        row.addWidget(self.player_time_lbl)
        row.addWidget(self.player_title_lbl, 0)
        row.addWidget(self.player_close_btn)
        self.player_panel.content.addLayout(row)
        self.player_panel.setVisible(False)
        root.addWidget(self.player_panel)
        self._themed += [self.player_panel, self.player_note, self.player_title_lbl,
                         self.player_play_btn, self.player_stop_btn,
                         self.player_time_lbl, self.player_close_btn]

    def _build_status(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        self.status_dot = StatusDot()
        self.status_lbl = _GlassLabel("", px=9, role="text2")
        row.addWidget(self.status_dot)
        row.addWidget(self.status_lbl)
        row.addStretch(1)
        self._themed += [self.status_dot, self.status_lbl]
        return row

    def _build_log(self, root: QVBoxLayout) -> None:
        self.log_panel = GlassPanel(self.ambient, pad=(12, 8, 12, 8), spacing=4)
        self.log_title = _GlassLabel("日志", px=11, bold=True)
        self.log_panel.content.addWidget(self.log_title)
        self.log_text = QPlainTextEdit(self.log_panel)
        self.log_text.setReadOnly(True)
        self.log_text.setFont(mono_qfont(10))
        self.log_text.setFixedHeight(76)
        self.log_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.log_panel.content.addWidget(self.log_text)
        root.addWidget(self.log_panel)
        self._themed += [self.log_title, self.log_text, self.log_panel]

    # ---------- 主题 ----------

    def _apply_theme(self) -> None:
        pal = self.theme.palette
        sync_app_palette(pal, self.theme.theme_mode)
        self.theme_btn.set_glyph(self.theme.glyph)
        self._divider.setStyleSheet(f"background: {pal.divider};")
        self.tree.setStyleSheet(build_tree_qss(pal))
        self.log_text.setStyleSheet(build_log_qss(pal))
        self.task_scroll.setStyleSheet(build_scroll_qss())
        self.player_slider.setStyleSheet(build_slider_qss(pal))
        radius = pal.radius_card
        for panel in (self.search_panel, self.ctrl_panel, self.results_panel,
                      self.tasks_panel, self.player_panel, self.log_panel):
            panel.set_radius(radius)
        for w in self._themed:
            if hasattr(w, "apply_theme"):
                w.apply_theme(pal)
        for row in self._task_rows.values():
            row.apply_theme(pal)
        if self._tip_win is not None:
            self._tip_win.apply_theme(pal)
        if self._tip_records_win is not None:
            self._tip_records_win.apply_theme(pal)
        self.ambient.scene_pixmap()  # 同步重建背景像素（约 20ms）
        self.ambient.update()        # 新配色背景即时上屏（即时反馈）
        self.ambient.refresh_glass()  # 面板折射派发到线程池，不阻塞 UI

    # ---------- 状态与日志 ----------

    def _set_status(self, text: str, kind: str = "info") -> None:
        self.status_lbl.setText(text)
        self.status_dot.set_kind(kind)

    def _log(self, message: str) -> None:
        self.log_text.appendPlainText(message)

    # ---------- 设计预览 ----------

    def _seed_demo(self) -> None:
        demo_songs = [
            # (歌名, 歌手, 平台, 音质标签, 是否有链接, 版本标记, 版本词)
            ("晴天", "周杰伦", "咪咕音乐", "320K", True, "", ""),
            ("晴天", "周杰伦", "网易云音乐", "LOSSLESS", True, "", ""),
            ("晴天", "周杰伦", "QQ音乐", "320K", False, "", ""),
            ("富士山下", "陈奕迅", "网易云音乐", "LOSSLESS", True, "", ""),
            ("江南", "林俊杰", "QQ音乐", "320K", False, "variant", "live"),
            ("光年之外", "G.E.M. 邓紫棋", "酷我音乐", "LOSSLESS", True, "", ""),
            ("起风了", "买辣椒也用券", "咪咕音乐", "320K", False, "", ""),
            ("夜曲", "周杰伦", "酷我音乐", "320K", True, "bad", "伴奏"),
        ]
        self.search_results = []
        for t, a, s, q, has_url, vtag, vlabel in demo_songs:
            song = {"title": t, "artist": a, "source_name": s, "quality": q}
            if has_url:
                song["audio_url"] = "https://example.invalid/demo.mp3"
            if vtag:
                song["version_tag"] = vtag
                song["version_label"] = vlabel
            song["_uid"] = id(song)
            self.search_results.append(song)
        self.filtered_results = list(self.search_results)
        self._populate_tree(self.search_results)
        self.artist_filter.set_values(["全部"] + sorted({s[1] for s in demo_songs}))
        self.source_filter.set_values(["全部"] + list(PLATFORM_NAMES))
        self.preview_btn.setEnabled(True)
        self.lyrics_btn.setEnabled(True)
        self.download_sel_btn.setEnabled(True)
        self.download_all_btn.setEnabled(True)

        demo_tasks = [
            ("晴天", "周杰伦", "咪咕音乐", "320K",
             TaskStatus.DOWNLOADING, 8_400_000, 5_800_000, 1_350_000),
            ("富士山下", "陈奕迅", "网易云音乐", "LOSSLESS",
             TaskStatus.FETCHING, 0, 0, 0),
            ("江南", "林俊杰", "QQ音乐", "320K",
             TaskStatus.PAUSED, 5_200_000, 1_560_000, 0),
            ("光年之外", "G.E.M. 邓紫棋", "酷我音乐", "LOSSLESS",
             TaskStatus.COMPLETED, 26_300_000, 26_300_000, 0),
        ]
        for i, (title, artist, source, quality, status,
                total, done, speed) in enumerate(demo_tasks):
            task = DownloadTask(
                task_id=f"demo-{i}", title=title, artist=artist,
                source=source, quality=quality,
                audio_url="https://example.invalid/demo.mp3",
            )
            task.status = status
            task.total_size = total
            task.downloaded = done
            task.speed_bps = float(speed)
            self._add_task_row(task)
        self.total_speed_lbl.setText("总速度 1.3 MB/s")

        self._set_status("设计预览：演示数据已载入（搜索/下载不会真正发起）", "info")
        self._log("已进入设计预览模式")
        self._log(f"当前方案: {SCHEMES[self.theme.scheme_key]['name']} · "
                  f"外观: {dict(THEME_MODES)[self.theme.theme_mode]}")
        self._log("点击右上角圆形按钮可切换 3 套设计方案与浅色/深色外观")

    # ---------- 搜索历史 / 目录 ----------

    def _show_search_history(self) -> None:
        history = self.search_history.get_all()
        if not history:
            self._log("暂无搜索历史")
            return
        pal = self.theme.palette
        menu = GlassMenu(
            self.ambient, pal,
            [(None, [(k, k, False) for k in history])],
            self._on_history_pick, min_width=self.search_field.width() - 20,
        )
        gl = self.search_field.mapToGlobal(QPoint(6, self.search_field.height() + 4))
        menu.open_at(gl)

    def _on_history_pick(self, key: str) -> None:
        self.search_field.set(key)
        self._on_search()

    def _browse_dir(self) -> None:
        dir_path = QFileDialog.getExistingDirectory(self, "选择下载目录", self.download_dir)
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
            except Exception as e:  # noqa: BLE001
                self._log(f"无法创建目录: {e}")
                self.path_field.set(self.download_dir)

    def _open_download_dir(self) -> None:
        if not os.path.exists(self.download_dir):
            return
        if sys.platform == "darwin":
            subprocess.run(["open", self.download_dir], check=False)
        elif sys.platform == "win32":
            subprocess.run(["explorer", os.path.normpath(self.download_dir)], check=False)
        else:
            subprocess.run(["xdg-open", self.download_dir], check=False)

    # ---------- 筛选 ----------

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

    def _quality_min_tier(self) -> str:
        """当前音质筛选对应的最低 tier；空串表示“全部”。"""
        label = self.quality_filter.get()
        for lab, tier in QUALITY_FILTERS:
            if lab == label:
                return tier
        return ""

    @staticmethod
    def _song_tier(song: dict[str, Any]) -> str:
        return quality_tier(str(song.get("quality", "") or ""),
                            str(song.get("audio_url", "") or ""))

    def _version_of(self, song: dict[str, Any]) -> tuple[str, str]:
        """返回 (level, marker)：优先用详情标记，否则按标题即时识别。"""
        tag = str(song.get("version_tag", "") or "")
        marker = str(song.get("version_label", "") or "")
        if tag:
            return tag, marker
        title = song.get("title", "") or song.get("name", "")
        return detect_version_risk(title, self._last_keyword)

    def _update_filter_options(self) -> None:
        # 歌手下拉仅列当前搜索结果中实际存在的歌手，避免历史歌手选后无结果
        artists: set[str] = set()
        for song in self.search_results:
            artist = song.get("artist", "") or song.get("singer", "")
            if artist:
                self.artist_history.add(artist)
                artists.add(artist)
        self.artist_filter.set("全部")
        self.source_filter.set("全部")
        self.quality_filter.set(QUALITY_FILTER_ALL)
        self.artist_filter.set_values(["全部"] + sorted(artists))
        self.source_filter.set_values(["全部"] + list(PLATFORM_NAMES))

    def _on_filter_change(self, _value: Optional[str] = None) -> None:
        artist_filter = self.artist_filter.get()
        source_filter = self.source_filter.get()
        min_tier = self._quality_min_tier()
        self.filtered_results = []
        for song in self.search_results:
            if artist_filter != "全部":
                artist = song.get("artist", "") or song.get("singer", "")
                if artist_filter not in artist:
                    continue
            if source_filter != "全部":
                if source_filter != song.get("source_name", ""):
                    continue
            if min_tier:
                tier = self._song_tier(song)
                # 选定具体音质后，音质未知的音源不展示（避免混入不符合要求的文件）
                if tier == TIER_UNKNOWN or TIER_ORDER[tier] < TIER_ORDER[min_tier]:
                    continue
            self.filtered_results.append(song)
        self._populate_tree(self.filtered_results)
        active: list[str] = []
        if artist_filter != "全部":
            active.append(f"歌手={artist_filter}")
        if source_filter != "全部":
            active.append(f"平台={source_filter}")
        if min_tier:
            active.append(f"音质≥{TIER_LABELS[min_tier]}")
        state = " · ".join(active) if active else "无筛选"
        self._set_status(f"筛选结果: {len(self.filtered_results)} 首（{state}）")

    def _clear_filter(self) -> None:
        self.artist_filter.set("全部")
        self.source_filter.set("全部")
        self.quality_filter.set(QUALITY_FILTER_ALL)
        self._on_filter_change()

    def _clear_results(self) -> None:
        # 作废上一批后台预取结果
        self._detail_gen += 1
        self.tree.clear()
        self.search_results = []
        self.filtered_results = []
        self.count_lbl.setText("")
        self.preview_btn.setEnabled(False)
        self.lyrics_btn.setEnabled(False)
        self.download_sel_btn.setEnabled(False)
        self.download_all_btn.setEnabled(False)
        self._set_status("准备就绪", "info")

    # ---------- 搜索 ----------

    def _on_search(self) -> None:
        keyword = self.search_field.get().strip()
        if not keyword:
            QMessageBox.warning(self, "提示", "请输入要搜索的歌曲名")
            return
        self.search_history.add(keyword)
        self._last_keyword = keyword
        self.search_btn.setEnabled(False)
        self._clear_results()
        self._log(f"正在搜索: {keyword}")
        self._set_status("正在搜索…", "busy")
        threading.Thread(target=self._search_worker, args=(keyword,),
                         daemon=True).start()

    def _search_worker(self, keyword: str) -> None:
        try:
            results = search_all_platforms(keyword)
            self.bus.search_ok.emit(results)
        except Exception as e:  # noqa: BLE001
            self.bus.search_err.emit(str(e))

    def _on_search_ok(self, results: list) -> None:
        self.search_results = results
        self.filtered_results = results.copy()
        if results:
            for song in results:
                song["_uid"] = id(song)
            self._populate_tree(results)
            self._update_filter_options()
            self._set_status(f"找到 {len(results)} 首歌曲", "ok")
            self.preview_btn.setEnabled(True)
            self.lyrics_btn.setEnabled(True)
            self.download_sel_btn.setEnabled(True)
            self.download_all_btn.setEnabled(True)
            self._log(f"搜索完成: 共 {len(results)} 首歌曲（四平台交错排列）")
            # 后台并发预取音源详情（音质/版本），完成后逐条刷新，不阻塞列表
            self._start_detail_prefetch(results)
        else:
            # 无结果：清空旧数据并重置筛选，避免旧结果/旧筛选残留
            self.search_results = []
            self.filtered_results = []
            self.tree.clear()
            self.count_lbl.setText("")
            self.preview_btn.setEnabled(False)
            self.lyrics_btn.setEnabled(False)
            self.download_sel_btn.setEnabled(False)
            self.download_all_btn.setEnabled(False)
            self.artist_filter.set("全部")
            self.source_filter.set("全部")
            self.quality_filter.set(QUALITY_FILTER_ALL)
            self.artist_filter.set_values(["全部"])
            self.source_filter.set_values(["全部"] + list(PLATFORM_NAMES))
            self._log("未找到相关歌曲，请更换关键词")
            self._set_status("未找到相关歌曲", "warn")
        self.search_btn.setEnabled(True)
        self.search_btn.update()

    def _start_detail_prefetch(self, songs: list[dict[str, Any]]) -> None:
        """线程池并发解析无链接歌曲的详情，结果经信号回 UI 线程。"""
        gen = self._detail_gen
        targets = [s for s in songs if not s.get("audio_url")]
        if not targets:
            return

        def _worker() -> None:
            pool = ThreadPoolExecutor(max_workers=DETAIL_WORKERS)
            futs = {pool.submit(resolve_song, s): s for s in targets}
            try:
                for fut in as_completed(futs):
                    # 新搜索发起后旧批次立即作废，未开始的任务直接取消
                    if gen != self._detail_gen:
                        break
                    song = futs[fut]
                    try:
                        detail = fut.result()
                    except Exception:  # noqa: BLE001
                        detail = None
                    if detail:
                        song["audio_url"] = detail.get("audio_url", "")
                        if detail.get("quality"):
                            song["quality"] = detail["quality"]
                        song["version_tag"] = detail.get("version_tag", "")
                        song["version_label"] = detail.get("version_label", "")
                    else:
                        song["_detail_failed"] = True
                    self.bus.detail_ready.emit((gen, song["_uid"]))
            finally:
                # 不等待在途请求（守护线程，随进程退出；单请求有超时兜底）
                pool.shutdown(wait=False, cancel_futures=True)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_detail_ready(self, payload: object) -> None:
        gen, uid = payload
        if gen != self._detail_gen:
            return
        if not any(s.get("_uid") == uid for s in self.search_results):
            return
        # 保留当前选中项与筛选条件，仅刷新展示
        selected_uids = self._selected_uids()
        self._on_filter_change()
        self._reselect_uids(selected_uids)

    def _on_search_err(self, err: str) -> None:
        self._log(f"搜索出错: {err}")
        self._set_status("搜索出错", "err")
        self.search_btn.setEnabled(True)

    def _populate_tree(self, songs: list[dict[str, Any]]) -> None:
        bad_brush = QBrush(QColor("#ff5a5f"))
        variant_brush = QColor("#f0a93b")
        self.tree.clear()
        for idx, song in enumerate(songs, 1):
            title = song.get("title", "") or song.get("name", "")
            artist = song.get("artist", "") or song.get("singer", "")
            source = song.get("source_name", song.get("source", "?"))
            tier = self._song_tier(song)
            tag, marker = self._version_of(song)
            if tag == "bad":
                version_text = f"⚠ {marker or '伴奏'}"
            elif tag == "variant":
                version_text = marker or "变体"
            else:
                version_text = "—"
            item = QTreeWidgetItem(
                [str(idx), title, artist, source, TIER_LABELS[tier], version_text]
            )
            item.setTextAlignment(0, int(Qt.AlignmentFlag.AlignCenter))
            item.setTextAlignment(4, int(Qt.AlignmentFlag.AlignCenter))
            item.setTextAlignment(5, int(Qt.AlignmentFlag.AlignCenter))
            item.setData(0, Qt.ItemDataRole.UserRole, song.get("_uid", idx - 1))
            if tag == "bad":
                item.setForeground(5, bad_brush)
            elif tag == "variant":
                item.setForeground(5, QBrush(variant_brush))
            self.tree.addTopLevelItem(item)
        self.count_lbl.setText(f"{len(songs)} 首")

    def _selected_uids(self) -> set[int]:
        return {
            it.data(0, Qt.ItemDataRole.UserRole)
            for it in self.tree.selectedItems()
        }

    def _reselect_uids(self, uids: set[int]) -> None:
        if not uids:
            return
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.data(0, Qt.ItemDataRole.UserRole) in uids:
                it.setSelected(True)

    # ---------- 下载（加入队列） ----------

    def _songs_by_uids(self, uids: set[int]) -> list[dict[str, Any]]:
        return [s for s in self.filtered_results if s.get("_uid") in uids]

    def _on_download_selected(self) -> None:
        selected = self.tree.selectedItems()
        if not selected:
            QMessageBox.warning(self, "提示", "请先在表格中选择要下载的歌曲")
            return
        songs = self._songs_by_uids(self._selected_uids())
        if songs:
            self._add_songs_to_queue(songs)

    def _on_download_all(self) -> None:
        if not self.filtered_results:
            QMessageBox.warning(self, "提示", "没有可下载的歌曲")
            return
        self._add_songs_to_queue(list(self.filtered_results))

    def _ensure_queue(self) -> DownloadQueue:
        """获取或创建下载队列（含限速、全局限流器、后处理配置）。"""
        if self._queue is None:
            self._queue = DownloadQueue(
                directory=self.download_dir,
                per_task_limit=self.per_task_speed * 1024,
                global_limiter=self._global_limiter,
                post_options=self._post_options,
            )
            self._queue.on_progress = self._on_queue_progress
            self._queue.on_status_change = self._on_queue_status_change
            self._queue.on_file_exists = self._on_queue_file_exists
        else:
            self._queue.set_limits(self.per_task_speed * 1024,
                                   self.global_speed * 1024)
            self._queue.set_post_options(self._post_options)
        self._queue.directory = ensure_download_dir(self.download_dir)
        return self._queue

    @staticmethod
    def _build_song_meta(song: dict[str, Any], title: str,
                         artist: str, detail: dict[str, Any] | None) -> dict[str, Any]:
        """从搜索项/详情组装后处理元数据（专辑/年份/封面/歌词身份）。"""
        def pick(key: str) -> Any:
            if detail and detail.get(key):
                return detail[key]
            return song.get(key)
        return {
            "title": title,
            "artist": artist,
            "album": str(pick("album") or ""),
            "year": str(pick("year") or ""),
            "cover_url": str(pick("cover") or ""),
            "lrc_url": str(pick("lrc_url") or ""),
            "source": song.get("source", ""),
            "song_id": song.get("song_id"),
            "rid": song.get("rid"),
            "song_mid": song.get("song_mid"),
        }

    def _add_songs_to_queue(self, songs: list[dict[str, Any]]) -> None:
        queue = self._ensure_queue()

        added = 0
        for song in songs:
            title = song.get("title", "") or song.get("name", "")
            artist = song.get("artist", "") or song.get("singer", "")
            source = song.get("source_name", song.get("source", "?"))
            quality = song.get("quality", "?")
            audio_url = song.get("audio_url", "")
            detail = None
            if not audio_url:
                detail = resolve_song(song)
            if detail is not None:
                audio_url = detail.get("audio_url", "")
                title = detail.get("title", title)
                artist = detail.get("artist", artist)
                quality = detail.get("quality", quality)
                tag = str(detail.get("version_tag", "") or "")
                marker = str(detail.get("version_label", "") or "")
            else:
                # 预取链接或解析失败：以本地标题识别兜底版本校验
                tag, marker = self._version_of(song)
            # 高置信伴奏/无人声音源一律拦截
            if tag == "bad":
                self._log(f"已拦截疑似伴奏/无人声版本（{marker}）: {artist} - {title}")
                continue
            if not audio_url:
                self._log(f"无法获取下载链接: {artist} - {title}")
                continue
            if tag == "variant":
                self._log(f"提示：变体版本（{marker}）: {artist} - {title}")
            meta = self._build_song_meta(song, title, artist, detail)
            task = queue.add_task(
                title=title, artist=artist, audio_url=audio_url,
                quality=quality, source=source, meta=meta,
            )
            self._add_task_row(task)
            added += 1

        if added == 0:
            self._log("没有可下载的歌曲（无法获取链接或均为伴奏版本）")
            return
        self._log(f"已添加 {added} 首到下载队列")
        self._update_queue_buttons()
        if not self._queue_running:
            self._queue_running = True
            queue.start_async()

    # ---------- 任务面板 ----------

    def _sync_empty_state(self) -> None:
        # 占位提示与任务条目互斥：有行即隐藏，无行即显示
        self.empty_lbl.setVisible(not self._task_rows)

    def _add_task_row(self, task: DownloadTask) -> None:
        row = TaskRow(task, self.ambient,
                      self._on_task_pause_resume, self._on_task_cancel,
                      self.rows_holder)
        # stretch 占位之前插入，保持新增任务在最下、stretch 收尾
        self.rows_lay.insertWidget(self.rows_lay.count() - 1, row)
        self._task_rows[task.task_id] = row
        self._sync_empty_state()
        row.apply_theme(self.theme.palette)
        row.update_from_task()

    def _find_task(self, task_id: str) -> Optional[DownloadTask]:
        if self._queue is None:
            return None
        for t in self._queue.tasks:
            if t.task_id == task_id:
                return t
        return None

    # ---------- 队列回调（线程 → 信号） ----------

    def _on_queue_progress(self, task: DownloadTask) -> None:
        self.bus.task_changed.emit(task.task_id)

    def _on_queue_status_change(self, task: DownloadTask) -> None:
        self.bus.task_changed.emit(task.task_id)

    def _on_queue_file_exists(self, task: DownloadTask) -> str:
        """下载线程回调：发现同名文件时请求 UI 决策，阻塞等待返回。"""
        event = threading.Event()
        self._fe_event = event
        self._fe_choice = None
        self.bus.file_exists.emit(task)
        event.wait()
        return self._fe_choice or "skip"

    def _on_file_exists_dialog(self, task: DownloadTask) -> None:
        """UI 线程槽：弹出冲突选择框，回写结果并唤醒下载线程。"""
        choice = self._show_overwrite_dialog(task)
        self._fe_choice = choice
        if self._fe_event is not None:
            self._fe_event.set()

    def _show_overwrite_dialog(self, task: DownloadTask) -> str:
        """同名文件冲突三选一对话框，返回 overwrite / skip / rename。"""
        name = os.path.basename(task.filepath)
        dlg = QMessageBox(self)
        dlg.setWindowTitle("同名文件已存在")
        dlg.setIcon(QMessageBox.Icon.Warning)
        dlg.setText(f"检测到当前路径已存在同名歌曲文件：\n{name}")
        dlg.setInformativeText("请选择处理方式：")
        btn_overwrite = dlg.addButton(
            "覆盖现有文件", QMessageBox.ButtonRole.AcceptRole)
        btn_skip = dlg.addButton(
            "保留现有文件并取消本次下载", QMessageBox.ButtonRole.RejectRole)
        btn_rename = dlg.addButton(
            "保留现有文件并将新文件重命名下载", QMessageBox.ButtonRole.ActionRole)
        dlg.exec()
        clicked = dlg.clickedButton()
        if clicked is btn_rename:
            return "rename"
        if clicked is btn_overwrite:
            return "overwrite"
        return "skip"

    def _on_task_changed(self, task_id: str) -> None:
        row = self._task_rows.get(task_id)
        task = self._find_task(task_id)
        if row is not None and task is not None:
            row.update_from_task()
        self._check_queue_done()

    def _check_queue_done(self) -> None:
        if self._queue is None:
            return
        active = sum(
            1 for t in self._queue.tasks
            if t.status.value in ("pending", "fetching", "downloading", "paused")
        )
        if active == 0 and self._queue_running:
            self._queue_running = False
            self._log("下载队列全部完成")
            self._set_status("下载队列全部完成", "ok")
        self._update_queue_buttons()

    def _update_queue_buttons(self) -> None:
        if self._queue is None or not self._task_rows:
            for b in (self.pause_all_btn, self.cancel_all_btn, self.clear_done_btn):
                b.setEnabled(False)
            return
        tasks = self._queue.tasks
        has_active = any(t.status.value in ("fetching", "downloading") for t in tasks)
        has_paused = any(t.status.value == "paused" for t in tasks)
        has_done = any(t.status.value in ("completed", "failed", "cancelled")
                       for t in tasks)
        self.pause_all_btn.setEnabled(has_active or has_paused)
        self.cancel_all_btn.setEnabled(bool(self._task_rows))
        self.clear_done_btn.setEnabled(has_done)

    # ---------- 任务操作 ----------

    def _on_task_pause_resume(self, task: DownloadTask) -> None:
        if task.status == TaskStatus.DOWNLOADING:
            task.pause()
            self._log(f"暂停: {task.display_name}")
        elif task.status == TaskStatus.PAUSED:
            task.resume_after_pause()
            self._log(f"恢复: {task.display_name}")
        self._on_task_changed(task.task_id)

    def _on_task_cancel(self, task: DownloadTask) -> None:
        task.cancel()
        self._log(f"取消: {task.display_name}")
        self._on_task_changed(task.task_id)

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
        for task_id in list(self._task_rows):
            task = self._find_task(task_id)
            if task:
                self._task_rows[task_id].update_from_task()

    def _clear_completed_tasks(self) -> None:
        to_remove = [
            task_id for task_id, row in self._task_rows.items()
            if (task := self._find_task(task_id)) is None
            or task.status.value in ("completed", "failed", "cancelled")
        ]
        for task_id in to_remove:
            row = self._task_rows.pop(task_id)
            row.setParent(None)
            row.deleteLater()
        if self._queue:
            self._queue.clear_completed()
        self._sync_empty_state()
        self._log(f"已清除 {len(to_remove)} 个已完成任务")
        self._update_queue_buttons()

    # ---------- 下载设置（限速） ----------

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self, self.theme.palette, cfg=self._settings_cfg)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        values = dlg.values()
        per_kb = values["per_task_speed"]
        global_kb = values["global_speed"]
        self.per_task_speed = per_kb
        self.global_speed = global_kb
        self._settings_cfg.update(values)
        # 后处理选项立即重建并同步到队列（后续任务生效）
        self._post_options = PostOptions.from_config(self._settings_cfg)
        # 全局限流器为共享实例，set_rate 立即生效；队列单任务限速同步更新
        self._global_limiter.set_rate(global_kb * 1024)
        if self._queue is not None:
            self._queue.set_limits(per_kb * 1024, global_kb * 1024)
            self._queue.set_post_options(self._post_options)
        save_settings({
            "download_dir": self.download_dir,
            **values,
        })
        per_txt = "不限速" if per_kb == 0 else f"{per_kb} KB/s"
        global_txt = "不限速" if global_kb == 0 else f"{global_kb} KB/s"
        conv_txt = {"off": "不转码", "mp3": "转 MP3", "flac": "转 FLAC"}.get(
            values["convert_mode"], "不转码")
        self._log(
            f"设置已保存：单任务 {per_txt}，全局 {global_txt}，"
            f"格式 {conv_txt}"
            + (f" {values['mp3_bitrate']}kbps" if values["convert_mode"] == "mp3" else "")
        )
        self._set_status("下载设置已保存", "ok")

    def _refresh_speeds(self) -> None:
        """500ms 定时刷新：各任务行实时速度 + 总速度。"""
        if self._queue is not None:
            for task in self._queue.tasks:
                row = self._task_rows.get(task.task_id)
                if row is not None and task.status == TaskStatus.DOWNLOADING:
                    row.update_from_task()
            self.total_speed_lbl.setText(
                f"总速度 {format_speed(self._queue.total_speed_bps)}"
            )

    # ---------- 内置试听 ----------

    def _on_preview_selected(self) -> None:
        items = self.tree.selectedItems()
        if not items:
            QMessageBox.warning(self, "提示", "请先选择一首歌曲进行试听")
            return
        uid = items[0].data(0, Qt.ItemDataRole.UserRole)
        songs = self._songs_by_uids({uid})
        if not songs:
            return
        song = songs[0]
        title = song.get("title", "") or song.get("name", "")
        artist = song.get("artist", "") or song.get("singer", "")
        tag, marker = self._version_of(song)
        if tag == "bad":
            self._log(f"该音源疑似伴奏/无人声版本（{marker}），已跳过试听: {artist} - {title}")
            self._set_status("选中的是疑似伴奏版本，已阻止试听", "warn")
            return
        self._preview_uid = uid
        self._preview_gen += 1
        gen = self._preview_gen
        self.player_title_lbl.setText(f"{artist} - {title}")
        self.player_panel.setVisible(True)
        self._set_status("正在获取试听链接…", "busy")
        threading.Thread(target=self._preview_worker, args=(song, gen),
                         daemon=True).start()

    def _preview_worker(self, song: dict[str, Any], gen: int) -> None:
        try:
            url = str(song.get("audio_url", "") or "")
            detail = None
            if not url:
                detail = resolve_song(song)
                url = (detail or {}).get("audio_url", "")
                if detail and detail.get("version_tag") == "bad":
                    if gen == self._preview_gen:
                        self.bus.preview_err.emit(
                            f"疑似伴奏版本（{detail.get('version_label')}），无法试听"
                        )
                    return
            if not url:
                if gen == self._preview_gen:
                    self.bus.preview_err.emit("无法获取试听链接")
                return
            title = ((detail or {}).get("title")
                     or song.get("title") or song.get("name") or "")
            artist = ((detail or {}).get("artist")
                      or song.get("artist") or song.get("singer") or "")
            # 回填，供后续下载直接使用
            if not song.get("audio_url"):
                song["audio_url"] = url
                if detail:
                    song["quality"] = detail.get("quality", song.get("quality", ""))
                    song["version_tag"] = detail.get("version_tag", "")
                    song["version_label"] = detail.get("version_label", "")
            if gen == self._preview_gen:
                self.bus.preview_ready.emit((url, f"{artist} - {title}"))
        except Exception as e:  # noqa: BLE001
            if gen == self._preview_gen:
                self.bus.preview_err.emit(str(e))

    def _on_preview_ready(self, payload: object) -> None:
        url, name = payload
        self.player_title_lbl.setText(name)
        self.player.play_url(url)
        self._log(f"开始试听: {name}")
        self._set_status(f"正在试听: {name}", "info")

    def _on_preview_err(self, msg: str) -> None:
        self._log(f"试听失败: {msg}")
        self._set_status("试听失败", "warn")

    def _player_toggle(self) -> None:
        self.player.toggle()

    def _player_stop(self) -> None:
        self.player.stop()

    def _player_close(self) -> None:
        self.player.stop()
        self.player_panel.setVisible(False)
        self._preview_uid = None
        self._set_status("准备就绪", "info")

    def _player_slider_pressed(self) -> None:
        self._player_seeking = True

    def _player_seek(self) -> None:
        self.player.seek(self.player_slider.value())
        self._player_seeking = False

    def _on_player_state(self, state: int) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.player_play_btn.set_glyph("pause" if playing else "play")
        if state == QMediaPlayer.PlaybackState.StoppedState:
            self.player_slider.setValue(0)

    def _on_player_position(self, ms: int) -> None:
        if not self._player_seeking:
            self.player_slider.setValue(ms)
        total = self.player.media.duration()
        self.player_time_lbl.setText(
            f"{self._ms_fmt(ms)} / {self._ms_fmt(total)}"
        )

    def _on_player_duration(self, ms: int) -> None:
        self.player_slider.setRange(0, max(0, int(ms)))

    def _on_player_error(self, msg: str) -> None:
        self._log(f"播放错误: {msg}")
        self._set_status("试听失败", "warn")

    @staticmethod
    def _ms_fmt(ms: int) -> str:
        if ms <= 0:
            return "0:00"
        s = int(ms // 1000)
        return f"{s // 60}:{s % 60:02d}"

    # ---------- 歌词预览 ----------

    def _on_lyrics_selected(self) -> None:
        items = self.tree.selectedItems()
        if not items:
            QMessageBox.warning(self, "提示", "请先选择一首歌曲查看歌词")
            return
        uid = items[0].data(0, Qt.ItemDataRole.UserRole)
        songs = self._songs_by_uids({uid})
        if not songs:
            return
        song = songs[0]
        title = song.get("title", "") or song.get("name", "")
        artist = song.get("artist", "") or song.get("singer", "")
        name = f"{artist} - {title}"
        self._lyrics_gen += 1
        gen = self._lyrics_gen
        self._lyrics_win = LyricsDialog(
            self, self.theme.palette, title=name, lrc="", busy=True)
        self._set_status(f"正在搜索歌词: {name}", "busy")
        threading.Thread(target=self._lyrics_worker, args=(song, title, artist, gen),
                         daemon=True).start()
        self._lyrics_win.show()

    def _lyrics_worker(self, song: dict[str, Any], title: str,
                       artist: str, gen: int) -> None:
        try:
            detail = None
            if not song.get("lrc_url"):
                # 详情可补出平台直出歌词链接（失败不影响后续兜底检索）
                detail = resolve_song(song)
            meta = self._build_song_meta(song, title, artist, detail)
            lrc = fetch_lyrics(meta)
        except Exception:  # noqa: BLE001
            lrc = None
        self.bus.lyrics_ready.emit((gen, f"{artist} - {title}", lrc))

    def _on_lyrics_ready(self, payload: object) -> None:
        gen, name, lrc = payload
        if gen != self._lyrics_gen:
            return
        win = self._lyrics_win
        if win is None:
            return
        win.set_lyrics(lrc)
        if lrc:
            self._log(f"歌词已加载: {name}")
            self._set_status("歌词已加载", "ok")
        else:
            self._log(f"未找到歌词: {name}")
            self._set_status("未找到该歌曲歌词", "warn")


    # ---------- 主题菜单 / 打赏 ----------

    def _show_theme_menu(self) -> None:
        pal = self.theme.palette
        old = getattr(self, "_theme_menu", None)
        if old is not None:
            # 连开（含动画未结束）：立即拆除旧菜单，避免两菜单叠加、
            # 旧 closed 信号干扰新菜单
            old._anim.stop()
            old.hide()
            old._closing = True
            old.closed.emit()
        scheme_section = [(k, meta["name"], k == self.theme.scheme_key)
                          for k, meta in SCHEMES.items()]
        mode_section = [(m, label, m == self.theme.theme_mode)
                        for m, label in THEME_MODES]
        menu = GlassMenu(
            self.ambient, pal,
            [("设计方案", scheme_section), ("外观模式", mode_section)],
            self._on_theme_pick,
        )
        gl = self.theme_btn.mapToGlobal(QPoint(0, self.theme_btn.height() + 6))
        self._theme_menu = menu

        def _clear_closed(m=menu) -> None:
            # 快速连开时旧菜单的关闭信号不得清掉新菜单引用
            if self._theme_menu is m:
                self._theme_menu = None

        menu.closed.connect(_clear_closed)
        menu.open_at(gl)

    def _on_theme_pick(self, value: str) -> None:
        if value in SCHEMES:
            self.theme.set_scheme(value)
        elif value in ("auto", "light", "dark"):
            self.theme.set_mode(value)
        self._log(f"方案: {SCHEMES[self.theme.scheme_key]['name']} · "
                  f"外观: {dict(THEME_MODES)[self.theme.theme_mode]}")

    def _open_tip_dialog(self) -> None:
        if self._tip_win is not None:
            self._tip_win.raise_()
            self._tip_win.setFocus()
            return
        self._tip_win = TipDialogQ(
            self.ambient, self.theme.palette, self.tip_store,
            on_record=lambda msg: self.bus.tip_record.emit(msg),
            on_view_records=self._open_tip_records,
            on_close=lambda: setattr(self, "_tip_win", None),
        )
        self._tip_win.open_at()

    def _on_tip_record(self, msg: str) -> None:
        self._log("打赏 · " + msg)
        self._set_status(msg, "ok")

    def _open_tip_records(self) -> None:
        if self._tip_records_win is not None:
            self._tip_records_win.raise_()
            return
        self._tip_records_win = TipRecordsQ(self.ambient, self.theme.palette,
                                            self.tip_store)
        self._tip_records_win.closed.connect(
            lambda: setattr(self, "_tip_records_win", None))
        self._tip_records_win.open_at()

    # ---------- 布局自适应 ----------

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self.ambient.schedule_refresh()


# ==================== 程序入口 ====================


def main() -> None:
    demo = "--demo" in sys.argv
    apply_macos_app_identity()  # 需在 QApplication 之前，修正 Dock/菜单栏名称
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName(APP_TITLE)
    icon = app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)  # 所有窗口默认图标
        apply_macos_dock_icon(app_icon_path())  # 源码直跑时兜底设置 Dock 图标
    base = QFont(UI_FONT)
    base.setPixelSize(12)
    app.setFont(base)

    win = MainWindow(demo=demo)
    if not icon.isNull():
        win.setWindowIcon(icon)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
