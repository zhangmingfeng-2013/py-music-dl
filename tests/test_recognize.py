#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""recognize.py 纯逻辑测试：窗口规划、偏移校验、共识投票、结果解析（不触网）。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import recognize as rec  # noqa: E402
from recognize import SUPPORTED_EXT, _parse_shazam_track, recognize_file  # noqa: E402

_TRACK_FULL = {
    "title": "夜曲",
    "subtitle": "周杰伦",
    "images": {"coverart": "https://example.com/cover.jpg"},
    "genres": {"primary": "Pop"},
    "sections": [
        {"metadata": [
            {"title": "Album", "text": "十一月的萧邦"},
            {"title": "Label", "text": "JVR"},
            {"title": "Released", "text": "2005"},
        ]},
    ],
}

_TRACK_A = {"key": 101, "title": "可不可以", "subtitle": "张紫豪"}
_TRACK_B = {"key": 202, "title": "海阔天空", "subtitle": "Beyond"}


class TestParseTrack:
    def test_parse_full_track(self) -> None:
        meta = _parse_shazam_track(_TRACK_FULL)
        assert meta["title"] == "夜曲"
        assert meta["artist"] == "周杰伦"
        assert meta["album"] == "十一月的萧邦"
        assert meta["cover_url"] == "https://example.com/cover.jpg"
        assert meta["genre"] == "Pop"
        assert meta["year"] == "2005"

    def test_parse_localized_metadata(self) -> None:
        track = {
            "title": "可不可以", "subtitle": "张紫豪",
            "sections": [{"metadata": [
                {"title": "专辑", "text": "可不可以 (抖音热歌) - Single"},
                {"title": "唱片公司", "text": "恬音文化"},
                {"title": "发行时间", "text": "2018-09-28"},
            ]}],
        }
        meta = _parse_shazam_track(track)
        assert meta["album"] == "可不可以 (抖音热歌) - Single"
        assert meta["year"] == "2018"

    def test_parse_falls_back_to_hq_cover(self) -> None:
        meta = _parse_shazam_track(
            {"title": "T", "images": {"coverarthq": "https://x/hq.jpg"}})
        assert meta["cover_url"] == "https://x/hq.jpg"

    def test_parse_missing_fields(self) -> None:
        meta = _parse_shazam_track({"title": "只有标题"})
        assert meta["title"] == "只有标题"
        assert meta["artist"] == "" and meta["album"] == ""
        assert meta["cover_url"] == "" and meta["year"] == ""

    def test_parse_garbage(self) -> None:
        meta = _parse_shazam_track({"sections": "not-a-list"})
        assert meta["title"] == ""
        meta2 = _parse_shazam_track({"sections": [None, {"metadata": "x"}]})
        assert meta2["album"] == ""


class TestWindowPlanning:
    def test_unknown_or_short_duration_single_window(self) -> None:
        assert rec._candidate_starts(0) == [0.0]
        assert rec._candidate_starts(8) == [0.0]
        assert rec._candidate_starts(12.5) == [0.0]
        assert rec._candidate_starts("bad") == [0.0]

    def test_spread_windows_stay_inside_track(self) -> None:
        duration = 240.0
        starts = rec._candidate_starts(duration)
        assert starts[0] == 0.0
        assert len(starts) >= 4
        assert all(0 <= s <= duration - rec._WINDOW_SECONDS for s in starts)
        # 窗口互不重叠（起点间距大于去重阈值）
        for i, first in enumerate(starts):
            for second in starts[i + 1:]:
                assert abs(first - second) > 2.0

    def test_short_track_windows_clamped(self) -> None:
        starts = rec._candidate_starts(30.0)
        assert all(0 <= s <= 30.0 - rec._WINDOW_SECONDS for s in starts)


class TestOffsetValidation:
    def test_false_positive_offset_rejected(self) -> None:
        # 15s 片段被居中分析 2.5–12.5s，却命中 95.2s —— 典型唯一性误报
        assert rec._offset_is_plausible(95.2, 2.5, 10.0) is False

    def test_hit_before_window_start_rejected(self) -> None:
        # 窗口 44.25s 起，参考曲目命中在第 41.75s：仅片段尾部重叠，属误报
        assert rec._offset_is_plausible(41.75, 44.25, 12.0) is False

    def test_in_window_offsets_accepted(self) -> None:
        assert rec._offset_is_plausible(1.0, 0.0, 12.0) is True
        assert rec._offset_is_plausible(0.0, 0.0, 12.0) is True
        assert rec._offset_is_plausible(13.0, 0.0, 12.0) is True   # 末尾容差内
        assert rec._offset_is_plausible(-0.5, 0.0, 12.0) is True   # 起点抖动内

    def test_analyzed_span_centers_long_windows(self) -> None:
        assert rec._analyzed_span(0.0, 15.0, 10.0) == (2.5, 10.0)
        assert rec._analyzed_span(5.0, 12.0, 12.0) == (5.0, 12.0)
        assert rec._analyzed_span(5.0, 8.0, 12.0) == (5.0, 8.0)
        assert rec._analyzed_span(5.0, 12.0, -1.0) == (5.0, 12.0)


class TestConsensus:
    def test_majority_wins(self) -> None:
        track, confidence, votes = rec._pick_consensus(
            [_TRACK_A, _TRACK_B, _TRACK_A])
        assert track is _TRACK_A
        assert confidence == "high"
        assert votes == 2

    def test_single_hit_is_low_confidence(self) -> None:
        assert rec._pick_consensus([_TRACK_A]) == (_TRACK_A, "low", 1)

    def test_conflicting_single_hits_give_up(self) -> None:
        assert rec._pick_consensus([_TRACK_A, _TRACK_B]) == (None, "", 1)

    def test_tie_gives_up(self) -> None:
        assert rec._pick_consensus(
            [_TRACK_A, _TRACK_B, _TRACK_A, _TRACK_B]) == (None, "", 2)

    def test_empty(self) -> None:
        assert rec._pick_consensus([]) == (None, "", 0)

    def test_vote_key_falls_back_to_text(self) -> None:
        assert rec._track_vote_key(_TRACK_A) == "key:101"
        assert rec._track_vote_key(
            {"title": "Song", "subtitle": "Artist"}
        ) == "text:artist|song"


class TestEvaluateResult:
    def _result(self, offset: float = 1.0) -> dict:
        return {"track": dict(_TRACK_A), "matches": [{"offset": offset}]}

    def test_accepts_hit_inside_window(self) -> None:
        assert rec._evaluate_result(self._result(), 0.0, 12.0, 12.0) is not None

    def test_rejects_hit_outside_window(self) -> None:
        assert rec._evaluate_result(self._result(95.2), 0.0, 12.0, 12.0) is None

    def test_rejects_missing_track_or_matches(self) -> None:
        assert rec._evaluate_result("garbage", 0.0, 12.0, 12.0) is None
        assert rec._evaluate_result(
            {"track": {"title": "T"}, "matches": []}, 0.0, 12.0, 12.0) is None
        assert rec._evaluate_result(
            {"track": {"title": ""}, "matches": [{"offset": 0}]},
            0.0, 12.0, 12.0) is None


class TestEntryPoints:
    def test_unsupported_ext_rejected(self) -> None:
        assert ".txt" not in SUPPORTED_EXT
        assert recognize_file("/tmp/foo.txt") is None
        assert recognize_file("") is None
        assert recognize_file("/nonexistent/path/x.mp3") is None


if __name__ == "__main__":
    raise SystemExit("请使用 pytest 运行该测试文件")
