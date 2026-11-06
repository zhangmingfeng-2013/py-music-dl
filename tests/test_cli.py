#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""cli.py 测试：多选解析、结果表格、进度输出与入队流程。"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cli  # noqa: E402
from downloader import DownloadQueue, TaskStatus  # noqa: E402


class TestParseSelection:
    @pytest.mark.parametrize("raw,expected", [
        ("1,3,5-8", [1, 3, 5, 6, 7, 8]),
        ("8-5", [5, 6, 7, 8]),
        ("2,2,2", [2]),
        ("all", [1, 2, 3]),
        ("0", []),
        (" 1 , 2 ", [1, 2]),
    ])
    def test_valid(self, raw, expected):
        assert cli.parse_selection(raw, 8 if raw != "all" else 3) == expected

    def test_out_of_range(self):
        with pytest.raises(cli.SelectionRangeError) as info:
            cli.parse_selection("0,1", 3)
        assert "1 ~ 3" in str(info.value)

    @pytest.mark.parametrize("raw", ["", "abc", "1,,2", "1-x", "-"])
    def test_invalid_format(self, raw):
        with pytest.raises(ValueError):
            cli.parse_selection(raw, 10)

    def test_all_with_zero_songs(self):
        assert cli.parse_selection("all", 0) == []


class TestDisplayTable:
    def test_empty(self, capsys):
        cli._display_table([])
        assert "[!] 没有找到歌曲" in capsys.readouterr().out

    def test_rows_and_truncation(self, capsys):
        songs = [{
            "title": "长" * 40,
            "artist": "歌" * 30,
            "source_name": "QQ音乐",
            "quality": "320K",
        }]
        cli._display_table(songs)
        output = capsys.readouterr().out
        assert "QQ音乐" in output
        assert "320K" in output
        assert ".." in output


class TestProgressPrinter:
    def test_progress_and_status(self, tmp_path, capsys):
        queue = DownloadQueue(str(tmp_path))
        task = queue.add_task(
            title="晴天", artist="周杰伦", audio_url="https://x/a.mp3",
        )
        printer = cli._ProgressPrinter()
        task.status = TaskStatus.DOWNLOADING
        task.downloaded = 50
        task.total_size = 100
        printer.on_progress(task)
        output = capsys.readouterr().out
        assert "周杰伦 - 晴天" in output
        assert "50.0%" in output

        task.status = TaskStatus.FAILED
        task.error = "网络错误"
        printer.on_status(task)
        assert "失败: 网络错误" in capsys.readouterr().out

    def test_terminal_status_ends_line(self, tmp_path, capsys):
        queue = DownloadQueue(str(tmp_path))
        task = queue.add_task(
            title="晴天", artist="周杰伦", audio_url="https://x/a.mp3",
        )
        printer = cli._ProgressPrinter()
        task.status = TaskStatus.COMPLETED
        printer.on_progress(task)
        assert capsys.readouterr().out.endswith("\n")


class TestEnqueue:
    def test_enqueue_details(self, tmp_path, monkeypatch):
        queue = DownloadQueue(str(tmp_path))
        songs = [
            {"source_name": "QQ音乐", "title": "晴天", "artist": "周杰伦"},
            {"source_name": "QQ音乐", "title": "夜曲", "artist": "周杰伦"},
        ]

        def fake_detail(song):
            if song["title"] == "晴天":
                return {"title": "晴天", "artist": "周杰伦",
                        "audio_url": "https://x/a.mp3", "quality": "320K"}
            return None

        monkeypatch.setattr(cli, "get_song_detail", fake_detail)
        failed = _enqueue(queue, songs)
        assert failed == 1
        assert len(queue.tasks) == 1
        assert queue.tasks[0].title == "晴天"

    def test_summary(self, tmp_path, capsys):
        queue = DownloadQueue(str(tmp_path))
        first = queue.add_task(
            title="a", artist="b", audio_url="https://x/a.mp3")
        second = queue.add_task(
            title="c", artist="d", audio_url="https://x/b.mp3")
        first.status = TaskStatus.COMPLETED
        second.status = TaskStatus.FAILED
        cli._print_summary(queue, str(tmp_path))
        output = capsys.readouterr().out
        assert "1 成功, 1 失败" in output


def _enqueue(queue, songs):
    """包装私有函数，避免测试函数名被 pytest 收集。"""
    return cli._enqueue_details(queue, songs)


if __name__ == "__main__":
    raise SystemExit("请使用 pytest 运行该测试文件")
