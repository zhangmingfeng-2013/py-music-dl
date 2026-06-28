#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
下载管理器 — 队列下载、断点续传、进度回调

DownloadTask:    单个下载任务，记录状态/进度，支持暂停/取消
DownloadQueue:   管理任务队列，顺序下载，回调通知 GUI/CLI
"""

from __future__ import annotations

import os
import time
import hashlib
import threading
from enum import Enum
from dataclasses import dataclass, field
from typing import Callable

import requests
import urllib3

from utils import (
    log, safe_filename, ensure_download_dir, format_size, ext_from_url,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---- 常量 ----

HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
}

DEFAULT_TIMEOUT: int = 120
CHUNK_SIZE: int = 8192

# ---- 进度回调类型 ----

ProgressCallback = Callable[["DownloadTask"], None]
"""回调签名: callback(task: DownloadTask) -> None"""

# ---- 任务状态与数据 ----


class TaskStatus(str, Enum):
    PENDING    = "pending"
    FETCHING   = "fetching"    # 正在获取详情链接
    DOWNLOADING = "downloading"
    PAUSED     = "paused"
    COMPLETED  = "completed"
    FAILED     = "failed"
    CANCELLED  = "cancelled"


@dataclass
class DownloadTask:
    """单个下载任务"""

    task_id: str
    title: str
    artist: str
    source: str = ""

    # 详情链接（由外部填充）
    audio_url: str = ""
    quality: str = "?"

    # 文件路径
    directory: str = ""
    filepath: str = ""

    # 进度
    total_size: int = 0
    downloaded: int = 0
    status: TaskStatus = TaskStatus.PENDING

    # 错误信息
    error: str = ""

    # 内部控制
    # _pause_event 初始为 set（不阻塞），pause 时 clear（阻塞 wait）
    _pause_event: threading.Event = field(
        default_factory=lambda: threading.Event(), repr=False
    )
    _cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)

    def __post_init__(self) -> None:
        """初始化后设置 _pause_event 为 set（不暂停状态）"""
        self._pause_event.set()

    @property
    def progress_pct(self) -> float:
        """下载进度百分比 0-100"""
        if self.total_size <= 0:
            return 0.0
        return self.downloaded / self.total_size * 100

    @property
    def display_name(self) -> str:
        return f"{self.artist} - {self.title}"

    @property
    def is_active(self) -> bool:
        return self.status in (TaskStatus.FETCHING, TaskStatus.DOWNLOADING)

    def pause(self) -> None:
        """暂停下载 — 清除事件使 wait() 阻塞"""
        if self.status == TaskStatus.DOWNLOADING:
            self._pause_event.clear()
            self.status = TaskStatus.PAUSED
            log.info("暂停: %s", self.display_name)

    def resume_after_pause(self) -> None:
        """恢复下载 — 设置事件使 wait() 返回"""
        self._pause_event.set()
        self.status = TaskStatus.DOWNLOADING

    def cancel(self) -> None:
        """取消下载"""
        if self.status not in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
            self._cancel_event.set()
            self._pause_event.set()  # 同时解除阻塞
            self.status = TaskStatus.CANCELLED
            log.info("取消: %s", self.display_name)


# ---- 下载队列 ----


class DownloadQueue:
    """
    下载队列管理器

    用法:
        queue = DownloadQueue(directory="downloaded_music")
        queue.on_progress = lambda task: print(task.progress_pct)
        queue.add_task(title="晴天", artist="周杰伦", audio_url="...")
        queue.start()          # 阻塞直到所有任务完成
        # 或
        queue.start_async()    # 后台线程
    """

    def __init__(self, directory: str = "downloaded_music",
                 max_retries: int = 2):
        self.directory = ensure_download_dir(directory)
        self.max_retries = max_retries
        self._tasks: list[DownloadTask] = []
        self._current_idx: int = -1
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

        # 回调
        self.on_progress: ProgressCallback | None = None
        self.on_status_change: ProgressCallback | None = None

    # ---- 属性 ----

    @property
    def tasks(self) -> list[DownloadTask]:
        with self._lock:
            return list(self._tasks)

    @property
    def current_task(self) -> DownloadTask | None:
        with self._lock:
            if 0 <= self._current_idx < len(self._tasks):
                return self._tasks[self._current_idx]
            return None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ---- 任务管理 ----

    def add_task(self, *, title: str, artist: str, audio_url: str,
                 quality: str = "?", source: str = "",
                 task_id: str | None = None) -> DownloadTask:
        """添加一个下载任务到队列末尾"""
        if task_id is None:
            raw = f"{artist}-{title}-{audio_url}-{time.time()}"
            task_id = hashlib.md5(raw.encode()).hexdigest()[:12]

        ext = ext_from_url(audio_url)
        filename = f"{safe_filename(f'{artist} - {title}')}.{ext}"
        filepath = os.path.join(self.directory, filename)

        task = DownloadTask(
            task_id=task_id, title=title, artist=artist, source=source,
            audio_url=audio_url, quality=quality,
            directory=self.directory, filepath=filepath,
        )
        with self._lock:
            self._tasks.append(task)
        log.debug("添加任务: %s", task.display_name)
        self._notify_status(task)
        return task

    def remove_task(self, task_id: str) -> bool:
        """移除指定任务（仅限未开始或已完成的任务）"""
        with self._lock:
            for i, t in enumerate(self._tasks):
                if t.task_id == task_id:
                    if t.is_active:
                        return False
                    self._tasks.pop(i)
                    if i < self._current_idx:
                        self._current_idx -= 1
                    return True
        return False

    def clear_completed(self) -> int:
        """清除已完成/失败/取消的任务，返回清除数量"""
        with self._lock:
            before = len(self._tasks)
            self._tasks = [
                t for t in self._tasks
                if t.status in (TaskStatus.PENDING,)
            ]
            self._current_idx = -1
            return before - len(self._tasks)

    # ---- 流程控制 ----

    def start(self) -> None:
        """阻塞运行下载队列"""
        self._run()

    def start_async(self) -> threading.Thread:
        """后台线程运行下载队列"""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self._thread

    def pause_all(self) -> None:
        """暂停所有正在下载的任务"""
        with self._lock:
            for t in self._tasks:
                if t.status == TaskStatus.DOWNLOADING:
                    t.pause()

    def cancel_all(self) -> None:
        """取消所有任务"""
        with self._lock:
            for t in self._tasks:
                t.cancel()

    # ---- 内部 ----

    def _run(self) -> None:
        """主循环：逐个处理队列中的任务"""
        while True:
            task = self._next_pending()
            if task is None:
                break
            self._process_task(task)

    def _next_pending(self) -> DownloadTask | None:
        with self._lock:
            for i in range(len(self._tasks)):
                if self._tasks[i].status == TaskStatus.PENDING:
                    self._tasks[i].status = TaskStatus.FETCHING
                    self._current_idx = i
                    return self._tasks[i]
            return None

    def _process_task(self, task: DownloadTask) -> None:
        """处理单个任务：下载并写文件"""
        self._notify_status(task)

        if task._cancel_event.is_set():
            task.status = TaskStatus.CANCELLED
            self._notify_status(task)
            return

        task.status = TaskStatus.DOWNLOADING
        self._notify_status(task)

        # HTTP Range 断点续传
        existing_size = 0
        if os.path.exists(task.filepath):
            existing_size = os.path.getsize(task.filepath)

        headers = dict(HEADERS)
        mode = "ab" if existing_size > 0 else "wb"
        if existing_size > 0:
            headers["Range"] = f"bytes={existing_size}-"
            log.info("断点续传: %s (已有 %s)", task.display_name, format_size(existing_size))

        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                log.info("重试 %d/%d: %s", attempt, self.max_retries, task.display_name)
                # 重试前检查文件状态（可能已部分写入）
                if os.path.exists(task.filepath):
                    existing_size = os.path.getsize(task.filepath)
                    if existing_size > 0:
                        headers["Range"] = f"bytes={existing_size}-"
                        mode = "ab"

            try:
                resp = requests.get(
                    task.audio_url, headers=headers, stream=True,
                    timeout=DEFAULT_TIMEOUT, verify=False,
                )
                resp.raise_for_status()

                # 计算总大小
                if "content-range" in resp.headers:
                    # 断点续传响应：Content-Range: bytes 1000-2000/5000
                    total = int(resp.headers["content-range"].split("/")[-1])
                else:
                    cl = resp.headers.get("content-length")
                    total = int(cl) if cl else 0

                task.total_size = total if total > 0 else (existing_size + total)
                task.downloaded = existing_size
                if not task.total_size:
                    task.total_size = existing_size

                self._notify_progress(task)

                with open(task.filepath, mode) as f:
                    for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                        if chunk:
                            # 检查暂停 — wait() 在 event 为 clear 时阻塞
                            task._pause_event.wait()

                            # 检查取消
                            if task._cancel_event.is_set():
                                task.status = TaskStatus.CANCELLED
                                self._notify_status(task)
                                return

                            f.write(chunk)
                            task.downloaded += len(chunk)
                            self._notify_progress(task)

                task.status = TaskStatus.COMPLETED
                self._notify_status(task)
                log.info("下载完成: %s → %s", task.display_name, task.filepath)
                return

            except requests.RequestException as e:
                task.error = str(e)
                log.warning("下载失败: %s (%s)", task.display_name, e)
                if attempt < self.max_retries:
                    time.sleep(1 * (attempt + 1))
                else:
                    task.status = TaskStatus.FAILED
                    self._notify_status(task)
            except IOError as e:
                task.error = str(e)
                task.status = TaskStatus.FAILED
                self._notify_status(task)
                return

    def _notify_progress(self, task: DownloadTask) -> None:
        if self.on_progress:
            try:
                self.on_progress(task)
            except Exception:
                pass

    def _notify_status(self, task: DownloadTask) -> None:
        if self.on_status_change:
            try:
                self.on_status_change(task)
            except Exception:
                pass
