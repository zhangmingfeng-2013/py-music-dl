#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""应用配置与本地记录持久化。

包含
    * 界面 / 下载偏好（``settings.json``）的读取、校验与原子写入；
    * 搜索关键词、歌手历史（JSON 列表）；
    * 开发者打赏记录（仅本地，原子写入，损坏时备份重置）。

本模块不依赖任何 GUI 框架，CLI、Tkinter 版与 PyQt 版共用同一套
持久化语义。所有读取失败都会回退默认值，绝不让损坏的配置文件
阻塞程序启动。
"""

from __future__ import annotations

import os
import time
from typing import Any, Final, Optional

from naming import DEFAULT_TEMPLATE, validate_template
from theme import SCHEMES
from utils import (
    load_json,
    log,
    resource_path,
    save_json_atomic,
    user_config_path,
)

# ---------------------------------------------------------------------------
# 文件路径
# ---------------------------------------------------------------------------

SETTINGS_FILE: Final = user_config_path("settings.json")
SEARCH_HISTORY_FILE: Final = user_config_path("search_history.json")
ARTIST_HISTORY_FILE: Final = user_config_path("artist_history.json")
TIP_RECORDS_FILE: Final = user_config_path("tip_records.json")

# ---------------------------------------------------------------------------
# 默认配置
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS: Final[dict[str, Any]] = {
    "scheme": "liquid",
    "theme_mode": "auto",
    # 下载目录（空串表示使用平台默认目录）
    "download_dir": "",
    # 下载限速（KB/s，0 = 不限速）
    "per_task_speed": 0,
    "global_speed": 0,
    # 下载后处理
    "convert_mode": "off",   # off / mp3 / flac
    "mp3_bitrate": 320,      # 128 / 192 / 320
    "write_tags": True,      # 写入标题/歌手/专辑/年份
    "embed_cover": True,     # 内嵌专辑封面
    "save_lrc": True,        # 同名 .lrc 文件
    "embed_lyrics": True,    # 歌词内嵌到音频标签
    "whisper_fallback": True,  # API 歌词缺失时 Whisper 语音识别兜底
    # 自定义文件命名模板（占位符规则见 naming.py）
    "naming_template": DEFAULT_TEMPLATE,
}

_BOOL_SETTINGS: Final = (
    "write_tags", "embed_cover", "save_lrc", "embed_lyrics", "whisper_fallback",
)
_SPEED_SETTINGS: Final = ("per_task_speed", "global_speed")
_CONVERT_MODES: Final = ("off", "mp3", "flac")
_MP3_BITRATES: Final = (128, 192, 320)
_THEME_MODES: Final = ("auto", "light", "dark")

# ---------------------------------------------------------------------------
# 打赏记录
# ---------------------------------------------------------------------------

TIP_METHODS: Final[dict[str, str]] = {"wechat": "微信支付", "alipay": "支付宝"}
TIP_QR_FILES: Final[dict[str, str]] = {
    "wechat": resource_path("assets", "tip", "wechat.png"),
    "alipay": resource_path("assets", "tip", "alipay.png"),
}
TIP_MAX_RECORDS: Final = 500


# ---------------------------------------------------------------------------
# 设置读写
# ---------------------------------------------------------------------------


def _sanitize_settings(saved: dict[str, Any]) -> dict[str, Any]:
    """把磁盘上的配置逐项校验后合并到默认值上。"""
    data = dict(DEFAULT_SETTINGS)

    if saved.get("scheme") in SCHEMES:
        data["scheme"] = saved["scheme"]
    if saved.get("theme_mode") in _THEME_MODES:
        data["theme_mode"] = saved["theme_mode"]

    download_dir = saved.get("download_dir")
    if isinstance(download_dir, str) and download_dir.strip():
        data["download_dir"] = download_dir.strip()

    for key in _SPEED_SETTINGS:
        try:
            data[key] = max(0, int(saved.get(key, 0)))
        except (TypeError, ValueError):
            pass

    if saved.get("convert_mode") in _CONVERT_MODES:
        data["convert_mode"] = saved["convert_mode"]
    try:
        bitrate = int(saved.get("mp3_bitrate", 320))
        if bitrate in _MP3_BITRATES:
            data["mp3_bitrate"] = bitrate
    except (TypeError, ValueError):
        pass

    for key in _BOOL_SETTINGS:
        if isinstance(saved.get(key), bool):
            data[key] = saved[key]

    # 命名模板：字符串且校验通过才采用，否则保留默认
    template = saved.get("naming_template")
    if isinstance(template, str):
        ok, _error, _used = validate_template(template)
        if ok:
            data["naming_template"] = template
    return data


def load_settings(path: Optional[str] = None) -> dict[str, Any]:
    """读取界面偏好；文件缺失或损坏时返回默认值。"""
    settings_path = path or SETTINGS_FILE
    saved = load_json(settings_path, {})
    if not isinstance(saved, dict):
        return dict(DEFAULT_SETTINGS)
    return _sanitize_settings(saved)


def save_settings(data: dict[str, Any], path: Optional[str] = None) -> None:
    """合并写入设置：保留文件中已有的其他键，原子替换。"""
    settings_path = path or SETTINGS_FILE
    merged: dict[str, Any] = {}
    old = load_json(settings_path, {})
    if isinstance(old, dict):
        merged.update(old)
    if isinstance(data, dict):
        merged.update(data)
    if not save_json_atomic(settings_path, merged):
        log.warning("设置保存失败: %s", settings_path)


def ensure_config_files() -> None:
    """启动时创建缺失的 JSON 配置文件（已存在则不覆盖，失败静默跳过）。"""
    targets = (
        (SETTINGS_FILE, DEFAULT_SETTINGS),
        (SEARCH_HISTORY_FILE, []),
        (ARTIST_HISTORY_FILE, []),
        (TIP_RECORDS_FILE, []),
    )
    for path, payload in targets:
        if os.path.exists(path):
            continue
        save_json_atomic(path, payload)


# ---------------------------------------------------------------------------
# 历史记录
# ---------------------------------------------------------------------------


class JsonHistoryStore:
    """字符串历史列表的通用持久化实现（最近使用优先）。"""

    def __init__(self, history_file: Optional[str] = None,
                 max_items: int = 20) -> None:
        self.history_file = history_file or self.default_history_file()
        self.max_items = max(0, int(max_items))
        self.history: list[str] = self._load_history()

    @staticmethod
    def default_history_file() -> str:
        """子类返回默认文件路径。"""
        raise NotImplementedError

    def _load_history(self) -> list[str]:
        """读取并过滤历史文件：仅保留非空字符串，并遵守条数上限。"""
        data = load_json(self.history_file, [])
        if not isinstance(data, list):
            return []
        cleaned = [
            item for item in data
            if isinstance(item, str) and item.strip()
        ]
        return cleaned[:self.max_items] if self.max_items else []

    def _save_history(self) -> None:
        """原子写入历史文件，失败只记录日志。"""
        if not save_json_atomic(self.history_file, self.history):
            log.warning("历史记录保存失败: %s", self.history_file)

    def add(self, value: str) -> None:
        """把条目插到最前（已存在则先移除），并裁剪到上限。"""
        if not isinstance(value, str):
            return
        item = value.strip()
        if not item:
            return
        if item in self.history:
            self.history.remove(item)
        self.history.insert(0, item)
        if self.max_items:
            self.history = self.history[:self.max_items]
        self._save_history()

    def get_all(self) -> list[str]:
        """返回历史副本，避免调用方修改内部状态。"""
        return self.history.copy()

    def clear(self) -> None:
        """清空历史并落盘。"""
        self.history = []
        self._save_history()


class SearchHistory(JsonHistoryStore):
    """搜索关键词历史（沿用基类默认：保留 20 条）。"""

    @staticmethod
    def default_history_file() -> str:
        return SEARCH_HISTORY_FILE


class ArtistHistory(JsonHistoryStore):
    """歌手筛选历史（默认保留 50 条）。"""

    def __init__(self, history_file: Optional[str] = None,
                 max_items: int = 50) -> None:
        super().__init__(history_file, max_items)

    @staticmethod
    def default_history_file() -> str:
        return ARTIST_HISTORY_FILE


# ---------------------------------------------------------------------------
# 打赏记录
# ---------------------------------------------------------------------------


class TipRecordStore:
    """打赏登记记录：仅本地 JSON，原子写入；文件损坏时备份后重置。

    安全说明：个人收款码无法做服务端验单，记录完全来自用户在界面上的
    确认操作，程序不发起任何网络支付请求。打赏金额由用户在手机端自行
    输入，本地不记录金额。
    """

    VALID_STATUS = ("success", "failed")

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or TIP_RECORDS_FILE
        self.records: list[dict[str, Any]] = self._load()

    def _load(self) -> list[dict[str, Any]]:
        if not os.path.exists(self.path):
            return []
        data = load_json(self.path, None)
        if isinstance(data, list):
            return self._sanitize(data)
        # 损坏文件不删除，备份留证后从空开始
        self._backup_corrupt()
        return []

    def _sanitize(self, data: list[Any]) -> list[dict[str, Any]]:
        """仅保留结构合法的记录，并统一为四个必要字段。"""
        clean: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            record_id = str(item.get("id", ""))
            timestamp = item.get("ts")
            method = item.get("method")
            status = item.get("status")
            if (
                not record_id
                or not isinstance(timestamp, (int, float))
                or method not in TIP_METHODS
                or status not in self.VALID_STATUS
            ):
                continue
            clean.append({
                "id": record_id,
                "ts": int(timestamp),
                "method": method,
                "status": status,
            })
        return clean[:TIP_MAX_RECORDS]

    def _backup_corrupt(self) -> None:
        """把损坏文件重命名为 ``.bak``，保留现场。"""
        try:
            os.replace(self.path, self.path + ".bak")
        except OSError:
            pass

    def _save(self) -> bool:
        """原子写入记录文件。"""
        return save_json_atomic(self.path, self.records)

    def add(self, method: str, status: str) -> Optional[dict[str, Any]]:
        """新增一条记录；非法参数返回 ``None``。"""
        if method not in TIP_METHODS or status not in self.VALID_STATUS:
            return None
        record = {
            "id": f"tip-{int(time.time() * 1000)}-{len(self.records)}",
            "ts": int(time.time()),
            "method": method,
            "status": status,
        }
        self.records.insert(0, record)
        if len(self.records) > TIP_MAX_RECORDS:
            self.records = self.records[:TIP_MAX_RECORDS]
        self._save()
        return record

    def clear(self) -> None:
        """清空记录并落盘。"""
        self.records = []
        self._save()

    def summary(self) -> tuple[int, int]:
        """返回（成功笔数, 未完成笔数）。"""
        succeeded = sum(1 for record in self.records if record["status"] == "success")
        return succeeded, len(self.records) - succeeded
