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
from typing import Callable, Optional

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

DEFAULT_TIMEOUT: int = 60
CHUNK_SIZE: int = 8192

# ---- 速度限制（令牌桶）----


class RateLimiter:
    """线程安全令牌桶限速器。

    rate_bps <= 0 表示不限速；桶容量为 1 秒额度（允许短时突发）。
    可被多个下载线程共享（全局限速），也可每任务独立（单任务限速）。
    """

    def __init__(self, rate_bps: int = 0) -> None:
        self._rate = max(0, int(rate_bps))
        self._lock = threading.Lock()
        self._tokens: float = float(self._rate)  # 初始满桶
        self._last = time.monotonic()

    def set_rate(self, rate_bps: int) -> None:
        """动态调整限速（0 = 不限速），立即生效。"""
        with self._lock:
            self._rate = max(0, int(rate_bps))
            if self._rate > 0:
                # 换额后桶内余量不超过新额度 1 秒，避免瞬间突发
                self._tokens = min(self._tokens, float(self._rate))

    @property
    def rate_bps(self) -> int:
        return self._rate

    def consume(self, size: int) -> None:
        """申领 size 字节额度，不足则阻塞等待。"""
        while True:
            with self._lock:
                if self._rate <= 0:
                    return
                now = time.monotonic()
                self._tokens = min(
                    float(self._rate),
                    self._tokens + (now - self._last) * self._rate,
                )
                self._last = now
                if self._tokens >= size:
                    self._tokens -= size
                    return
                wait = (size - self._tokens) / self._rate
            # 分段睡眠，保证设置变更/暂停能快速响应
            time.sleep(min(wait, 0.05))

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

    # 实时速度（字节/秒，EWMA 平滑；非下载状态为 0）
    speed_bps: float = 0.0

    # 后处理元数据：album/year/cover_url/lrc_url/lyrics 及平台身份字段
    meta: dict = field(default_factory=dict)
    # 后处理阶段提示（转码中/写入元数据…），供 UI 实时展示
    remark: str = ""

    # 错误信息
    error: str = ""

    # 内部控制
    # _pause_event 初始为 set（不阻塞），pause 时 clear（阻塞 wait）
    _pause_event: threading.Event = field(
        default_factory=lambda: threading.Event(), repr=False
    )
    _cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _speed_ts: float = field(default=0.0, repr=False)

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
            self.speed_bps = 0.0
            log.info("暂停: %s", self.display_name)

    def resume_after_pause(self) -> None:
        """恢复下载 — 设置事件使 wait() 返回"""
        self._speed_ts = 0.0  # 丢弃暂停期间的时间差，避免速度被平均为近 0
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
                 max_retries: int = 2,
                 per_task_limit: int = 0,
                 global_limiter: Optional["RateLimiter"] = None,
                 post_options: object = None):
        self.directory = ensure_download_dir(directory)
        self.max_retries = max_retries
        # 单任务限速（每个任务独立令牌桶）；0 = 不限速
        self.per_task_limit = max(0, int(per_task_limit))
        # 全局限速（队列内所有任务共享）；外部可传入同一个实例跨队列共享
        self.global_limiter = global_limiter
        # 下载后处理选项（media.PostOptions）；None = 不做任何后处理
        self.post_options = post_options
        self._tasks: list[DownloadTask] = []
        self._current_idx: int = -1
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        # 新增任务唤醒事件 + 最近入队时间：支持批量导入“先启动、边搜边入队”
        self._wake_event = threading.Event()
        self._last_add_ts = time.time()

        # 回调
        self.on_progress: ProgressCallback | None = None
        self.on_status_change: ProgressCallback | None = None
        # 同名文件冲突回调：返回 "overwrite" | "skip" | "rename"
        # 由调用方（GUI）在 UI 线程弹窗确认；下载线程阻塞等待返回值
        self.on_file_exists: Callable[[DownloadTask], str] | None = None

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
                 meta: dict | None = None,
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
            meta=dict(meta or {}),
        )
        with self._lock:
            self._tasks.append(task)
            self._last_add_ts = time.time()
        self._wake_event.set()
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

    def set_limits(self, per_task_bps: int, global_bps: int) -> None:
        """运行中动态调整限速（字节/秒，0 = 不限速）。"""
        self.per_task_limit = max(0, int(per_task_bps))
        if global_bps and global_bps > 0:
            if self.global_limiter is None:
                self.global_limiter = RateLimiter(global_bps)
            else:
                self.global_limiter.set_rate(global_bps)
        elif self.global_limiter is not None:
            self.global_limiter.set_rate(0)

    def set_post_options(self, options: object) -> None:
        """动态更新下载后处理选项（media.PostOptions）。"""
        self.post_options = options

    @property
    def total_speed_bps(self) -> float:
        """当前所有下载中任务的实时速度之和。"""
        with self._lock:
            return sum(
                t.speed_bps for t in self._tasks
                if t.status == TaskStatus.DOWNLOADING
            )

    # ---- 内部 ----

    def _run(self) -> None:
        """主循环：逐个处理队列中的任务。

        没有待办任务时最多空闲等待 20 秒（每 2 秒被新任务唤醒），
        以支持批量导入边搜索边入队；超时无新任务则退出。
        """
        IDLE_TIMEOUT = 20.0
        while True:
            task = self._next_pending()
            if task is not None:
                self._process_task(task)
                continue
            self._wake_event.clear()
            # clear 之后、wait 之前入队的任务不会丢失（事件已 set 立即返回）
            if self._has_pending():
                continue
            if time.time() - self._last_add_ts > IDLE_TIMEOUT:
                break
            self._wake_event.wait(timeout=2.0)

    def _has_pending(self) -> bool:
        with self._lock:
            return any(t.status == TaskStatus.PENDING for t in self._tasks)

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

        # 同名文件冲突检查（下载前）
        if os.path.exists(task.filepath) and self.on_file_exists is not None:
            action = self.on_file_exists(task)
            if action == "skip":
                task.status = TaskStatus.CANCELLED
                task.error = "用户取消：已存在同名文件"
                self._notify_status(task)
                return
            elif action == "rename":
                task.filepath = self._unique_filepath(task.filepath)
                log.info("重命名下载: %s → %s", task.display_name, task.filepath)
            elif action == "overwrite":
                if os.path.exists(task.filepath):
                    try:
                        os.remove(task.filepath)
                    except OSError as e:
                        task.error = f"无法删除旧文件: {e}"
                        task.status = TaskStatus.FAILED
                        self._notify_status(task)
                        return

        task.status = TaskStatus.DOWNLOADING
        task.speed_bps = 0.0
        task._speed_ts = 0.0
        self._notify_status(task)

        # 单任务限速桶（限额动态跟随 self.per_task_limit）
        task_limiter: Optional[RateLimiter] = None

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
                                task.speed_bps = 0.0
                                self._notify_status(task)
                                return

                            # 限速：先全局后单任务（两者同时生效，取更严格约束）
                            if self.global_limiter is not None:
                                self.global_limiter.consume(len(chunk))
                            if self.per_task_limit > 0:
                                if task_limiter is None:
                                    task_limiter = RateLimiter(self.per_task_limit)
                                task_limiter.set_rate(self.per_task_limit)
                                task_limiter.consume(len(chunk))

                            # 限速等待期间可能已暂停/取消，再校验一次
                            task._pause_event.wait()
                            if task._cancel_event.is_set():
                                task.status = TaskStatus.CANCELLED
                                task.speed_bps = 0.0
                                self._notify_status(task)
                                return

                            f.write(chunk)
                            task.downloaded += len(chunk)

                            # 实时速度（EWMA 平滑）
                            now = time.monotonic()
                            if task._speed_ts > 0:
                                dt = now - task._speed_ts
                                if dt > 0:
                                    inst = len(chunk) / dt
                                    task.speed_bps = (
                                        inst if task.speed_bps <= 0
                                        else task.speed_bps * 0.6 + inst * 0.4
                                    )
                            task._speed_ts = now

                            self._notify_progress(task)

                task.speed_bps = 0.0

                # 下载后处理：转码 / 歌词 / 元数据（失败不影响已下载文件）
                if self.post_options is not None:
                    self._run_post_process(task)

                task.status = TaskStatus.COMPLETED
                task.remark = ""
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
                    task.speed_bps = 0.0
                    self._notify_status(task)
            except IOError as e:
                task.error = str(e)
                task.status = TaskStatus.FAILED
                task.speed_bps = 0.0
                self._notify_status(task)
                return

    def _run_post_process(self, task: DownloadTask) -> None:
        """执行下载后处理管线（转码/歌词/标签），内部吞掉所有异常。"""
        try:
            from media import post_process
            from api import fetch_lyrics
            post_process(
                task, self.post_options,
                lyrics_fetcher=fetch_lyrics,
                notify=self._notify_progress,
            )
        except Exception:
            log.exception("后处理异常: %s", task.display_name)

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

    @staticmethod
    def _unique_filepath(filepath: str) -> str:
        """生成不冲突的新路径：artist - title (1).ext"""
        base, ext = os.path.splitext(filepath)
        i = 1
        while os.path.exists(f"{base} ({i}){ext}"):
            i += 1
        return f"{base} ({i}){ext}"
