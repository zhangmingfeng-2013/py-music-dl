#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""拾音 CLI：多平台并发搜索 + 多选批量下载。

交互流程
    下载目录 → 搜索关键词 → 四平台并发搜索 → 音质预取 → 结果表格
    → 多选（``1,3,5-8`` / ``all`` / ``0``）→ 解析链接 → 队列下载 → 汇总

设计说明
    * 输入解析与进度输出拆为可独立测试的函数 / 类；
    * 下载队列在后台线程运行，主线程仅消费回调；
    * ``Ctrl+C`` 优雅退出（SIGINT → ``SystemExit``）。
"""

from __future__ import annotations

import signal
import sys
import threading
from typing import Any, Final

from api import get_song_detail, prefetch_quality, search_all_platforms
from downloader import DownloadQueue, DownloadTask, TaskStatus
from utils import DEFAULT_DOWNLOAD_DIR, ensure_download_dir, format_progress_bar

_SEPARATOR: Final = "═" * 52

_BANNER: Final = "\n".join((
    _SEPARATOR,
    "           🎵  拾音 v2.0  🎵",
    "                多平台聚合",
    "     支持：咪咕 | 网易云 | QQ音乐 | 酷我",
    _SEPARATOR,
))


class SelectionRangeError(ValueError):
    """多选序号越界。"""


def _print_line(char: str = "═", width: int = 90) -> None:
    """打印指定字符组成的分隔线。"""
    print(char * width)


# ---------------------------------------------------------------------------
# 结果展示
# ---------------------------------------------------------------------------


def _display_table(songs: list[dict[str, Any]]) -> None:
    """以定宽表格展示搜索结果。"""
    if not songs:
        print("[!] 没有找到歌曲")
        return

    print()
    _print_line()
    print(f"{'序号':<6}{'歌曲名':<34}{'歌手':<22}{'来源':<14}{'音质':>8}")
    _print_line()

    for index, song in enumerate(songs, 1):
        title = str(song.get("title", "") or song.get("name", ""))
        artist = str(song.get("artist", "") or song.get("singer", ""))
        source = str(song.get("source_name", song.get("source", "?")))
        quality = str(song.get("quality", "?"))

        title = title[:32] + ".." if len(title) > 34 else title
        artist = artist[:20] + ".." if len(artist) > 22 else artist
        print(f"{index:<6}{title:<34}{artist:<22}{source:<14}{quality:>8}")

    _print_line()


# ---------------------------------------------------------------------------
# 多选输入
# ---------------------------------------------------------------------------


def parse_selection(raw: str, max_num: int) -> list[int]:
    """解析多选输入。

    支持 ``1,3,5-8``、``all``、``0``（退出）；区间可反序（``8-5``），
    重复序号自动去重并升序返回。

    Raises:
        SelectionRangeError: 序号越界。
        ValueError: 格式非法（非数字、空片段等）。
    """
    text = (raw or "").strip()
    if text == "0":
        return []
    if text.lower() == "all":
        return list(range(1, max_num + 1))

    selected: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            raise ValueError("empty selection segment")
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start, end = int(start_text.strip()), int(end_text.strip())
            if start > end:
                start, end = end, start
            selected.update(range(start, end + 1))
        else:
            selected.add(int(part))

    result = sorted(selected)
    if not all(1 <= number <= max_num for number in result):
        raise SelectionRangeError(f"序号需在 1 ~ {max_num} 之间")
    return result


def _multi_select(max_num: int) -> list[int]:
    """循环读取多选输入，直到得到合法结果或用户退出。"""
    while True:
        try:
            raw = input(
                "\n请输入要下载的歌曲序号，多选用逗号分隔（如 1,3,5-8），"
                "输入 all 全选，输入 0 退出："
            )
            return parse_selection(raw, max_num)
        except SelectionRangeError as exc:
            print(f"[!] {exc}")
        except ValueError:
            print("[!] 输入格式错误，示例：1,3,5-8 或 all")
        except KeyboardInterrupt:
            print()
            return []


# ---------------------------------------------------------------------------
# 下载进度输出
# ---------------------------------------------------------------------------


class _ProgressPrinter:
    """串行化下载线程回调，避免多行进度互相覆盖。"""

    _STATUS_ICONS: Final = {
        TaskStatus.COMPLETED: "✓",
        TaskStatus.FAILED: "✗",
        TaskStatus.CANCELLED: "✕",
    }
    _STATUS_MESSAGES: Final = {
        TaskStatus.FETCHING: "  [→] 获取链接中...",
        TaskStatus.FAILED: "  [✗] 下载失败",
        TaskStatus.CANCELLED: "  [✕] 已取消",
    }

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: DownloadTask | None = None

    def on_progress(self, task: DownloadTask) -> None:
        """单行覆盖式进度条。"""
        with self._lock:
            if self._current is not None and self._current.task_id != task.task_id:
                sys.stdout.write("\n")
            self._current = task
            self._write_progress(task)

    def _write_progress(self, task: DownloadTask) -> None:
        progress = format_progress_bar(task.downloaded, task.total_size)
        icon = self._STATUS_ICONS.get(task.status, "↓")
        line = f"  [{icon}] {task.display_name:<44} {progress}"
        sys.stdout.write(f"\r{line}\033[K")
        if task.status.is_terminal:
            sys.stdout.write("\n")
        sys.stdout.flush()

    def on_status(self, task: DownloadTask) -> None:
        """状态变化提示（获取链接 / 失败 / 取消）。"""
        with self._lock:
            if self._current is None or self._current.task_id != task.task_id:
                if self._current is not None:
                    sys.stdout.write("\n")
                self._current = task

            if task.status is TaskStatus.FAILED and task.error:
                message = f"  [✗] 失败: {task.error}"
            else:
                message = self._STATUS_MESSAGES.get(task.status, "")
            if message:
                sys.stdout.write(f"\n{message}\n")
                sys.stdout.flush()


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def _prompt_download_dir() -> str:
    """询问下载目录并创建。"""
    directory = input(
        f"\n下载目录（回车默认 {DEFAULT_DOWNLOAD_DIR}/）："
    ).strip()
    return ensure_download_dir(directory or DEFAULT_DOWNLOAD_DIR)


def _enqueue_details(queue: DownloadQueue,
                     songs: list[dict[str, Any]]) -> int:
    """逐首解析下载链接并加入队列，返回失败数量。"""
    failed = 0
    for song in songs:
        detail = get_song_detail(song)
        if detail and detail.get("audio_url"):
            queue.add_task(
                title=detail.get("title", song.get("title", "")),
                artist=detail.get("artist", song.get("artist", "")),
                audio_url=detail["audio_url"],
                quality=detail.get("quality", "?"),
                source=song.get("source_name", ""),
            )
            continue

        failed += 1
        print(f"  [✗] 无法获取链接："
              f"{song.get('artist', '?')} - {song.get('title', '?')}")
    return failed


def _print_summary(queue: DownloadQueue, directory: str) -> None:
    """打印下载结果汇总。"""
    tasks = queue.tasks
    completed = sum(1 for task in tasks if task.status is TaskStatus.COMPLETED)
    failed = sum(1 for task in tasks if task.status is TaskStatus.FAILED)
    print(f"\n{'═' * 52}")
    print(f"  下载完成：{completed} 成功, {failed} 失败")
    print(f"  文件保存在: {directory}/")
    print(f"{'═' * 52}")


def main() -> None:
    """CLI 主入口。"""
    # 处理 Ctrl+C：退出码 0，便于脚本静默中断
    try:
        signal.signal(signal.SIGINT, lambda _signum, _frame: sys.exit(0))
    except ValueError:
        # 非主线程调用 main()（如测试）时无法注册信号，忽略即可
        pass

    print(_BANNER)

    directory = _prompt_download_dir()
    print(f"[✓] 下载目录: {directory}")

    keyword = input("\n请输入要搜索的歌曲名：").strip()
    if not keyword:
        print("[!] 歌曲名不能为空")
        return

    songs = search_all_platforms(keyword)
    if not songs:
        print("[!] 未找到相关歌曲")
        return

    prefetch_quality(songs)
    _display_table(songs)

    indices = _multi_select(len(songs))
    if not indices:
        print("[*] 退出")
        return

    selected = [songs[index - 1] for index in indices]
    print(f"\n[*] 已选择 {len(selected)} 首歌曲，开始获取下载链接...")

    queue = DownloadQueue(directory=directory)
    printer = _ProgressPrinter()
    queue.on_progress = printer.on_progress
    queue.on_status_change = printer.on_status

    failed_details = _enqueue_details(queue, selected)
    if not queue.tasks:
        print("[✗] 没有可下载的歌曲")
        return
    if failed_details:
        print(f"\n[*] {failed_details} 首获取链接失败，跳过")

    print(f"\n[*] 开始下载 {len(queue.tasks)} 首...")
    print()
    queue.start()
    _print_summary(queue, directory)


if __name__ == "__main__":
    main()
