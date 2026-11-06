#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""config.py 测试：设置校验/合并写入、历史记录、打赏记录。"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from config import (  # noqa: E402
    ArtistHistory,
    SearchHistory,
    TipRecordStore,
    ensure_config_files,
    load_settings,
    save_settings,
)


class TestSettings:
    def test_missing_file_returns_defaults(self, tmp_path):
        settings = load_settings(str(tmp_path / "missing.json"))
        assert settings == config.DEFAULT_SETTINGS
        assert settings is not config.DEFAULT_SETTINGS

    def test_corrupt_file_returns_defaults(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text("{broken", encoding="utf-8")
        assert load_settings(str(path)) == config.DEFAULT_SETTINGS

    def test_invalid_values_rejected(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({
            "scheme": "unknown",
            "theme_mode": "neon",
            "per_task_speed": "bad",
            "global_speed": -5,
            "convert_mode": "ogg",
            "mp3_bitrate": 999,
            "write_tags": "yes",
            "naming_template": "{title}/{singer}",
        }), encoding="utf-8")
        settings = load_settings(str(path))
        assert settings["scheme"] == "liquid"
        assert settings["theme_mode"] == "auto"
        assert settings["per_task_speed"] == 0
        assert settings["global_speed"] == 0
        assert settings["convert_mode"] == "off"
        assert settings["mp3_bitrate"] == 320
        assert settings["write_tags"] is True
        assert settings["naming_template"] == config.DEFAULT_SETTINGS["naming_template"]

    def test_valid_values_accepted(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({
            "scheme": "mono",
            "theme_mode": "dark",
            "download_dir": "  /tmp/music  ",
            "per_task_speed": 128,
            "global_speed": 1024,
            "convert_mode": "flac",
            "mp3_bitrate": 192,
            "write_tags": False,
            "embed_cover": False,
            "save_lrc": False,
            "embed_lyrics": False,
            "whisper_fallback": False,
            "naming_template": "{title} - {artist}",
        }), encoding="utf-8")
        settings = load_settings(str(path))
        assert settings["scheme"] == "mono"
        assert settings["theme_mode"] == "dark"
        assert settings["download_dir"] == "/tmp/music"
        assert settings["per_task_speed"] == 128
        assert settings["global_speed"] == 1024
        assert settings["convert_mode"] == "flac"
        assert settings["mp3_bitrate"] == 192
        assert settings["write_tags"] is False
        assert settings["embed_cover"] is False
        assert settings["save_lrc"] is False
        assert settings["embed_lyrics"] is False
        assert settings["whisper_fallback"] is False
        assert settings["naming_template"] == "{title} - {artist}"

    def test_save_merges_existing_keys(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"custom": 1, "scheme": "mono"}),
                        encoding="utf-8")
        save_settings({"theme_mode": "dark"}, str(path))
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data == {"custom": 1, "scheme": "mono", "theme_mode": "dark"}

    def test_save_creates_parent_directory(self, tmp_path):
        path = tmp_path / "a" / "b" / "settings.json"
        save_settings({"scheme": "aurora"}, str(path))
        assert json.loads(path.read_text(encoding="utf-8"))["scheme"] == "aurora"


class TestEnsureConfigFiles:
    def test_creates_missing_and_does_not_overwrite(self, tmp_path, monkeypatch):
        settings = tmp_path / "settings.json"
        search = tmp_path / "search.json"
        artist = tmp_path / "artist.json"
        tips = tmp_path / "tips.json"
        monkeypatch.setattr(config, "SETTINGS_FILE", str(settings))
        monkeypatch.setattr(config, "SEARCH_HISTORY_FILE", str(search))
        monkeypatch.setattr(config, "ARTIST_HISTORY_FILE", str(artist))
        monkeypatch.setattr(config, "TIP_RECORDS_FILE", str(tips))

        ensure_config_files()
        assert json.loads(settings.read_text(encoding="utf-8")) == config.DEFAULT_SETTINGS
        assert json.loads(search.read_text(encoding="utf-8")) == []
        assert json.loads(artist.read_text(encoding="utf-8")) == []
        assert json.loads(tips.read_text(encoding="utf-8")) == []

        settings.write_text('{"scheme": "mono"}', encoding="utf-8")
        ensure_config_files()
        assert json.loads(settings.read_text(encoding="utf-8")) == {"scheme": "mono"}


class TestHistory:
    def test_search_history_add_dedupe_and_trim(self, tmp_path):
        path = tmp_path / "search.json"
        history = SearchHistory(str(path), max_items=3)
        history.add("晴天")
        history.add("夜曲")
        history.add("晴天")
        assert history.get_all() == ["晴天", "夜曲"]

        history.add("稻香")
        history.add("七里香")
        assert history.get_all() == ["七里香", "稻香", "晴天"]

        # 持久化后重新加载
        reloaded = SearchHistory(str(path), max_items=3)
        assert reloaded.get_all() == history.get_all()

    def test_artist_history_ignores_blank_and_non_str(self, tmp_path):
        history = ArtistHistory(str(tmp_path / "artist.json"), max_items=10)
        history.add("")
        history.add("   ")
        history.add(None)  # type: ignore[arg-type]
        history.add("周杰伦")
        assert history.get_all() == ["周杰伦"]

    def test_clear(self, tmp_path):
        path = tmp_path / "search.json"
        history = SearchHistory(str(path))
        history.add("晴天")
        history.clear()
        assert history.get_all() == []
        assert json.loads(path.read_text(encoding="utf-8")) == []

    def test_load_filters_invalid_entries(self, tmp_path):
        path = tmp_path / "search.json"
        path.write_text(json.dumps(["晴天", 1, None, "  ", "夜曲"]),
                        encoding="utf-8")
        assert SearchHistory(str(path)).get_all() == ["晴天", "夜曲"]

    def test_corrupt_file_falls_back_empty(self, tmp_path):
        path = tmp_path / "search.json"
        path.write_text("{broken", encoding="utf-8")
        assert SearchHistory(str(path)).get_all() == []


class TestTipRecords:
    def test_add_and_summary(self, tmp_path):
        store = TipRecordStore(str(tmp_path / "tips.json"))
        assert store.add("wechat", "success") is not None
        record = store.add("alipay", "failed")
        assert record is not None
        assert store.summary() == (1, 1)

        reloaded = TipRecordStore(str(tmp_path / "tips.json"))
        assert len(reloaded.records) == 2
        assert reloaded.summary() == (1, 1)

    def test_invalid_arguments(self, tmp_path):
        store = TipRecordStore(str(tmp_path / "tips.json"))
        assert store.add("paypal", "success") is None
        assert store.add("wechat", "unknown") is None
        assert store.records == []

    def test_sanitize_drops_invalid_and_amount(self, tmp_path):
        path = tmp_path / "tips.json"
        path.write_text(json.dumps([
            {"id": "a", "ts": 1, "method": "wechat", "status": "success",
             "amount": 10},
            {"id": "", "ts": 1, "method": "wechat", "status": "success"},
            {"id": "b", "ts": "bad", "method": "wechat", "status": "success"},
            {"id": "c", "ts": 1, "method": "paypal", "status": "success"},
            {"id": "d", "ts": 1, "method": "wechat", "status": "unknown"},
            "garbage",
        ]), encoding="utf-8")
        store = TipRecordStore(str(path))
        assert store.records == [
            {"id": "a", "ts": 1, "method": "wechat", "status": "success"}
        ]

    def test_corrupt_file_backed_up(self, tmp_path):
        path = tmp_path / "tips.json"
        path.write_text("{broken", encoding="utf-8")
        store = TipRecordStore(str(path))
        assert store.records == []
        assert (tmp_path / "tips.json.bak").exists()

    def test_clear(self, tmp_path):
        path = tmp_path / "tips.json"
        store = TipRecordStore(str(path))
        store.add("wechat", "success")
        store.clear()
        assert store.records == []
        assert json.loads(path.read_text(encoding="utf-8")) == []


if __name__ == "__main__":
    raise SystemExit("请使用 pytest 运行该测试文件")
