#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""api.py 单元测试：平台响应解析、交错排序、版本识别、歌词兜底。

全部用例通过 monkeypatch 替换网络层，不发起真实请求。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import api  # noqa: E402


def _mock_json(monkeypatch, payload):
    calls = []

    def fake_get_json(url, params=None, headers=None, timeout=10, quiet=False):
        calls.append((url, params, quiet))
        return payload

    monkeypatch.setattr(api, "_get_json", fake_get_json)
    return calls


class TestSearchParsers:
    def test_migu(self, monkeypatch):
        _mock_json(monkeypatch, {
            "code": 200,
            "data": [
                {"title": "晴天", "singer": "周杰伦", "n": 2, "cover": "c"},
                "not-a-dict",
            ],
        })
        songs = api._search_migu("晴天", limit=3)
        assert len(songs) == 1
        song = songs[0]
        assert song["source"] == "migu"
        assert song["title"] == "晴天"
        assert song["index"] == 2
        assert song["request_num"] == 3
        assert song["keyword"] == "晴天"

    def test_migu_failure_payloads(self, monkeypatch):
        for payload in (None, {}, {"code": 500}, {"code": 200, "data": {}}):
            _mock_json(monkeypatch, payload)
            assert api._search_migu("x") == []

    def test_netease(self, monkeypatch):
        _mock_json(monkeypatch, {
            "data": [
                {"song": "夜曲", "singer": "周杰伦", "id": 1,
                 "album": "十一月的萧邦", "cover": "c"},
                None,
            ],
        })
        songs = api._search_netease("夜曲", page=2, num=10)
        assert len(songs) == 1
        assert songs[0]["title"] == "夜曲"
        assert songs[0]["song_id"] == 1
        assert songs[0]["display_index"] == 11

    def test_qq_accepts_list_and_dict(self, monkeypatch):
        item = {"song_mid": "mid1", "song_title": "晴天", "singer_name": "周杰伦"}
        _mock_json(monkeypatch, [item, {"song_title": "无 mid"}])
        songs = api._search_qq("晴天")
        assert [s["song_mid"] for s in songs] == ["mid1"]
        assert songs[0]["qq_search_key"] == "晴天"

        _mock_json(monkeypatch, {"data": [item]})
        assert api._search_qq("晴天")[0]["song_mid"] == "mid1"

    def test_kuwo_list_and_nested(self, monkeypatch):
        item = {"rid": "MUSIC_9", "name": "晴天", "artist": "周杰伦",
                "url": "https://x/a.flac"}
        _mock_json(monkeypatch, {"data": [item]})
        songs = api._search_kuwo("晴天")
        assert songs[0]["rid"] == "9"
        assert songs[0]["quality"] == "LOSSLESS"

        _mock_json(monkeypatch, {"data": {"list": [item]}})
        assert api._search_kuwo("晴天")[0]["rid"] == "9"

        _mock_json(monkeypatch, {"data": {"data": [item]}})
        assert api._search_kuwo("晴天")[0]["title"] == "晴天"

    def test_kuwo_invalid(self, monkeypatch):
        _mock_json(monkeypatch, {"data": "bad"})
        assert api._search_kuwo("x") == []
        _mock_json(monkeypatch, None)
        assert api._search_kuwo("x") == []


class TestInterleave:
    def test_round_robin(self):
        groups = {
            "A": [{"title": "a1"}, {"title": "a2"}],
            "B": [{"title": "b1"}],
            "C": [],
        }
        result = api._interleave(groups, ["A", "B", "C"])
        assert [song["title"] for song in result] == ["a1", "b1", "a2"]
        assert [song["display_order"] for song in result] == [0, 1, 2]
        assert [song["source_name"] for song in result] == ["A", "B", "A"]

    def test_missing_group_does_not_raise(self):
        assert api._interleave({}, ["A"]) == []


class TestSearchAll:
    def test_concurrent_search_and_failure_isolation(self, monkeypatch):
        searchers = {
            "migu": ("咪咕音乐", lambda kw: [{"title": "m1", "source": "migu"}]),
            "netease": ("网易云音乐",
                        lambda kw: [{"title": "n1", "source": "netease"}]),
            "qq": ("QQ音乐", lambda kw: (_ for _ in ()).throw(RuntimeError("boom"))),
            "kuwo": ("酷我音乐", lambda kw: [{"title": "k1", "source": "kuwo"}]),
        }
        monkeypatch.setattr(api, "_SEARCHERS", searchers)
        result = api.search_all_platforms("晴天")
        assert [song["title"] for song in result] == ["m1", "n1", "k1"]
        assert all("source_name" in song for song in result)

    def test_prefetch_quality(self, monkeypatch):
        monkeypatch.setitem(
            api._DETAILERS, "migu",
            lambda song: {"quality": "LOSSLESS"} if song["title"] == "a" else None,
        )
        songs = [
            {"source": "migu", "title": "a"},
            {"source": "migu", "title": "b"},
            {"source": "kuwo", "title": "c", "quality": "320K"},
        ]
        api.prefetch_quality(songs)
        assert songs[0]["quality"] == "LOSSLESS"
        assert "quality" not in songs[1]
        assert songs[2]["quality"] == "320K"


class TestVersionRisk:
    def test_bad_version(self):
        assert api.detect_version_risk("晴天 (伴奏)", "晴天") == ("bad", "伴奏")
        assert api.detect_version_risk("晴天 Instrumental", "晴天") == (
            "bad", "instrumental"
        )

    def test_variant_version(self):
        assert api.detect_version_risk("晴天 Live", "晴天") == ("variant", "live")
        assert api.detect_version_risk("晴天 翻唱", "晴天") == ("variant", "翻唱")

    def test_user_searched_marker_is_not_flagged(self):
        assert api.detect_version_risk("晴天 伴奏", "晴天 伴奏") == ("", "")
        assert api.detect_version_risk("晴天 现场", "晴天 现场") == ("", "")

    def test_no_risk(self):
        assert api.detect_version_risk("晴天", "晴天") == ("", "")

    def test_title_consistency(self):
        assert api._titles_consistent("晴天", "晴天")
        assert api._titles_consistent("晴天", "晴天 (Live)")
        assert api._titles_consistent("", "晴天")
        assert not api._titles_consistent("晴天", "雨天")


class TestResolveSong:
    def _song(self):
        return {
            "source": "migu", "title": "晴天", "artist": "周杰伦",
            "album": "叶惠美", "year": "2003", "cover": "cover-url",
            "lrc_url": "lrc-url",
        }

    def test_backfill_and_metadata(self, monkeypatch):
        monkeypatch.setitem(
            api._DETAILERS, "migu",
            lambda song: {
                "title": "晴天", "audio_url": "https://x/a.flac",
                "quality": "LOSSLESS",
            },
        )
        detail = api.resolve_song(self._song())
        assert detail is not None
        assert detail["audio_url"] == "https://x/a.flac"
        assert detail["artist"] == "周杰伦"
        assert detail["album"] == "叶惠美"
        assert detail["year"] == "2003"
        assert detail["cover"] == "cover-url"
        assert detail["lrc_url"] == "lrc-url"
        assert detail["version_tag"] == ""
        assert detail["quality"] == "LOSSLESS"

    def test_bad_version_blocked_by_get_detail(self, monkeypatch):
        monkeypatch.setitem(
            api._DETAILERS, "migu",
            lambda song: {"title": "晴天 (伴奏)", "audio_url": "https://x/a.mp3"},
        )
        song = self._song()
        resolved = api.resolve_song(song)
        assert resolved is not None
        assert resolved["version_tag"] == "bad"
        assert api.get_song_detail(song) is None

    def test_inconsistent_title_dropped(self, monkeypatch):
        monkeypatch.setitem(
            api._DETAILERS, "migu",
            lambda song: {"title": "雨天", "audio_url": "https://x/a.mp3"},
        )
        assert api.resolve_song(self._song()) is None

    def test_missing_url_and_exception(self, monkeypatch):
        monkeypatch.setitem(
            api._DETAILERS, "migu", lambda song: {"title": "晴天"}
        )
        assert api.resolve_song(self._song()) is None

        def boom(_song):
            raise RuntimeError("upstream")

        monkeypatch.setitem(api._DETAILERS, "migu", boom)
        assert api.resolve_song(self._song()) is None

    def test_unknown_source(self):
        assert api.resolve_song({"source": "unknown"}) is None


class TestNeteaseExtra:
    def test_millisecond_timestamp(self, monkeypatch):
        monkeypatch.setattr(api, "_get_json", lambda *a, **k: {
            "songs": [{"al": {
                "name": "叶惠美", "publishTime": 1041379200000,
                "picUrl": "p",
            }}],
        })
        extra = api._netease_extra(1)
        assert extra == {"album": "叶惠美", "year": "2003", "cover": "p"}

    def test_second_timestamp(self, monkeypatch):
        monkeypatch.setattr(api, "_get_json", lambda *a, **k: {
            "songs": [{"al": {"publishTime": 1041379200}}],
        })
        assert api._netease_extra(1)["year"] == "2003"

    def test_dirty_year_and_missing(self, monkeypatch):
        monkeypatch.setattr(api, "_get_json", lambda *a, **k: {
            "songs": [{"al": {"publishTime": 9992678400000}}],
        })
        assert api._netease_extra(1)["year"] == ""
        monkeypatch.setattr(api, "_get_json", lambda *a, **k: {})
        assert api._netease_extra(1) is None


class TestLyrics:
    def test_existing_text_short_circuits(self, monkeypatch):
        calls = []
        monkeypatch.setattr(api, "_get_text", lambda *a, **k: calls.append("text"))
        text = api.fetch_lyrics({"lyrics": "  [00:00]hi  "})
        assert text == "[00:00]hi"
        assert calls == []

    def test_lrc_url_priority(self, monkeypatch):
        monkeypatch.setattr(api, "_get_text", lambda url, **k: "[00:01]a\n")

        def unexpected(_song_id):
            raise AssertionError("不应走到网易云 ID 兜底")

        monkeypatch.setattr(api, "_netease_lyrics_by_id", unexpected)
        assert api.fetch_lyrics({"lrc_url": "https://x/a.lrc"}) == "[00:01]a"

    def test_lrc_url_without_tags_falls_back(self, monkeypatch):
        monkeypatch.setattr(api, "_get_text", lambda url, **k: "plain text")
        monkeypatch.setattr(api, "_netease_lyrics_by_id", lambda sid: "[00:02]b")
        monkeypatch.setattr(api, "_netease_search_lyric", lambda *a, **k: None)
        monkeypatch.setattr(api, "_lrclib_lyrics", lambda *a, **k: None)
        meta = {"lrc_url": "https://x/a.lrc", "source": "netease", "song_id": 1}
        assert api.fetch_lyrics(meta) == "[00:02]b"

    def test_order_netease_then_lrclib(self, monkeypatch):
        order = []
        monkeypatch.setattr(api, "_netease_search_lyric",
                            lambda *a, **k: order.append("search") or None)
        monkeypatch.setattr(api, "_lrclib_lyrics",
                            lambda *a, **k: order.append("lrclib") or "lrclib-text")
        assert api.fetch_lyrics({"title": "晴天"}) == "lrclib-text"
        assert order == ["search", "lrclib"]

    def test_all_fail_returns_none(self, monkeypatch):
        monkeypatch.setattr(api, "_netease_search_lyric", lambda *a, **k: None)
        monkeypatch.setattr(api, "_lrclib_lyrics", lambda *a, **k: None)
        assert api.fetch_lyrics({"title": "晴天"}) is None

    def test_strip_timestamps(self):
        lrc = "[ti:晴天]\n[ar:周杰伦]\n[00:01.00]第一句\n[00:02.50]第二句\n[00:02.50]第二句\n\n"
        assert api.strip_lrc_timestamps(lrc) == "第一句\n第二句"
        assert api.strip_lrc_timestamps("") == ""


class TestHttpResponseGuards:
    def test_get_json_handles_invalid_json(self, monkeypatch):
        import json

        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                raise json.JSONDecodeError("not json", "", 0)

        monkeypatch.setattr(api.requests, "get", lambda *a, **k: Response())
        assert api._get_json("https://x", quiet=True) is None

    def test_kuwo_detail_payload(self):
        assert api._kuwo_detail_payload({"url": "u"}) == "u"
        assert api._kuwo_detail_payload({"data": {"url": "u2"}}) == "u2"
        assert api._kuwo_detail_payload([]) == ""


if __name__ == "__main__":
    raise SystemExit("请使用 pytest 运行该测试文件")
