#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""下载引擎：队列调度、断点续传、限速与进度回调。

核心类型
    * :class:`DownloadTask` —— 单个任务的状态机与进度数据
    * :class:`DownloadQueue` —— 顺序消费队列，向 GUI/CLI 回调进度
    * :class:`RateLimiter` —— 线程安全令牌桶，支持全局/单任务双重限速

线程模型
    队列在单个后台线程中顺序执行任务；任务状态由该线程写入，UI 只读取。
    ``pause`` / ``cancel`` 通过 ``threading.Event`` 与下载线程通信。

安全边界
    * 同名文件默认不覆盖：无 UI 决策回调时跳过，避免把新数据追加到旧文件；
    * 仅对「本次任务已写入的字节」做 Range 续传；服务端忽略 Range 时
      自动回退为完整重下，防止文件被重复拼接；
    * 任何未预期异常都会把任务标记为失败并继续处理后续任务，队列线程
      不会因单任务异常而退出。
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, cast

import requests
import urllib3

from naming import render_filename
from utils import (
    USER_AGENT,
    ensure_download_dir,
    ext_from_url,
    format_size,
    log,
    safe_filename,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

HEADERS: dict[str, str] = {"User-Agent": USER_AGENT}
DEFAULT_TIMEOUT: int = 60
CHUNK_SIZE: int = 8192

#: 队列空闲多久后退出（秒）。支持「先启动队列、边搜索边入队」。
IDLE_TIMEOUT: float = 20.0
#: 空闲等待的轮询间隔（秒）
WAKE_INTERVAL: float = 2.0

_CONTENT_RANGE_RE = re.compile(
    r"bytes\s+(\d+)-(\d+)/(\d+|\*)", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# 速度限制（令牌桶）
# ---------------------------------------------------------------------------


class RateLimiter:
    """线程安全令牌桶限速器。

    ``rate_bps <= 0`` 表示不限速；桶容量为 1 秒额度（允许短时突发）。
    可被多个下载线程共享（全局限速），也可每任务独立（单任务限速）。

    当单次申领量大于桶容量时，按「1 秒额度」切片消费，避免令牌永远
    攒不够导致的死循环（低限速 + 大 chunk 场景）。
    """

    _SLEEP_SLICE: float = 0.05

    def __init__(self, rate_bps: int = 0) -> None:
        self._rate = max(0, int(rate_bps))
        self._lock = threading.Lock()
        self._tokens = float(self._rate)  # 初始满桶
        self._last = time.monotonic()

    def set_rate(self, rate_bps: int) -> None:
        """动态调整限速（0 = 不限速），下一次 :meth:`consume` 即生效。"""
        with self._lock:
            self._rate = max(0, int(rate_bps))
            if self._rate > 0:
                # 换额后桶内余量不超过新额度 1 秒，避免瞬间突发
                self._tokens = min(self._tokens, float(self._rate))

    @property
    def rate_bps(self) -> int:
        """当前限速（字节/秒）。"""
        return self._rate

    def consume(self, size: int,
                cancel_event: Optional[threading.Event] = None) -> bool:
        """申领 ``size`` 字节额度，不足则阻塞等待。

        Args:
            size: 本次需要消费的字节数。
            cancel_event: 可选的取消事件；置位后立即返回 ``False``。

        Returns:
            ``True`` 表示额度已消费；``False`` 表示被取消。
        """
        remaining = max(0, int(size))
        while remaining > 0:
            if cancel_event is not None and cancel_event.is_set():
                return False
            with self._lock:
                rate = self._rate
                if rate <= 0:
                    return True
                # 单次最多消费 1 秒额度：rate 足够大时直接扣减，
                # 低限速时拆成多次等待，保证有限时间内完成。
                chunk = min(remaining, rate)
                now = time.monotonic()
                self._tokens = min(
                    float(rate),
                    self._tokens + (now - self._last) * rate,
                )
                self._last = now
                if self._tokens >= chunk:
                    self._tokens -= chunk
                    remaining -= chunk
                    continue
                wait = (chunk - self._tokens) / rate
            # 分段睡眠，保证限速调整 / 取消能快速响应
            time.sleep(min(wait, self._SLEEP_SLICE))
        return True


# ---------------------------------------------------------------------------
# 任务状态与数据
# ---------------------------------------------------------------------------

ProgressCallback = Callable[["DownloadTask"], None]
"""回调签名：``callback(task) -> None``。"""

FileExistsCallback = Callable[["DownloadTask"], str]
"""同名文件回调，返回 ``overwrite`` / ``skip`` / ``rename``。"""


class TaskStatus(str, Enum):
    """任务生命周期状态。值同时用于 UI 文案映射，保持短横线小写。"""

    PENDING = "pending"
    FETCHING = "fetching"          # 正在获取详情链接
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_running(self) -> bool:
        """正在占用下载线程（不含暂停 / 排队）。"""
        return self in (TaskStatus.FETCHING, TaskStatus.DOWNLOADING)

    @property
    def is_terminal(self) -> bool:
        """终态：不会再被队列处理。"""
        return self in (
            TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED,
        )

    @property
    def is_pending(self) -> bool:
        """等待队列调度。"""
        return self is TaskStatus.PENDING


@dataclass
class DownloadTask:
    """单个下载任务。"""

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
    meta: dict[str, Any] = field(default_factory=dict)
    # 后处理阶段提示（转码中/写入元数据…），供 UI 实时展示
    remark: str = ""

    # 错误信息
    error: str = ""

    # 内部控制
    # _pause_event 初始为 set（不阻塞），pause 时 clear（阻塞 wait）
    _pause_event: threading.Event = field(
        default_factory=threading.Event, repr=False
    )
    _cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _speed_ts: float = field(default=0.0, repr=False)

    def __post_init__(self) -> None:
        """构造后进入「未暂停」状态。"""
        self._pause_event.set()

    @property
    def progress_pct(self) -> float:
        """下载进度百分比，钳制在 0–100 之间。"""
        if self.total_size <= 0:
            return 0.0
        return min(100.0, max(0.0, self.downloaded / self.total_size * 100))

    @property
    def display_name(self) -> str:
        """``歌手 - 歌名``，供日志与任务行展示。"""
        return f"{self.artist} - {self.title}"

    @property
    def is_active(self) -> bool:
        """任务是否仍占用队列（下载中 / 获取链接 / 暂停中）。"""
        return self.status in (
            TaskStatus.FETCHING, TaskStatus.DOWNLOADING, TaskStatus.PAUSED,
        )

    def pause(self) -> None:
        """暂停下载：清除事件使下载线程阻塞在 ``wait()``。"""
        if self.status is TaskStatus.DOWNLOADING:
            self._pause_event.clear()
            self.status = TaskStatus.PAUSED
            self.speed_bps = 0.0
            log.info("暂停: %s", self.display_name)

    def resume_after_pause(self) -> None:
        """恢复下载：设置事件使 ``wait()`` 返回。"""
        if self.status is not TaskStatus.PAUSED:
            return
        self._speed_ts = 0.0  # 丢弃暂停期间的时间差，避免速度被平均为近 0
        self._pause_event.set()
        self.status = TaskStatus.DOWNLOADING

    def cancel(self) -> None:
        """取消任务（完成或已取消的任务不受影响）。"""
        if self.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
            return
        self._cancel_event.set()
        self._pause_event.set()  # 同时解除暂停阻塞
        self.status = TaskStatus.CANCELLED
        log.info("取消: %s", self.display_name)


class _DownloadCancelled(Exception):
    """内部控制流：任务被用户取消。"""


class _RetryableError(Exception):
    """内部控制流：可重试的瞬时错误。"""


# ---------------------------------------------------------------------------
# 下载队列
# ---------------------------------------------------------------------------


class DownloadQueue:
    """下载队列管理器。

    用法::

        queue = DownloadQueue(directory="downloaded_music")
        queue.on_progress = lambda task: print(task.progress_pct)
        queue.add_task(title="晴天", artist="周杰伦", audio_url="...")
        queue.start()          # 阻塞直到队列空闲超时
        # 或
        queue.start_async()    # 后台线程，可重复调用（幂等）
    """

    def __init__(self, directory: str = "downloaded_music",
                 max_retries: int = 2,
                 per_task_limit: int = 0,
                 global_limiter: Optional[RateLimiter] = None,
                 post_options: object = None) -> None:
        self.directory = ensure_download_dir(directory)
        self.max_retries = max(0, int(max_retries))
        # 单任务限速（每个任务独立令牌桶）；0 = 不限速
        self.per_task_limit = max(0, int(per_task_limit))
        # 全局限速（队列内所有任务共享）；外部可传入同一个实例跨队列共享
        self.global_limiter = global_limiter
        # 下载后处理选项（media.PostOptions）；None = 不做任何后处理
        self.post_options = post_options

        self._tasks: list[DownloadTask] = []
        self._current_idx: int = -1
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._thread_lock = threading.Lock()
        # 新增任务唤醒事件 + 最近入队时间：支持批量导入「先启动、边搜边入队」
        self._wake_event = threading.Event()
        self._last_add_ts = time.time()

        # 回调
        self.on_progress: Optional[ProgressCallback] = None
        self.on_status_change: Optional[ProgressCallback] = None
        # 同名文件冲突回调：返回 "overwrite" | "skip" | "rename"
        # 由调用方（GUI）在 UI 线程弹窗确认；下载线程阻塞等待返回值
        self.on_file_exists: Optional[FileExistsCallback] = None

    # ---- 属性 ----

    @property
    def tasks(self) -> list[DownloadTask]:
        """任务快照（副本，避免外部在迭代时被并发修改）。"""
        with self._lock:
            return list(self._tasks)

    @property
    def current_task(self) -> Optional[DownloadTask]:
        """当前正在处理的任务。"""
        with self._lock:
            if 0 <= self._current_idx < len(self._tasks):
                return self._tasks[self._current_idx]
            return None

    @property
    def is_running(self) -> bool:
        """后台队列线程是否存活。"""
        thread = self._thread
        return thread is not None and thread.is_alive()

    @property
    def total_speed_bps(self) -> float:
        """当前所有下载中任务的实时速度之和。"""
        with self._lock:
            return sum(
                task.speed_bps for task in self._tasks
                if task.status is TaskStatus.DOWNLOADING
            )

    # ---- 任务管理 ----

    def add_task(self, *, title: str, artist: str, audio_url: str,
                 quality: str = "?", source: str = "",
                 meta: Optional[dict[str, Any]] = None,
                 task_id: Optional[str] = None,
                 name_template: Optional[str] = None) -> DownloadTask:
        """添加一个下载任务到队列末尾并返回该任务。

        Args:
            title / artist: 展示名与标签元数据。
            audio_url: 直链地址。
            quality / source: 音质标签与平台标识。
            meta: 后处理元数据（专辑/年份/封面/歌词链接等）。
            task_id: 外部指定 ID；缺省按内容哈希生成。
            name_template: 自定义命名模板；为空或非法时回退默认
                ``"artist - title"``。
        """
        clean_title = str(title or "").strip()
        clean_artist = str(artist or "").strip()
        clean_url = str(audio_url or "").strip()
        clean_meta = dict(meta) if isinstance(meta, dict) else {}

        if task_id is None:
            raw = f"{clean_artist}-{clean_title}-{clean_url}-{time.time()}"
            task_id = hashlib.md5(  # noqa: S324  仅用于生成短 ID，非安全用途
                raw.encode(), usedforsecurity=False
            ).hexdigest()[:12]

        ext = ext_from_url(clean_url)
        template_meta = dict(clean_meta)
        template_meta.setdefault("title", clean_title)
        template_meta.setdefault("artist", clean_artist)
        template_meta.setdefault("source", source)
        template_meta.setdefault("quality", quality)
        try:
            filename = render_filename(
                name_template or "", template_meta, ext,
                fallback=f"{clean_artist} - {clean_title}",
            )
        except Exception:  # noqa: BLE001  命名异常不得阻塞下载
            log.exception("命名模板渲染失败，回退默认命名: %s", template_meta)
            filename = (
                f"{safe_filename(f'{clean_artist} - {clean_title}')}.{ext}"
            )

        task = DownloadTask(
            task_id=task_id,
            title=clean_title,
            artist=clean_artist,
            source=source,
            audio_url=clean_url,
            quality=quality,
            directory=self.directory,
            filepath=os.path.join(self.directory, filename),
            meta=clean_meta,
        )
        with self._lock:
            self._tasks.append(task)
            self._last_add_ts = time.time()
        self._wake_event.set()
        log.debug("添加任务: %s", task.display_name)
        self._notify_status(task)
        return task

    def remove_task(self, task_id: str) -> bool:
        """移除指定任务；正在下载 / 暂停中的任务不可移除。"""
        with self._lock:
            for index, task in enumerate(self._tasks):
                if task.task_id != task_id:
                    continue
                # 下载 / 获取链接 / 暂停中的任务不可移除；排队中与终态可移除
                if task.is_active:
                    return False
                self._tasks.pop(index)
                if index < self._current_idx:
                    self._current_idx -= 1
                return True
        return False

    def clear_completed(self) -> int:
        """清除终态任务（完成 / 失败 / 取消），返回清除数量。

        保留排队、获取链接、下载中与暂停中的任务；当前任务索引会被
        重新定位，避免清除后 ``current_task`` 指向错误的元素。
        """
        with self._lock:
            current = (
                self._tasks[self._current_idx]
                if 0 <= self._current_idx < len(self._tasks) else None
            )
            before = len(self._tasks)
            self._tasks = [
                task for task in self._tasks if not task.status.is_terminal
            ]
            self._current_idx = next(
                (index for index, task in enumerate(self._tasks) if task is current),
                -1,
            )
            return before - len(self._tasks)

    # ---- 流程控制 ----

    def start(self) -> None:
        """阻塞运行下载队列，直到队列空闲超时。

        若已有后台线程在运行，则等待其结束，避免两个消费者并发抢占任务。
        """
        thread = self._thread
        if thread is not None and thread.is_alive():
            if thread is not threading.current_thread():
                thread.join()
            return
        self._run()

    def start_async(self) -> threading.Thread:
        """在后台线程运行队列；重复调用返回同一存活线程（幂等）。"""
        with self._thread_lock:
            if self._thread is not None and self._thread.is_alive():
                return self._thread
            self._thread = threading.Thread(
                target=self._run, name="musicdl-queue", daemon=True
            )
            self._thread.start()
            return self._thread

    def pause_all(self) -> None:
        """暂停所有正在下载的任务。"""
        for task in self.tasks:
            if task.status is TaskStatus.DOWNLOADING:
                task.pause()

    def cancel_all(self) -> None:
        """取消所有未完成任务。"""
        for task in self.tasks:
            task.cancel()

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
        """动态更新下载后处理选项（``media.PostOptions``）。"""
        self.post_options = options

    # ---- 内部：队列循环 ----

    def _run(self) -> None:
        """主循环：逐个处理队列任务；无新任务且空闲超时后退出。"""
        while True:
            task = self._next_pending()
            if task is not None:
                self._process_safely(task)
                continue

            self._wake_event.clear()
            # clear 之后、wait 之前入队的任务不会丢失（事件已 set 立即返回）
            if self._has_pending():
                continue
            if time.time() - self._last_add_ts > IDLE_TIMEOUT:
                break
            self._wake_event.wait(timeout=WAKE_INTERVAL)

    def _process_safely(self, task: DownloadTask) -> None:
        """执行单任务；兜底任何未预期异常，保证队列线程不中断。"""
        try:
            self._process_task(task)
        except Exception as exc:  # noqa: BLE001  单任务异常不得终止队列
            log.exception("下载任务异常: %s", task.display_name)
            self._finish_failed(task, f"未预期异常: {exc}")

    def _has_pending(self) -> bool:
        with self._lock:
            return any(task.status.is_pending for task in self._tasks)

    def _next_pending(self) -> Optional[DownloadTask]:
        """取出下一个待处理任务并置为 FETCHING。"""
        with self._lock:
            for index, task in enumerate(self._tasks):
                if task.status.is_pending:
                    task.status = TaskStatus.FETCHING
                    self._current_idx = index
                    return task
            return None

    # ---- 内部：单任务处理 ----

    def _process_task(self, task: DownloadTask) -> None:
        """处理单个任务：冲突检查 → 下载（含重试）→ 后处理 → 完成。"""
        self._notify_status(task)

        if task._cancel_event.is_set():
            self._finish_cancelled(task)
            return

        if not self._resolve_file_conflict(task):
            return

        task.status = TaskStatus.DOWNLOADING
        task.speed_bps = 0.0
        task._speed_ts = 0.0
        self._notify_status(task)

        # 每任务独立令牌桶；初始速率可为 0，运行中可通过 set_limits 动态提高
        task_limiter = RateLimiter(self.per_task_limit)
        resume_offset = 0
        last_error = ""

        for attempt in range(self.max_retries + 1):
            if task._cancel_event.is_set():
                self._finish_cancelled(task)
                return
            if attempt > 0:
                log.info("重试 %d/%d: %s", attempt, self.max_retries, task.display_name)
                # 只续传本任务已经写入的字节（文件由本任务创建/截断）
                resume_offset = self._file_size(task.filepath)

            try:
                self._download_once(task, resume_offset, task_limiter)
            except _DownloadCancelled:
                self._finish_cancelled(task)
                return
            except requests.RequestException as exc:
                last_error = str(exc)
                task.error = last_error
                log.warning("下载失败: %s (%s)", task.display_name, exc)
                if attempt >= self.max_retries:
                    self._finish_failed(task, last_error)
                    return
                time.sleep(1 * (attempt + 1))
                continue
            except OSError as exc:
                self._finish_failed(task, str(exc))
                return
            else:
                self._finish_completed(task)
                return

        self._finish_failed(task, last_error or "下载失败")

    def _resolve_file_conflict(self, task: DownloadTask) -> bool:
        """处理同名文件；返回 ``True`` 表示可以继续下载。

        * 无回调（CLI / 程序化调用）：跳过并标记取消，绝不把新数据追加到
          未知内容的旧文件；
        * 有回调（GUI）：由用户选择覆盖 / 跳过 / 重命名。
        """
        if not os.path.exists(task.filepath):
            return True

        callback = cast(Optional[FileExistsCallback], self.on_file_exists)
        if not callable(callback):
            log.info("同名文件已存在，跳过: %s", task.filepath)
            task.error = "已存在同名文件（未覆盖）"
            task.status = TaskStatus.CANCELLED
            self._notify_status(task)
            return False

        try:
            # pylint 无法根据 Optional[Callable] 注解完成收窄，此处为误报
            action = callback(task)  # pylint: disable=not-callable
        except Exception:  # noqa: BLE001  回调异常按跳过处理
            log.exception("同名文件回调异常: %s", task.display_name)
            action = "skip"

        if action == "rename":
            task.filepath = self._unique_filepath(task.filepath)
            log.info("重命名下载: %s → %s", task.display_name, task.filepath)
            return True

        if action == "overwrite":
            try:
                os.remove(task.filepath)
            except OSError as exc:
                self._finish_failed(task, f"无法删除旧文件: {exc}")
                return False
            return True

        task.error = "用户取消：已存在同名文件"
        task.status = TaskStatus.CANCELLED
        self._notify_status(task)
        return False

    def _download_once(self, task: DownloadTask, resume_offset: int,
                       task_limiter: Optional[RateLimiter]) -> None:
        """执行一次 HTTP 下载；成功返回，失败抛出由调用方决定是否重试。"""
        headers = dict(HEADERS)
        if resume_offset > 0:
            headers["Range"] = f"bytes={resume_offset}-"
            log.info("断点续传: %s (已有 %s)",
                     task.display_name, format_size(resume_offset))

        response = requests.get(
            task.audio_url, headers=headers, stream=True,
            timeout=DEFAULT_TIMEOUT, verify=False,
        )
        response.raise_for_status()

        resumed, start, total = self._resolve_download_range(
            response, resume_offset
        )
        if resumed:
            task.downloaded = start
            task.total_size = total
            mode = "ab"
        else:
            if resume_offset > 0:
                log.info("服务器不支持断点续传，重新完整下载: %s", task.display_name)
            task.downloaded = 0
            task.total_size = total
            mode = "wb"

        self._notify_progress(task)

        try:
            with open(task.filepath, mode) as handle:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if not chunk:
                        continue
                    # 检查暂停 — wait() 在 event 为 clear 时阻塞
                    task._pause_event.wait()
                    self._raise_if_cancelled(task)

                    # 限速：先全局后单任务（同时生效，取更严格约束）
                    self._throttle(task, len(chunk), task_limiter)

                    # 限速/暂停等待期间可能已取消，写入前再校验一次
                    task._pause_event.wait()
                    self._raise_if_cancelled(task)

                    handle.write(chunk)
                    task.downloaded += len(chunk)
                    self._update_speed(task, len(chunk))
                    self._notify_progress(task)
        except requests.RequestException:
            # requests.RequestException 同时继承 IOError，必须先放行给重试逻辑
            raise
        except OSError as exc:
            raise OSError(f"写入失败 {task.filepath}: {exc}") from exc

    @staticmethod
    def _resolve_download_range(
        response: requests.Response, resume_offset: int
    ) -> tuple[bool, int, int]:
        """解析响应，决定是否续传以及起始偏移与总大小。

        Returns:
            ``(resumed, start_offset, total_size)``。

        服务端忽略 ``Range`` 返回 200 时 ``resumed=False``，调用方必须以
        ``wb`` 重新写入，否则会把完整响应追加到旧文件、造成内容损坏。
        """
        content_length = DownloadQueue._header_int(
            response.headers.get("content-length")
        )

        if resume_offset > 0 and response.status_code == 206:
            start, total = DownloadQueue._parse_content_range(
                response.headers.get("content-range")
            )
            if start is not None and start == resume_offset:
                if total is None:
                    total = start + content_length if content_length else 0
                return True, start, max(start, total)
            log.warning(
                "Content-Range 与本地偏移不一致（start=%s, local=%s），从头下载",
                start, resume_offset,
            )
            return False, 0, total or content_length

        total = content_length
        if total == 0:
            total = DownloadQueue._parse_content_range(
                response.headers.get("content-range")
            )[1] or 0
        return False, 0, total

    @staticmethod
    def _parse_content_range(value: Optional[str]) -> tuple[Optional[int], int]:
        """解析 ``Content-Range: bytes 0-99/1000``；无法解析返回 ``(None, 0)``。"""
        if not value:
            return None, 0
        match = _CONTENT_RANGE_RE.match(str(value).strip())
        if not match:
            return None, 0
        try:
            start = int(match.group(1))
            total = 0 if match.group(3) == "*" else int(match.group(3))
        except (TypeError, ValueError):
            return None, 0
        if start < 0 or total < 0 or (total and total < start):
            return None, 0
        return start, total

    @staticmethod
    def _header_int(value: Optional[str]) -> int:
        """安全解析非负整数响应头；非法值返回 0。"""
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError):
            return 0
        return max(0, parsed)

    def _throttle(self, task: DownloadTask, size: int,
                  task_limiter: Optional[RateLimiter]) -> None:
        """对单次读取应用全局 + 单任务限速；取消时抛出控制异常。"""
        if self.global_limiter is not None:
            if not self.global_limiter.consume(size, task._cancel_event):
                raise _DownloadCancelled
        limit = self.per_task_limit
        if limit > 0:
            limiter = task_limiter if task_limiter is not None else RateLimiter(limit)
            limiter.set_rate(limit)
            if not limiter.consume(size, task._cancel_event):
                raise _DownloadCancelled

    @staticmethod
    def _raise_if_cancelled(task: DownloadTask) -> None:
        """取消事件置位时抛出控制异常。"""
        if task._cancel_event.is_set():
            raise _DownloadCancelled

    @staticmethod
    def _update_speed(task: DownloadTask, chunk_size: int) -> None:
        """按 EWMA 更新实时速度（字节/秒）。"""
        now = time.monotonic()
        if task._speed_ts > 0:
            elapsed = now - task._speed_ts
            if elapsed > 0:
                instant = chunk_size / elapsed
                task.speed_bps = (
                    instant if task.speed_bps <= 0
                    else task.speed_bps * 0.6 + instant * 0.4
                )
        task._speed_ts = now

    @staticmethod
    def _file_size(path: str) -> int:
        """返回文件字节数；不存在或不可读时返回 0。"""
        try:
            return os.path.getsize(path)
        except OSError:
            return 0

    def _finish_completed(self, task: DownloadTask) -> None:
        """完成任务：校验输出非空 → 后处理 → 通知。"""
        task.speed_bps = 0.0
        if task.downloaded <= 0 or self._file_size(task.filepath) <= 0:
            self._finish_failed(task, "下载内容为空")
            return

        if self.post_options is not None:
            self._run_post_process(task)

        task.status = TaskStatus.COMPLETED
        task.remark = ""
        self._notify_status(task)
        log.info("下载完成: %s → %s", task.display_name, task.filepath)

    def _finish_failed(self, task: DownloadTask, message: str) -> None:
        """标记任务失败并通知 UI。"""
        task.error = message or "下载失败"
        task.status = TaskStatus.FAILED
        task.speed_bps = 0.0
        self._notify_status(task)
        log.warning("下载失败: %s (%s)", task.display_name, task.error)

    def _finish_cancelled(self, task: DownloadTask) -> None:
        """标记任务已取消并通知 UI。"""
        task.status = TaskStatus.CANCELLED
        task.speed_bps = 0.0
        self._notify_status(task)

    def _run_post_process(self, task: DownloadTask) -> None:
        """执行下载后处理管线（转码/歌词/标签），内部吞掉所有异常。"""
        try:
            # 局部导入：避免下载器在模块加载阶段拖入媒体/网络后处理依赖
            from api import fetch_lyrics  # pylint: disable=import-outside-toplevel
            from media import post_process  # pylint: disable=import-outside-toplevel
            post_process(
                task, self.post_options,
                lyrics_fetcher=fetch_lyrics,
                notify=self._notify_progress,
            )
        except Exception:  # noqa: BLE001  后处理失败不影响已下载文件
            log.exception("后处理异常: %s", task.display_name)

    def _notify_progress(self, task: DownloadTask) -> None:
        callback = cast(Optional[ProgressCallback], self.on_progress)
        if callback is None:
            return
        try:
            callback(task)  # pylint: disable=not-callable
        except Exception:  # noqa: BLE001  UI 回调异常不得中断下载
            log.debug("进度回调异常", exc_info=True)

    def _notify_status(self, task: DownloadTask) -> None:
        callback = cast(Optional[ProgressCallback], self.on_status_change)
        if callback is None:
            return
        try:
            callback(task)  # pylint: disable=not-callable
        except Exception:  # noqa: BLE001  UI 回调异常不得中断下载
            log.debug("状态回调异常", exc_info=True)

    @staticmethod
    def _unique_filepath(filepath: str) -> str:
        """生成不冲突的新路径：``artist - title (1).ext``。"""
        base, ext = os.path.splitext(filepath)
        index = 1
        while os.path.exists(f"{base} ({index}){ext}"):
            index += 1
        return f"{base} ({index}){ext}"
