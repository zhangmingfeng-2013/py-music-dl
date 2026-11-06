#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""downloader.py 单元 / 集成测试。

使用本地 ``ThreadingHTTPServer`` 验证真实 HTTP 行为（Range、200 回退、
断线重试），并通过直接调用 ``_process_task`` 避免 20 秒空闲等待。
"""

import http.server
import os
import sys
import threading
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import downloader  # noqa: E402
from downloader import DownloadQueue, DownloadTask, RateLimiter, TaskStatus  # noqa: E402

PAYLOAD = bytes(range(256)) * 40  # 10240 字节


class _Handler(http.server.BaseHTTPRequestHandler):
    """可配置的测试服务端。"""

    protocol_version = "HTTP/1.1"
    payload = PAYLOAD
    ignore_range = False
    drop_first = False
    empty = False
    slow = False
    request_count = 0
    range_headers: list[str | None] = []
    lock = threading.Lock()

    def log_message(self, *args):  # noqa: D401, ANN002
        """静默 HTTP 日志。"""

    def _record(self):
        with type(self).lock:
            type(self).request_count += 1
            type(self).range_headers.append(self.headers.get("Range"))
            return type(self).request_count

    def do_GET(self):  # noqa: N802  BaseHTTPRequestHandler 约定
        sequence = self._record()
        if self.path.startswith("/missing"):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        payload = b"" if self.empty else self.payload
        range_header = self.headers.get("Range")
        if range_header and not self.ignore_range:
            start = int(range_header.split("=", 1)[1].split("-", 1)[0])
            body = payload[start:]
            self.send_response(206)
            self.send_header(
                "Content-Range", f"bytes {start}-{len(payload) - 1}/{len(payload)}"
            )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()

        if self.drop_first and sequence == 1:
            # 发送一个完整 chunk 后断开，确保客户端已写入部分文件
            self.wfile.write(payload[:8192])
            self.wfile.flush()
            self.close_connection = True
            return

        if self.slow:
            for offset in range(0, len(payload), 2048):
                self.wfile.write(payload[offset:offset + 2048])
                self.wfile.flush()
                time.sleep(0.05)
            return

        self.wfile.write(payload)


@pytest.fixture
def server():
    """启动本地 HTTP 服务并返回 (handler 类, URL)。"""
    handler = type("Handler", (_Handler,), {
        "payload": PAYLOAD,
        "ignore_range": False,
        "drop_first": False,
        "empty": False,
        "slow": False,
        "request_count": 0,
        "range_headers": [],
        "lock": threading.Lock(),
    })
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield handler, f"http://127.0.0.1:{httpd.server_port}/audio.mp3"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _new_queue(tmp_path, **kwargs):
    kwargs.setdefault("max_retries", 0)
    return DownloadQueue(str(tmp_path), **kwargs)


def _add_task(queue, url):
    return queue.add_task(
        title="晴天", artist="周杰伦", audio_url=url,
        quality="320K", source="qq",
    )


class TestRateLimiter:
    def test_unlimited_is_immediate(self):
        limiter = RateLimiter(0)
        started = time.monotonic()
        assert limiter.consume(10 * 1024 * 1024)
        assert time.monotonic() - started < 0.2

    def test_request_larger_than_bucket_terminates(self):
        """回归：chunk > 桶容量时旧实现会永远等待。"""
        limiter = RateLimiter(1000)
        started = time.monotonic()
        assert limiter.consume(1500)
        elapsed = time.monotonic() - started
        assert 0.3 <= elapsed < 3.0

    def test_cancel_during_wait(self):
        limiter = RateLimiter(1000)
        event = threading.Event()
        event.set()
        assert limiter.consume(5000, event) is False

    def test_set_rate_zero(self):
        limiter = RateLimiter(1000)
        limiter.set_rate(0)
        assert limiter.rate_bps == 0
        assert limiter.consume(10 ** 6)


class TestTaskState:
    def test_progress_clamped(self):
        task = DownloadTask(task_id="x", title="t", artist="a",
                            total_size=100, downloaded=150)
        assert task.progress_pct == 100.0
        task.downloaded = -5
        assert task.progress_pct == 0.0
        task.total_size = 0
        assert task.progress_pct == 0.0

    def test_pause_resume_and_cancel(self, tmp_path):
        queue = _new_queue(tmp_path)
        task = _add_task(queue, "https://x/a.mp3")
        task.status = TaskStatus.DOWNLOADING
        task.pause()
        assert task.status is TaskStatus.PAUSED
        task.resume_after_pause()
        assert task.status is TaskStatus.DOWNLOADING
        task.cancel()
        assert task.status is TaskStatus.CANCELLED
        # 已终态不再改变
        task.cancel()
        assert task.status is TaskStatus.CANCELLED
        # 未暂停时 resume 是空操作
        task.status = TaskStatus.DOWNLOADING
        task.resume_after_pause()
        assert task.status is TaskStatus.DOWNLOADING

    def test_status_helpers(self):
        assert TaskStatus.DOWNLOADING.is_running
        assert not TaskStatus.PENDING.is_running
        assert TaskStatus.COMPLETED.is_terminal
        assert not TaskStatus.PAUSED.is_terminal
        assert TaskStatus.PENDING.is_pending


class TestQueueManagement:
    def test_add_task_filename_and_meta_not_mutated(self, tmp_path):
        queue = _new_queue(tmp_path)
        meta = {"album": "叶惠美"}
        task = queue.add_task(
            title="晴天", artist="周杰伦", audio_url="https://x/a.flac",
            quality="无损", source="qq", meta=meta, name_template="{artist} - {title}",
        )
        assert os.path.basename(task.filepath) == "周杰伦 - 晴天.flac"
        assert task.meta == {"album": "叶惠美"}
        assert meta == {"album": "叶惠美"}
        assert task.status is TaskStatus.PENDING

    def test_invalid_template_fallback(self, tmp_path):
        queue = _new_queue(tmp_path)
        task = queue.add_task(
            title="晴天", artist="周杰伦", audio_url="https://x/a.mp3",
            name_template="{title}/{singer}",
        )
        assert os.path.basename(task.filepath) == "周杰伦 - 晴天.mp3"

    def test_remove_task(self, tmp_path):
        queue = _new_queue(tmp_path)
        pending = _add_task(queue, "https://x/a.mp3")
        assert queue.remove_task(pending.task_id) is True
        assert queue.remove_task(pending.task_id) is False

        active = _add_task(queue, "https://x/a.mp3")
        active.status = TaskStatus.DOWNLOADING
        assert queue.remove_task(active.task_id) is False

    def test_clear_completed_keeps_pending(self, tmp_path):
        queue = _new_queue(tmp_path)
        pending = _add_task(queue, "https://x/a.mp3")
        done = _add_task(queue, "https://x/b.mp3")
        done.status = TaskStatus.COMPLETED
        assert queue.clear_completed() == 1
        assert queue.tasks == [pending]

    def test_clear_completed_keeps_paused_and_reindexes(self, tmp_path):
        queue = _new_queue(tmp_path)
        first = _add_task(queue, "https://x/a.mp3")
        second = _add_task(queue, "https://x/b.mp3")
        second.status = TaskStatus.PAUSED
        queue._current_idx = 1  # 模拟正在处理 second（测试内部索引）
        assert queue.clear_completed() == 0
        assert queue.current_task is second
        assert first.status is TaskStatus.PENDING

    def test_start_async_is_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(downloader, "IDLE_TIMEOUT", 0.05)
        monkeypatch.setattr(downloader, "WAKE_INTERVAL", 0.01)
        queue = _new_queue(tmp_path)
        task = _add_task(queue, "http://127.0.0.1:1/audio.mp3")
        task.cancel()
        first = queue.start_async()
        second = queue.start_async()
        assert first is second
        first.join(timeout=2)
        assert not first.is_alive()

    def test_set_limits(self, tmp_path):
        queue = _new_queue(tmp_path)
        queue.set_limits(1024, 2048)
        assert queue.per_task_limit == 1024
        assert queue.global_limiter is not None
        assert queue.global_limiter.rate_bps == 2048
        queue.set_limits(0, 0)
        assert queue.global_limiter.rate_bps == 0



    def test_blocking_start_processes_queue(self, tmp_path, server, monkeypatch):
        """端到端：start() 阻塞消费队列并在空闲超时后退出。"""
        monkeypatch.setattr(downloader, "IDLE_TIMEOUT", 0.1)
        monkeypatch.setattr(downloader, "WAKE_INTERVAL", 0.01)
        _, url = server
        queue = _new_queue(tmp_path)
        task = _add_task(queue, url)
        queue.start()
        assert task.status is TaskStatus.COMPLETED
        with open(task.filepath, "rb") as handle:
            assert handle.read() == PAYLOAD
        assert not queue.is_running

class TestDownloadFlow:
    def test_success(self, tmp_path, server):
        _, url = server
        queue = _new_queue(tmp_path)
        task = _add_task(queue, url)
        queue._process_task(task)
        assert task.status is TaskStatus.COMPLETED
        assert task.downloaded == len(PAYLOAD)
        assert task.total_size == len(PAYLOAD)
        assert task.error == ""
        with open(task.filepath, "rb") as handle:
            assert handle.read() == PAYLOAD

    def test_http_error_fails_without_retry(self, tmp_path, server):
        _, url = server
        queue = _new_queue(tmp_path, max_retries=0)
        task = _add_task(queue, url.replace("/audio.mp3", "/missing"))
        queue._process_task(task)
        assert task.status is TaskStatus.FAILED
        assert task.error
        assert not os.path.exists(task.filepath)

    def test_existing_file_without_callback_is_skipped(self, tmp_path, server):
        handler, url = server
        queue = _new_queue(tmp_path)
        task = _add_task(queue, url)
        os.makedirs(os.path.dirname(task.filepath), exist_ok=True)
        with open(task.filepath, "wb") as handle:
            handle.write(b"old")
        queue._process_task(task)
        assert task.status is TaskStatus.CANCELLED
        assert "已存在同名文件" in task.error
        assert handler.request_count == 0
        with open(task.filepath, "rb") as handle:
            assert handle.read() == b"old"

    def test_existing_file_rename(self, tmp_path, server):
        _, url = server
        queue = _new_queue(tmp_path)
        queue.on_file_exists = lambda task: "rename"
        task = _add_task(queue, url)
        with open(task.filepath, "wb") as handle:
            handle.write(b"old")
        queue._process_task(task)
        assert task.status is TaskStatus.COMPLETED
        assert task.filepath.endswith(" (1).mp3")
        with open(task.filepath, "rb") as handle:
            assert handle.read() == PAYLOAD

    def test_existing_file_overwrite(self, tmp_path, server):
        _, url = server
        queue = _new_queue(tmp_path)
        queue.on_file_exists = lambda task: "overwrite"
        task = _add_task(queue, url)
        with open(task.filepath, "wb") as handle:
            handle.write(b"old")
        queue._process_task(task)
        assert task.status is TaskStatus.COMPLETED
        with open(task.filepath, "rb") as handle:
            assert handle.read() == PAYLOAD

    def test_existing_file_callback_skip(self, tmp_path, server):
        _, url = server
        queue = _new_queue(tmp_path)
        queue.on_file_exists = lambda task: "skip"
        task = _add_task(queue, url)
        with open(task.filepath, "wb") as handle:
            handle.write(b"old")
        queue._process_task(task)
        assert task.status is TaskStatus.CANCELLED
        assert "用户取消" in task.error

    def test_empty_response_fails(self, tmp_path, server):
        handler, url = server
        handler.empty = True
        queue = _new_queue(tmp_path)
        task = _add_task(queue, url)
        queue._process_task(task)
        assert task.status is TaskStatus.FAILED
        assert "下载内容为空" in task.error

    def test_cancel_before_start(self, tmp_path, server):
        handler, url = server
        queue = _new_queue(tmp_path)
        task = _add_task(queue, url)
        task.cancel()
        queue._process_task(task)
        assert task.status is TaskStatus.CANCELLED
        assert handler.request_count == 0


class TestResume:
    def test_content_range_parsing(self):
        assert DownloadQueue._parse_content_range("bytes 100-199/500") == (100, 500)
        assert DownloadQueue._parse_content_range("bytes 0-99/*") == (0, 0)
        assert DownloadQueue._parse_content_range("garbage") == (None, 0)
        assert DownloadQueue._parse_content_range("bytes 500-99/100") == (None, 0)
        assert DownloadQueue._parse_content_range(None) == (None, 0)

    def test_header_int(self):
        assert DownloadQueue._header_int("123") == 123
        assert DownloadQueue._header_int("-1") == 0
        assert DownloadQueue._header_int("abc") == 0
        assert DownloadQueue._header_int(None) == 0

    def test_resolve_range_honours_206(self):
        response = SimpleNamespace(
            status_code=206,
            headers={
                "content-range": "bytes 100-199/200",
                "content-length": "100",
            },
        )
        assert DownloadQueue._resolve_download_range(response, 100) == (True, 100, 200)

    def test_resolve_range_mismatch_restarts(self):
        response = SimpleNamespace(
            status_code=206,
            headers={
                "content-range": "bytes 50-149/200",
                "content-length": "100",
            },
        )
        assert DownloadQueue._resolve_download_range(response, 100) == (False, 0, 200)

    def test_resolve_range_server_ignores_range(self):
        response = SimpleNamespace(
            status_code=200,
            headers={"content-length": "200"},
        )
        assert DownloadQueue._resolve_download_range(response, 100) == (False, 0, 200)

    def test_retry_after_connection_drop(self, tmp_path, server):
        handler, url = server
        handler.drop_first = True
        queue = _new_queue(tmp_path, max_retries=1)
        task = _add_task(queue, url)
        queue._process_task(task)
        assert task.status is TaskStatus.COMPLETED
        with open(task.filepath, "rb") as handle:
            assert handle.read() == PAYLOAD
        assert handler.request_count == 2
        assert handler.range_headers[1] == "bytes=8192-"

    def test_server_ignoring_range_does_not_duplicate(self, tmp_path, server):
        handler, url = server
        handler.drop_first = True
        handler.ignore_range = True
        queue = _new_queue(tmp_path, max_retries=1)
        task = _add_task(queue, url)
        queue._process_task(task)
        assert task.status is TaskStatus.COMPLETED
        with open(task.filepath, "rb") as handle:
            content = handle.read()
        assert content == PAYLOAD
        assert len(content) == len(PAYLOAD)

    def test_cancel_while_downloading(self, tmp_path, server):
        handler, url = server
        handler.slow = True
        queue = _new_queue(tmp_path, max_retries=0)
        task = _add_task(queue, url)

        def cancel_on_progress(changed):
            if changed.task_id == task.task_id and changed.downloaded > 0:
                changed.cancel()

        queue.on_progress = cancel_on_progress
        queue._process_task(task)
        assert task.status is TaskStatus.CANCELLED
        assert task.speed_bps == 0.0


if __name__ == "__main__":
    raise SystemExit("请使用 pytest 运行该测试文件")
