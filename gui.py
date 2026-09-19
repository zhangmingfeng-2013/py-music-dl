#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
音乐下载器 GUI v2.1
功能：多平台并发搜索 + 批量下载队列 + 任务面板（进度条/暂停/取消）
数据源：基于聚合音乐站 API
支持平台：咪咕音乐 / 网易云音乐 / QQ音乐 / 酷我音乐
"""

from __future__ import annotations

import os
import json
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
from typing import Any, Optional

from api import PLATFORM_NAMES, search_all_platforms, prefetch_quality, get_song_detail
from downloader import DownloadQueue, DownloadTask, TaskStatus
from utils import (
    log, safe_filename, ensure_download_dir, format_size,
    DEFAULT_DOWNLOAD_DIR,
)

# ---- 常量 ----

WIN_WIDTH = 980
WIN_HEIGHT = 780
TASK_ROW_HEIGHT = 36
MAX_TASK_PANEL_ROWS = 8

# ---- 主题 ----

THEME_NAME = "clam"
APP_FONT = "PingFang SC"          # macOS 使用苹方，其他系统自动回退
# 配色（现代浅色主题）
COLOR_PRIMARY = "#2563eb"         # 品牌蓝（主按钮/焦点）
COLOR_PRIMARY_DARK = "#1e40af"    # 主按钮按下
COLOR_SIDEBAR_BG = "#0f172a"      # 顶部横幅深色底
COLOR_SIDEBAR_ACCENT = "#38bdf8"  # 顶部横幅高亮
COLOR_STATUS_BG = "#eff6ff"       # 状态栏浅蓝底
COLOR_ROW_EVEN = "#ffffff"        # 表格偶数行
COLOR_ROW_ODD = "#f3f6fb"         # 表格奇数行
COLOR_EMPTY = "#9ca3af"           # 空状态提示灰
COLOR_FRAME_HEADER = "#334155"    # LabelFrame 标题字色

# ---- 状态颜色映射 ----

_STATUS_COLORS: dict[str, str] = {
    "pending":     "#6b7280",  # gray
    "fetching":    "#3b82f6",  # blue
    "downloading": "#2563eb",  # deeper blue
    "paused":      "#f59e0b",  # orange
    "completed":   "#10b981",  # green
    "failed":      "#ef4444",  # red
    "cancelled":   "#9ca3af",  # light gray
}

_STATUS_ICONS: dict[str, str] = {
    "pending":     "⏳",
    "fetching":    "🔗",
    "downloading": "⬇",
    "paused":      "⏸",
    "completed":   "✅",
    "failed":      "❌",
    "cancelled":   "🚫",
}


# ==================== 搜索历史管理 ====================


class SearchHistory:
    """搜索历史管理类（持久化到 JSON 文件）"""

    def __init__(self, history_file: str = "search_history.json", max_items: int = 20):
        self.history_file = history_file
        self.max_items = max_items
        self.history: list[str] = self._load_history()

    def _load_history(self) -> list[str]:
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
            except Exception:
                pass
        return []

    def _save_history(self) -> None:
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
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


# ==================== 歌手历史管理 ====================


class ArtistHistory:
    """
    歌手历史管理类（持久化到 artist_history.json）
    搜索结果中的歌手会自动记录，可在歌手筛选下拉中直接选择。
    """

    def __init__(self, history_file: str = "artist_history.json", max_items: int = 50):
        self.history_file = history_file
        self.max_items = max_items
        self.history: list[str] = self._load_history()

    def _load_history(self) -> list[str]:
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
            except Exception:
                pass
        return []

    def _save_history(self) -> None:
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
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


# ==================== 字体工具 ====================


def _ui_font(size: int, bold: bool = False) -> tuple:
    """返回统一 UI 字体（macOS 用苹方，其他平台回退默认）"""
    return (APP_FONT, size, "bold") if bold else (APP_FONT, size)


# ==================== 下载任务行组件 ====================


class TaskRow:
    """
    任务面板中的一行，对应一个 DownloadTask。
    包含：名称标签、进度条、状态图标、暂停/恢复按钮、取消按钮。
    """

    def __init__(
        self,
        parent: tk.Widget,
        task: DownloadTask,
        on_pause_resume: "Callable[[DownloadTask], None]",
        on_cancel: "Callable[[DownloadTask], None]",
    ):
        self.task = task
        self._on_pause_resume = on_pause_resume
        self._on_cancel = on_cancel

        self.frame = ttk.Frame(parent)
        self.frame.pack(fill=tk.X, pady=1)

        # 名称标签（固定宽度，截断过长文本）
        display = task.display_name
        if len(display) > 36:
            display = display[:33] + "..."
        self._name_var = tk.StringVar(value=display)
        self._name_lbl = ttk.Label(
            self.frame, textvariable=self._name_var,
            width=36, anchor=tk.W, font=_ui_font(10),
        )
        self._name_lbl.pack(side=tk.LEFT, padx=(2, 8))

        # 进度条
        self._progress = ttk.Progressbar(
            self.frame, mode='determinate', length=200,
            style="Slim.Horizontal.TProgressbar",
        )
        self._progress.pack(side=tk.LEFT, padx=2)
        self._progress["maximum"] = 100
        self._progress["value"] = 0

        # 状态标签
        self._status_var = tk.StringVar(value="⏳ 等待中")
        self._status_lbl = ttk.Label(
            self.frame, textvariable=self._status_var,
            width=12, anchor=tk.W, font=_ui_font(9),
        )
        self._status_lbl.pack(side=tk.LEFT, padx=4)

        # 暂停/恢复按钮
        self._pause_btn = ttk.Button(
            self.frame, text="⏸", width=3,
            command=lambda: self._on_pause_resume(self.task),
        )
        self._pause_btn.pack(side=tk.LEFT, padx=1)
        # 初始状态：PENDING 不可暂停
        self._pause_btn.config(state=tk.DISABLED)

        # 取消按钮
        self._cancel_btn = ttk.Button(
            self.frame, text="✕", width=3,
            command=lambda: self._on_cancel(self.task),
        )
        self._cancel_btn.pack(side=tk.LEFT, padx=1)

    def update_from_task(self) -> None:
        """根据 DownloadTask 最新状态刷新界面"""
        status = self.task.status.value
        color = _STATUS_COLORS.get(status, "#000000")
        icon = _STATUS_ICONS.get(status, "?")

        self._name_lbl.config(foreground=color)

        if status == "pending":
            self._status_var.set("⏳ 等待中")
            self._progress["value"] = 0
            self._pause_btn.config(state=tk.DISABLED, text="⏸")
            self._cancel_btn.config(state=tk.NORMAL)

        elif status == "fetching":
            self._status_var.set("🔗 获取链接")
            self._progress["mode"] = "indeterminate"
            self._progress.start(10)
            self._pause_btn.config(state=tk.DISABLED)
            self._cancel_btn.config(state=tk.NORMAL)

        elif status == "downloading":
            pct = self.task.progress_pct
            self._progress["mode"] = "determinate"
            self._progress["value"] = pct
            self._status_var.set(f"⬇ {pct:.0f}%")
            self._pause_btn.config(state=tk.NORMAL, text="⏸")
            self._cancel_btn.config(state=tk.NORMAL)

        elif status == "paused":
            pct = self.task.progress_pct
            self._progress["mode"] = "determinate"
            self._progress["value"] = pct
            self._status_var.set(f"⏸ {pct:.0f}%")
            self._pause_btn.config(state=tk.NORMAL, text="▶")
            self._cancel_btn.config(state=tk.NORMAL)

        elif status == "completed":
            self._progress["mode"] = "determinate"
            self._progress["value"] = 100
            size_str = format_size(self.task.total_size)
            self._status_var.set(f"✅ {size_str}")
            self._pause_btn.config(state=tk.DISABLED, text="⏸")
            self._cancel_btn.config(state=tk.DISABLED)

        elif status == "failed":
            self._progress["mode"] = "determinate"
            err = self.task.error[:10] if self.task.error else "未知错误"
            self._status_var.set(f"❌ {err}")
            self._pause_btn.config(state=tk.DISABLED)
            self._cancel_btn.config(state=tk.DISABLED)

        elif status == "cancelled":
            self._progress["mode"] = "determinate"
            self._status_var.set("🚫 已取消")
            self._pause_btn.config(state=tk.DISABLED)
            self._cancel_btn.config(state=tk.DISABLED)

    def destroy(self) -> None:
        self.frame.destroy()


# ==================== 主 GUI 类 ====================


class MusicDownloaderGUI:
    """音乐下载器图形界面 v2.0"""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("🎵 音乐下载器 v2.1 — 多平台聚合")
        self.root.geometry(f"{WIN_WIDTH}x{WIN_HEIGHT}")
        self.root.resizable(True, True)
        self.root.minsize(800, 600)

        # 搜索结果
        self.search_results: list[dict[str, Any]] = []
        self.filtered_results: list[dict[str, Any]] = []

        # 搜索 / 歌手历史
        self.search_history = SearchHistory()
        self.artist_history = ArtistHistory()

        # 下载目录
        self.download_dir: str = ensure_download_dir(DEFAULT_DOWNLOAD_DIR)

        # 下载队列 & 任务面板映射
        self._queue: Optional[DownloadQueue] = None
        self._task_rows: dict[str, TaskRow] = {}

        # 是否正在运行队列
        self._queue_running: bool = False

        self._setup_theme()
        self._setup_ui()

    # ---- 主题 ----

    def _setup_theme(self) -> None:
        """初始化 ttk 主题与全局配色"""
        style = ttk.Style(self.root)
        try:
            style.theme_use(THEME_NAME)
        except tk.TclError:
            # 平台不支持时保留默认主题，配色同样生效
            pass

        style.configure(
            ".", font=_ui_font(10), focuscolor=COLOR_PRIMARY,
        )
        # 主按钮：品牌蓝白字
        style.configure(
            "Accent.TButton",
            font=_ui_font(10, bold=True), foreground="#ffffff",
            background=COLOR_PRIMARY,
            bordercolor=COLOR_PRIMARY, lightcolor=COLOR_PRIMARY, darkcolor=COLOR_PRIMARY,
        )
        style.map(
            "Accent.TButton",
            background=[
                ("disabled", "#94a3b8"),
                ("pressed", COLOR_PRIMARY_DARK),
                ("active", "#3b82f6"),
            ],
            foreground=[
                ("disabled", "#e2e8f0"),
                ("!disabled", "#ffffff"),
            ],
        )
        # 次要按钮
        style.configure(
            "Subtle.TButton",
            font=_ui_font(10), foreground="#334155",
            background="#f1f5f9",
            bordercolor="#cbd5e1", lightcolor="#f8fafc", darkcolor="#cbd5e1",
        )
        style.map(
            "Subtle.TButton",
            background=[("pressed", "#e2e8f0"), ("active", "#e8eef7")],
        )
        # 面板标题（LabelFrame 文字）
        style.configure(
            "TLabelframe.Label", font=_ui_font(10, bold=True),
            foreground=COLOR_FRAME_HEADER,
        )
        # 树形表格
        style.configure(
            "Treeview",
            font=_ui_font(10), rowheight=26,
            background="#ffffff", fieldbackground="#ffffff",
            bordercolor="#cbd5e1", lightcolor="#cbd5e1", darkcolor="#cbd5e1",
        )
        style.configure(
            "Treeview.Heading",
            font=_ui_font(10, bold=True), foreground="#475569",
            background="#eef2f8", relief="flat",
        )
        style.map(
            "Treeview",
            background=[("selected", COLOR_PRIMARY)],
            foreground=[("selected", "#ffffff")],
        )
        # 进度条
        style.configure(
            "Horizontal.TProgressbar",
            troughcolor="#e2e8f0", background=COLOR_PRIMARY,
            bordercolor="#e2e8f0", lightcolor=COLOR_PRIMARY, darkcolor=COLOR_PRIMARY,
        )
        # 横向细进度条（任务面板用）
        style.configure(
            "Slim.Horizontal.TProgressbar",
            troughcolor="#e2e8f0", background=COLOR_PRIMARY,
            bordercolor="#e2e8f0", lightcolor=COLOR_PRIMARY, darkcolor=COLOR_PRIMARY,
            thickness=12,
        )

    # ---- UI 构建 ----

    def _setup_ui(self) -> None:
        """构建完整界面布局"""
        # 根容器
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)

        row_idx = 0

        # === 0. 顶部横幅 ===
        banner = tk.Frame(main_frame, bg=COLOR_SIDEBAR_BG, height=56)
        banner.grid(row=row_idx, column=0, sticky=(tk.W, tk.E), pady=(0, 8))
        banner.grid_propagate(False)
        banner.columnconfigure(1, weight=1)

        tk.Label(
            banner, text="🎵", bg=COLOR_SIDEBAR_BG,
            font=_ui_font(22),
        ).grid(row=0, column=0, padx=(16, 8), pady=10, sticky=tk.W)

        title_box = tk.Frame(banner, bg=COLOR_SIDEBAR_BG)
        title_box.grid(row=0, column=1, sticky=tk.W)
        tk.Label(
            title_box, text="音乐下载器", bg=COLOR_SIDEBAR_BG, fg="#ffffff",
            font=_ui_font(14, bold=True),
        ).pack(anchor=tk.W)
        tk.Label(
            title_box, text="多平台聚合 · 咪咕 | 网易云 | QQ音乐 | 酷我",
            bg=COLOR_SIDEBAR_BG, fg="#94a3b8", font=_ui_font(9),
        ).pack(anchor=tk.W)

        tk.Label(
            banner, text="v2.1", bg=COLOR_SIDEBAR_BG, fg=COLOR_SIDEBAR_ACCENT,
            font=_ui_font(10, bold=True),
        ).grid(row=0, column=2, padx=16, pady=10, sticky=tk.E)
        row_idx += 1

        # === 1. 搜索区域 ===
        search_frame = ttk.LabelFrame(main_frame, text="搜索音乐", padding="10")
        search_frame.grid(row=row_idx, column=0, sticky=(tk.W, tk.E), pady=(0, 8))
        search_frame.columnconfigure(1, weight=1)
        row_idx += 1

        ttk.Label(search_frame, text="歌曲名：", font=_ui_font(11)).grid(
            row=0, column=0, sticky=tk.W, padx=(0, 5),
        )
        self.search_var = tk.StringVar()
        self.search_combo = ttk.Combobox(
            search_frame, textvariable=self.search_var, font=_ui_font(12),
        )
        self.search_combo.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5)
        self.search_combo['values'] = self.search_history.get_all()
        self.search_combo.bind('<<ComboboxSelected>>', self._on_combo_select)
        self.search_combo.bind('<KeyRelease>', self._on_search_keyrelease)
        self.search_combo.bind('<Return>', lambda e: self._on_search())
        self.search_combo.focus_set()

        self.search_btn = ttk.Button(
            search_frame, text="🔍 搜索", command=self._on_search,
            style="Accent.TButton",
        )
        self.search_btn.grid(row=0, column=2, padx=5)

        # 下载目录行
        ttk.Label(search_frame, text="下载目录：", font=_ui_font(10)).grid(
            row=1, column=0, sticky=tk.W, padx=(0, 5), pady=(8, 0),
        )
        self.path_var = tk.StringVar(value=self.download_dir)
        self.path_entry = ttk.Entry(
            search_frame, textvariable=self.path_var, font=_ui_font(10),
        )
        self.path_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=5, pady=(8, 0))
        self.path_entry.bind('<Return>', self._on_dir_changed)

        self.browse_btn = ttk.Button(
            search_frame, text="📂 浏览", command=self._browse_dir,
        )
        self.browse_btn.grid(row=1, column=2, padx=5, pady=(8, 0))

        # === 2. 筛选区域 ===
        filter_frame = ttk.LabelFrame(main_frame, text="筛选结果", padding="5")
        filter_frame.grid(row=row_idx, column=0, sticky=(tk.W, tk.E), pady=(0, 8))
        filter_frame.columnconfigure(1, weight=1)
        filter_frame.columnconfigure(3, weight=1)
        row_idx += 1

        ttk.Label(filter_frame, text="歌手：").grid(
            row=0, column=0, sticky=tk.W, padx=(0, 5),
        )
        self.artist_filter_var = tk.StringVar(value='全部')
        self.artist_filter_combo = ttk.Combobox(
            filter_frame, textvariable=self.artist_filter_var,
            font=_ui_font(10),
        )
        self.artist_filter_combo.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5)
        self.artist_filter_combo.bind('<<ComboboxSelected>>', self._on_artist_select)
        self.artist_filter_combo['values'] = ['全部'] + self.artist_history.get_all()

        ttk.Label(filter_frame, text="平台：").grid(
            row=0, column=2, sticky=tk.W, padx=(10, 5),
        )
        self.source_filter_var = tk.StringVar(value='全部')
        self.source_filter_combo = ttk.Combobox(
            filter_frame, textvariable=self.source_filter_var,
            font=_ui_font(10), state='readonly',
        )
        self.source_filter_combo.grid(row=0, column=3, sticky=(tk.W, tk.E), padx=5)
        self.source_filter_combo.bind('<<ComboboxSelected>>', self._on_filter_change)
        # 常用平台固定列表
        self.source_filter_combo['values'] = ['全部'] + list(PLATFORM_NAMES)

        self.clear_filter_btn = ttk.Button(
            filter_frame, text="清除筛选", command=self._clear_filter,
        )
        self.clear_filter_btn.grid(row=0, column=4, padx=(10, 0))

        # === 3. 搜索结果表格 ===
        results_frame = ttk.LabelFrame(main_frame, text="搜索结果", padding="8")
        results_frame.grid(
            row=row_idx, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=2,
        )
        results_frame.columnconfigure(0, weight=1)
        results_frame.rowconfigure(0, weight=1)
        row_idx += 1

        columns = ("index", "title", "artist", "source", "quality")
        self.tree = ttk.Treeview(
            results_frame, columns=columns, show="headings",
            height=10, selectmode='extended',
        )

        self.tree.heading("index", text="序号")
        self.tree.heading("title", text="歌曲名")
        self.tree.heading("artist", text="歌手")
        self.tree.heading("source", text="来源")
        self.tree.heading("quality", text="音质")

        self.tree.column("index", width=55, anchor=tk.CENTER)
        self.tree.column("title", width=300)
        self.tree.column("artist", width=200)
        self.tree.column("source", width=100)
        self.tree.column("quality", width=70, anchor=tk.CENTER)

        # 斑马纹：奇偶行交替底色
        self.tree.tag_configure("even", background=COLOR_ROW_EVEN)
        self.tree.tag_configure("odd", background=COLOR_ROW_ODD)

        tree_scroll = ttk.Scrollbar(results_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)

        self.tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        tree_scroll.grid(row=0, column=1, sticky=(tk.N, tk.S))

        # 双击下载
        self.tree.bind("<Double-1>", lambda e: self._on_download_selected())

        # === 4. 操作按钮 ===
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=row_idx, column=0, pady=6)
        row_idx += 1

        self.download_sel_btn = ttk.Button(
            btn_frame, text="⬇️ 下载选中", command=self._on_download_selected,
            state=tk.DISABLED, style="Accent.TButton",
        )
        self.download_sel_btn.grid(row=0, column=0, padx=3)

        self.download_all_btn = ttk.Button(
            btn_frame, text="📥 全部下载", command=self._on_download_all,
            state=tk.DISABLED, style="Accent.TButton",
        )
        self.download_all_btn.grid(row=0, column=1, padx=3)

        self.open_dir_btn = ttk.Button(
            btn_frame, text="📁 打开下载目录", command=self._open_download_dir,
            style="Subtle.TButton",
        )
        self.open_dir_btn.grid(row=0, column=2, padx=3)

        self.clear_results_btn = ttk.Button(
            btn_frame, text="🗑 清空结果", command=self._clear_results,
            style="Subtle.TButton",
        )
        self.clear_results_btn.grid(row=0, column=3, padx=3)

        self.clear_history_btn = ttk.Button(
            btn_frame, text="📋 清空历史", command=self._clear_history,
            style="Subtle.TButton",
        )
        self.clear_history_btn.grid(row=0, column=4, padx=3)

        # === 5. 下载任务面板 ===
        task_frame = ttk.LabelFrame(main_frame, text="下载任务", padding="5")
        task_frame.grid(
            row=row_idx, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=2,
        )
        task_frame.columnconfigure(0, weight=1)
        task_frame.rowconfigure(0, weight=1)
        row_idx += 1

        # 用 Canvas 实现可滚动任务列表
        self._task_canvas = tk.Canvas(
            task_frame, height=TASK_ROW_HEIGHT * MAX_TASK_PANEL_ROWS,
            highlightthickness=0, bg="#ffffff",
        )
        self._task_canvas.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        task_scroll = ttk.Scrollbar(
            task_frame, orient=tk.VERTICAL, command=self._task_canvas.yview,
        )
        task_scroll.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self._task_canvas.configure(yscrollcommand=task_scroll.set)

        # 内嵌 frame 也使用卡片白底
        self._task_inner = ttk.Frame(self._task_canvas)
        self._task_canvas_window = self._task_canvas.create_window(
            (0, 0), window=self._task_inner, anchor=tk.NW, tags="inner",
        )

        # 内嵌 frame 大小变化时更新 canvas scrollregion
        self._task_inner.bind("<Configure>", self._on_inner_configure)
        self._task_canvas.bind("<Configure>", self._on_canvas_configure)

        # 鼠标滚轮支持
        self._task_canvas.bind("<Enter>", self._bind_mousewheel)
        self._task_canvas.bind("<Leave>", self._unbind_mousewheel)

        # 空状态提示
        self._task_empty_lbl = ttk.Label(
            self._task_inner, text="暂无下载任务", foreground=COLOR_EMPTY,
            font=_ui_font(10), background="#ffffff",
        )
        self._task_empty_lbl.pack(pady=20)

        # === 6. 队列管理按钮 ===
        queue_ctrl_frame = ttk.Frame(main_frame)
        queue_ctrl_frame.grid(row=row_idx, column=0, pady=4)
        row_idx += 1

        self.pause_all_btn = ttk.Button(
            queue_ctrl_frame, text="⏸ 暂停全部", command=self._pause_all_tasks,
            state=tk.DISABLED,
        )
        self.pause_all_btn.grid(row=0, column=0, padx=3)

        self.cancel_all_btn = ttk.Button(
            queue_ctrl_frame, text="✕ 取消全部", command=self._cancel_all_tasks,
            state=tk.DISABLED,
        )
        self.cancel_all_btn.grid(row=0, column=1, padx=3)

        self.clear_done_btn = ttk.Button(
            queue_ctrl_frame, text="🗑 清除已完成", command=self._clear_completed_tasks,
            state=tk.DISABLED,
        )
        self.clear_done_btn.grid(row=0, column=2, padx=3)

        # === 7. 状态栏 ===
        self.status_var = tk.StringVar(value="✅ 准备就绪")
        status_bar = tk.Label(
            main_frame, textvariable=self.status_var,
            anchor=tk.W, font=_ui_font(10),
            bg=COLOR_STATUS_BG, fg="#1e40af",
            padx=10, pady=5,
        )
        status_bar.grid(row=row_idx, column=0, sticky=(tk.W, tk.E), pady=(6, 0))
        row_idx += 1

        # === 8. 日志面板 ===
        log_frame = ttk.LabelFrame(main_frame, text="日志", padding="5")
        log_frame.grid(
            row=row_idx, column=0, sticky=(tk.W, tk.E), pady=(6, 0),
        )
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        row_idx += 1

        self.log_text = scrolledtext.ScrolledText(
            log_frame, height=5, wrap=tk.WORD, state=tk.DISABLED,
            font=_ui_font(9),
            bg="#f8fafc", fg="#334155", relief=tk.FLAT,
            highlightthickness=0, borderwidth=0,
        )
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

    # ---- Canvas 滚动适配 ----

    def _on_inner_configure(self, event: tk.Event) -> None:
        """内嵌 frame 大小变化时更新滚动区域"""
        self._task_canvas.configure(scrollregion=self._task_canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        """Canvas 宽度变化时调整内嵌 frame 宽度"""
        self._task_canvas.itemconfig(
            self._task_canvas_window, width=event.width,
        )

    def _bind_mousewheel(self, event: tk.Event) -> None:
        """鼠标进入 Canvas 时绑定滚轮"""
        self._task_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mousewheel(self, event: tk.Event) -> None:
        """鼠标离开 Canvas 时解绑滚轮"""
        self._task_canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event: tk.Event) -> None:
        """处理鼠标滚轮滚动"""
        self._task_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ---- 日志 ----

    def _log(self, message: str) -> None:
        """写入日志面板"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    # ---- 搜索历史 / 目录 ----

    def _on_combo_select(self, event: Optional[tk.Event] = None) -> None:
        """下拉框选中自动搜索"""
        selected = self.search_var.get()
        if selected:
            self._on_search()

    def _on_search_keyrelease(self, event: tk.Event) -> None:
        """键盘输入时更新搜索建议"""
        current_text = self.search_var.get()
        if not current_text:
            return
        history = self.search_history.get_all()
        matches = [h for h in history if current_text.lower() in h.lower()]
        self.search_combo['values'] = matches if matches else history

    def _browse_dir(self) -> None:
        """浏览选择下载目录"""
        dir_path = filedialog.askdirectory(initialdir=self.download_dir)
        if dir_path:
            self.download_dir = dir_path
            self.path_var.set(dir_path)
            self._log(f"下载目录已切换: {dir_path}")

    def _on_dir_changed(self, event: Optional[tk.Event] = None) -> None:
        """手动输入目录后回车"""
        new_dir = self.path_var.get().strip()
        if new_dir and os.path.isdir(new_dir):
            self.download_dir = new_dir
            self._log(f"下载目录已切换: {new_dir}")
        elif new_dir:
            try:
                self.download_dir = ensure_download_dir(new_dir)
                self.path_var.set(self.download_dir)
                self._log(f"下载目录已创建: {self.download_dir}")
            except Exception as e:
                self._log(f"无法创建目录: {e}")
                self.path_var.set(self.download_dir)

    def _open_download_dir(self) -> None:
        """在文件管理器中打开下载目录"""
        if os.path.exists(self.download_dir):
            subprocess.run(["open", self.download_dir])

    def _clear_history(self) -> None:
        """清空搜索历史"""
        self.search_history.clear()
        self.search_combo['values'] = []
        messagebox.showinfo("提示", "搜索历史已清空")

    def _on_artist_select(self, event: Optional[tk.Event] = None) -> None:
        """
        歌手下拉选择事件：
        - 当前结果中有该歌手 → 直接筛选
        - 没有结果（初始状态）→ 用歌手名触发搜索
        """
        selected = self.artist_filter_var.get()
        if not selected or selected == '全部':
            self._on_filter_change()
            return

        current_artists = {
            song.get("artist", "") or song.get("singer", "")
            for song in self.search_results
        }
        if selected in current_artists:
            self._on_filter_change()
        else:
            # 当前没有结果，把歌手名作为关键词直接搜索
            self._log(f"🎤 选择历史歌手: {selected}，按歌手搜索")
            self.search_var.set(selected)
            self._on_search()

    # ---- 筛选 ----

    def _update_filter_options(self) -> None:
        """根据搜索结果更新筛选下拉选项（歌手 = 历史 + 本次结果，平台 = 常用固定列表）"""
        artists: set[str] = set(self.artist_history.get_all())

        for song in self.search_results:
            artist = song.get("artist", "") or song.get("singer", "")
            if artist:
                # 自动记录到歌手历史，下次可直接选择
                self.artist_history.add(artist)
                artists.add(artist)

        self.artist_filter_combo['values'] = ['全部'] + sorted(artists)
        self.source_filter_combo['values'] = ['全部'] + list(PLATFORM_NAMES)
        # 若当前选中值不在新列表中（如旧结果被清除），回退到全部
        if self.artist_filter_var.get() not in ['全部'] + sorted(artists):
            self.artist_filter_var.set('全部')
        if self.source_filter_var.get() not in ['全部'] + list(PLATFORM_NAMES):
            self.source_filter_var.set('全部')

    def _on_filter_change(self, event: Optional[tk.Event] = None) -> None:
        """筛选条件改变时刷新表格"""
        artist_filter = self.artist_filter_var.get()
        source_filter = self.source_filter_var.get()

        self.filtered_results = []
        for song in self.search_results:
            if artist_filter != '全部':
                artist = song.get("artist", "") or song.get("singer", "")
                if artist_filter not in artist:
                    continue
            if source_filter != '全部':
                source = song.get("source_name", "")
                if source_filter != source:
                    continue
            self.filtered_results.append(song)

        self._populate_tree(self.filtered_results)
        self.status_var.set(f"筛选结果: {len(self.filtered_results)} 首歌曲")

    def _clear_filter(self) -> None:
        """清除所有筛选"""
        self.artist_filter_var.set('全部')
        self.source_filter_var.set('全部')
        self.filtered_results = self.search_results.copy()
        self._on_filter_change()

    def _clear_results(self) -> None:
        """清空搜索结果"""
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.search_results = []
        self.filtered_results = []
        self.download_sel_btn.config(state=tk.DISABLED)
        self.download_all_btn.config(state=tk.DISABLED)
        self.status_var.set("✅ 准备就绪")

    # ---- 搜索 ----

    def _on_search(self) -> None:
        """搜索按钮回调"""
        keyword = self.search_var.get().strip()
        if not keyword:
            messagebox.showwarning("提示", "请输入要搜索的歌曲名")
            return

        self.search_history.add(keyword)
        self.search_combo['values'] = self.search_history.get_all()

        self.search_btn.config(state=tk.DISABLED)
        self._clear_results()
        self._log(f"🔍 正在搜索: {keyword}")
        self.status_var.set("🔍 正在搜索...")

        threading.Thread(
            target=self._search_thread, args=(keyword,), daemon=True,
        ).start()

    def _search_thread(self, keyword: str) -> None:
        """搜索线程（后台）"""
        try:
            results = search_all_platforms(keyword)
            self.search_results = results
            self.filtered_results = results.copy()

            if results:
                self.root.after(0, self._populate_tree, results)
                self.root.after(0, self._update_filter_options)
                self.root.after(
                    0, lambda: self.status_var.set(f"✅ 找到 {len(results)} 首歌曲"),
                )
                self.root.after(0, self.download_sel_btn.config, {'state': tk.NORMAL})
                self.root.after(0, self.download_all_btn.config, {'state': tk.NORMAL})
                self._log(f"搜索完成: 共 {len(results)} 首歌曲（四平台交错排列）")
            else:
                self._log("未找到相关歌曲，请更换关键词")
                self.root.after(
                    0, lambda: self.status_var.set("⚠️ 未找到相关歌曲"),
                )
        except Exception as e:
            self._log(f"搜索出错: {e}")
            self.root.after(
                0, lambda: self.status_var.set("❌ 搜索出错"),
            )
        finally:
            self.root.after(0, self.search_btn.config, {'state': tk.NORMAL})

    def _populate_tree(self, songs: list[dict[str, Any]]) -> None:
        """将歌曲列表填充到 Treeview"""
        for item in self.tree.get_children():
            self.tree.delete(item)

        for idx, song in enumerate(songs, 1):
            title = song.get("title", "") or song.get("name", "")
            artist = song.get("artist", "") or song.get("singer", "")
            source = song.get("source_name", song.get("source", "?"))
            quality = song.get("quality", "?")

            if len(title) > 32:
                title = title[:29] + "..."
            if len(artist) > 22:
                artist = artist[:19] + "..."

            self.tree.insert(
                "", tk.END, values=(idx, title, artist, source, quality),
                tags=("even",) if idx % 2 == 0 else ("odd",),
            )

    # ---- 下载（加入队列） ----

    def _on_download_selected(self) -> None:
        """下载选中的歌曲"""
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
        """下载全部搜索结果"""
        if not self.filtered_results:
            messagebox.showwarning("提示", "没有可下载的歌曲")
            return
        self._add_songs_to_queue(list(self.filtered_results))

    def _add_songs_to_queue(self, songs: list[dict[str, Any]]) -> None:
        """将歌曲加入下载队列并启动"""
        # 确保队列存在
        if self._queue is None:
            self._queue = DownloadQueue(directory=self.download_dir)
            self._queue.on_progress = self._on_queue_progress
            self._queue.on_status_change = self._on_queue_status_change

        # 更新目录（可能已切换）
        self._queue.directory = ensure_download_dir(self.download_dir)

        added = 0
        for song in songs:
            title = song.get("title", "") or song.get("name", "")
            artist = song.get("artist", "") or song.get("singer", "")
            source = song.get("source_name", song.get("source", "?"))
            quality = song.get("quality", "?")
            audio_url = song.get("audio_url", "")

            # 酷我音乐在搜索阶段已有链接，其他平台需要获取详情
            if not audio_url:
                detail = get_song_detail(song)
                if detail:
                    audio_url = detail.get("audio_url", "")
                    title = detail.get("title", title)
                    artist = detail.get("artist", artist)
                    quality = detail.get("quality", quality)

            if not audio_url:
                self._log(f"⚠️ 无法获取下载链接: {artist} - {title}")
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

        # 启动下载（如果未运行）
        if not self._queue_running:
            self._queue_running = True
            self._queue.start_async()

    # ---- 任务面板 ----

    def _add_task_row(self, task: DownloadTask) -> None:
        """在任务面板中添加一行"""
        # 隐藏空状态提示
        if self._task_empty_lbl.winfo_ismapped():
            self._task_empty_lbl.pack_forget()

        row = TaskRow(
            self._task_inner, task,
            on_pause_resume=self._on_task_pause_resume,
            on_cancel=self._on_task_cancel,
        )
        self._task_rows[task.task_id] = row
        row.update_from_task()

    def _refresh_task_panel(self) -> None:
        """刷新所有任务行"""
        for task_id, row in list(self._task_rows.items()):
            # 查找对应的 task 对象
            task = self._find_task(task_id)
            if task:
                row.update_from_task()

    def _find_task(self, task_id: str) -> Optional[DownloadTask]:
        """在队列中查找 task"""
        if self._queue is None:
            return None
        for t in self._queue.tasks:
            if t.task_id == task_id:
                return t
        return None

    def _clear_all_task_rows(self) -> None:
        """清除所有任务行"""
        for row in self._task_rows.values():
            row.destroy()
        self._task_rows.clear()

        # 恢复空状态提示
        if not self._task_empty_lbl.winfo_ismapped():
            self._task_empty_lbl.pack(pady=20)

    # ---- 队列回调（从后台线程通过 root.after 更新 UI） ----

    def _on_queue_progress(self, task: DownloadTask) -> None:
        """下载进度回调（后台线程）"""
        self.root.after(0, self._safe_update_task_row, task.task_id)

    def _on_queue_status_change(self, task: DownloadTask) -> None:
        """任务状态变化回调（后台线程）"""
        self.root.after(0, self._safe_update_task_row, task.task_id)
        # 检查队列是否全部完成
        self.root.after(0, self._check_queue_done)

    def _safe_update_task_row(self, task_id: str) -> None:
        """主线程安全更新任务行"""
        row = self._task_rows.get(task_id)
        if row is None:
            return
        task = self._find_task(task_id)
        if task is None:
            return
        row.update_from_task()

    def _check_queue_done(self) -> None:
        """检查队列是否全部完成，更新按钮状态"""
        if self._queue is None:
            return

        active = sum(
            1 for t in self._queue.tasks
            if t.status.value in ("pending", "fetching", "downloading", "paused")
        )
        if active == 0:
            self._queue_running = False
            self._log("📦 下载队列全部完成")
            self.status_var.set("✅ 下载队列全部完成")

        self._update_queue_buttons()

    def _update_queue_buttons(self) -> None:
        """根据队列状态更新按钮"""
        if self._queue is None or not self._task_rows:
            self.pause_all_btn.config(state=tk.DISABLED)
            self.cancel_all_btn.config(state=tk.DISABLED)
            self.clear_done_btn.config(state=tk.DISABLED)
            return

        has_active = any(
            t.status.value in ("fetching", "downloading")
            for t in (self._queue.tasks if self._queue else [])
        )
        has_paused = any(
            t.status.value == "paused"
            for t in (self._queue.tasks if self._queue else [])
        )
        has_done = any(
            t.status.value in ("completed", "failed", "cancelled")
            for t in (self._queue.tasks if self._queue else [])
        )
        has_any = bool(self._task_rows)

        self.pause_all_btn.config(state=tk.NORMAL if (has_active or has_paused) else tk.DISABLED)
        self.cancel_all_btn.config(state=tk.NORMAL if has_any else tk.DISABLED)
        self.clear_done_btn.config(state=tk.NORMAL if has_done else tk.DISABLED)

    # ---- 任务操作 ----

    def _on_task_pause_resume(self, task: DownloadTask) -> None:
        """暂停/恢复单个任务"""
        if task.status == TaskStatus.DOWNLOADING:
            task.pause()
            self._log(f"⏸ 暂停: {task.display_name}")
        elif task.status == TaskStatus.PAUSED:
            task.resume_after_pause()
            self._log(f"▶ 恢复: {task.display_name}")

        self._safe_update_task_row(task.task_id)
        self._update_queue_buttons()

    def _on_task_cancel(self, task: DownloadTask) -> None:
        """取消单个任务"""
        task.cancel()
        self._log(f"✕ 取消: {task.display_name}")
        self._safe_update_task_row(task.task_id)
        self._update_queue_buttons()

    def _pause_all_tasks(self) -> None:
        """暂停全部活跃任务"""
        if self._queue is None:
            return

        paused = 0
        for t in self._queue.tasks:
            if t.status == TaskStatus.DOWNLOADING:
                t.pause()
                paused += 1

        self._log(f"⏸ 已暂停 {paused} 个任务")
        self._refresh_task_panel()
        self._update_queue_buttons()

    def _cancel_all_tasks(self) -> None:
        """取消全部未完成任务"""
        if self._queue is None:
            return

        cancelled = 0
        for t in self._queue.tasks:
            if t.status.value not in ("completed", "failed", "cancelled"):
                t.cancel()
                cancelled += 1

        self._log(f"✕ 已取消 {cancelled} 个任务")
        self._refresh_task_panel()
        self._queue_running = False
        self._update_queue_buttons()

    def _clear_completed_tasks(self) -> None:
        """清除已完成/失败/取消的任务行"""
        if self._queue is None:
            return

        to_remove: list[str] = []
        for task_id, row in list(self._task_rows.items()):
            task = self._find_task(task_id)
            if task and task.status.value in ("completed", "failed", "cancelled"):
                row.destroy()
                to_remove.append(task_id)

        for task_id in to_remove:
            del self._task_rows[task_id]

        if self._queue:
            self._queue.clear_completed()

        if not self._task_rows:
            self._task_empty_lbl.pack(pady=20)

        self._log(f"🗑 已清除 {len(to_remove)} 个已完成任务")
        self._update_queue_buttons()


# ==================== 程序入口 ====================


def main() -> None:
    root = tk.Tk()
    app = MusicDownloaderGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
