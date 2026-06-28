#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
音乐下载器 CLI — 多平台并发搜索 + 多选批量下载
"""

from __future__ import annotations

import sys
import signal
import threading
from typing import Any

from api import search_all_platforms, prefetch_quality, get_song_detail
from downloader import DownloadQueue, DownloadTask
from utils import (
    log, ensure_download_dir, format_size,
    format_progress_bar, DEFAULT_DOWNLOAD_DIR,
)


def _print_line(char: str = "═", width: int = 90) -> None:
    print(char * width)


def _display_table(songs: list[dict[str, Any]]) -> None:
    """以表格展示搜索结果"""
    if not songs:
        print("[!] 没有找到歌曲")
        return

    print()
    _print_line()
    print(f"{'序号':<6}{'歌曲名':<34}{'歌手':<22}{'来源':<14}{'音质':>8}")
    _print_line()

    for i, s in enumerate(songs, 1):
        name = s.get("title", "") or s.get("name", "")
        artist = s.get("artist", "") or s.get("singer", "")
        src = s.get("source_name", s.get("source", "?"))
        quality = s.get("quality", "?")

        name = name[:32] + ".." if len(name) > 34 else name
        artist = artist[:20] + ".." if len(artist) > 22 else artist

        print(f"{i:<6}{name:<34}{artist:<22}{src:<14}{quality:>8}")

    _print_line()


def _multi_select(max_num: int) -> list[int]:
    """多选输入。支持 1,3,5-8 或 all"""
    while True:
        try:
            inp = input(
                f"\n请输入要下载的歌曲序号，多选用逗号分隔（如 1,3,5-8），"
                f"输入 all 全选，输入 0 退出："
            ).strip()
            if inp == "0":
                return []
            if inp.lower() == "all":
                return list(range(1, max_num + 1))
            selected: set[int] = set()
            for part in inp.split(","):
                part = part.strip()
                if "-" in part:
                    a, b = part.split("-", 1)
                    a, b = int(a.strip()), int(b.strip())
                    if a > b:
                        a, b = b, a
                    selected.update(range(a, b + 1))
                else:
                    selected.add(int(part))
            result = sorted(selected)
            if all(1 <= n <= max_num for n in result):
                return result
            print(f"[!] 序号需在 1 ~ {max_num} 之间")
        except ValueError:
            print("[!] 输入格式错误，示例：1,3,5-8 或 all")
        except KeyboardInterrupt:
            print()
            return []


def _print_progress(task: DownloadTask) -> None:
    """单任务进度回调"""
    bar = format_progress_bar(task.downloaded, task.total_size)
    status_icon = {
        "completed": "✓", "failed": "✗", "cancelled": "✕",
    }.get(task.status.value, "↓")
    line = f"  [{status_icon}] {task.display_name:<44} {bar}"
    # 使用 \r 覆盖当前行
    sys.stdout.write(f"\r{line}\033[K")
    if task.status.value in ("completed", "failed", "cancelled"):
        sys.stdout.write("\n")
    sys.stdout.flush()


def main() -> None:
    """CLI 主入口"""
    # 处理 Ctrl+C 优雅退出
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))

    print("═" * 52)
    print("           🎵  音乐下载器 v2.0  🎵")
    print("                多平台聚合")
    print("     支持：咪咕 | 网易云 | QQ音乐 | 酷我")
    print("═" * 52)
    print("  新特性：并发搜索 · 批量下载 · 断点续传")
    print("═" * 52)

    # 下载目录
    directory = input(
        f"\n下载目录（回车默认 {DEFAULT_DOWNLOAD_DIR}/）："
    ).strip()
    directory = ensure_download_dir(directory or DEFAULT_DOWNLOAD_DIR)
    print(f"[✓] 下载目录: {directory}")

    # 搜索
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

    # 多选
    indices = _multi_select(len(songs))
    if not indices:
        print("[*] 退出")
        return

    selected = [songs[i - 1] for i in indices]
    print(f"\n[*] 已选择 {len(selected)} 首歌曲，开始获取下载链接...")

    # 创建下载队列
    queue = DownloadQueue(directory=directory)

    # 进度回调
    _lock = threading.Lock()
    current_task: DownloadTask | None = None

    def on_progress(task: DownloadTask) -> None:
        nonlocal current_task
        with _lock:
            if current_task and current_task.task_id != task.task_id:
                sys.stdout.write("\n")
            current_task = task
            _print_progress(task)

    def on_status(task: DownloadTask) -> None:
        nonlocal current_task
        with _lock:
            if current_task is None or current_task.task_id != task.task_id:
                if current_task:
                    sys.stdout.write("\n")
                current_task = task
            status_text = {
                "fetching": "  [→] 获取链接中...",
                "downloading": "",
                "completed": "",
                "failed": f"  [✗] 失败: {task.error}" if task.error else "  [✗] 下载失败",
                "cancelled": "  [✕] 已取消",
            }
            msg = status_text.get(task.status.value, "")
            if msg:
                sys.stdout.write(f"\n{msg}\n")
                sys.stdout.flush()

    queue.on_progress = on_progress
    queue.on_status_change = on_status

    # 获取详情并加入队列
    detail_err_count = 0
    for song in selected:
        detail = get_song_detail(song)
        if detail and detail.get("audio_url"):
            queue.add_task(
                title=detail.get("title", song.get("title", "")),
                artist=detail.get("artist", song.get("artist", "")),
                audio_url=detail["audio_url"],
                quality=detail.get("quality", "?"),
                source=song.get("source_name", ""),
            )
        else:
            detail_err_count += 1
            title = song.get("title", "?")
            artist = song.get("artist", "?")
            print(f"  [✗] 无法获取链接：{artist} - {title}")

    if not queue.tasks:
        print("[✗] 没有可下载的歌曲")
        return

    if detail_err_count:
        print(f"\n[*] {detail_err_count} 首获取链接失败，跳过")

    print(f"\n[*] 开始下载 {len(queue.tasks)} 首...")
    print()

    queue.start()

    # 总结
    completed = sum(1 for t in queue.tasks if t.status.value == "completed")
    failed = sum(1 for t in queue.tasks if t.status.value == "failed")
    print(f"\n{'═' * 52}")
    print(f"  下载完成：{completed} 成功, {failed} 失败")
    print(f"  文件保存在: {directory}/")
    print(f"{'═' * 52}")


if __name__ == "__main__":
    main()
