#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""recognize.py 纯逻辑测试：Shazam 结果解析与入口边界（不触网）。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


def test_parse_full_track() -> None:
    meta = _parse_shazam_track(_TRACK_FULL)
    assert meta["title"] == "夜曲"
    assert meta["artist"] == "周杰伦"
    assert meta["album"] == "十一月的萧邦"
    assert meta["cover_url"] == "https://example.com/cover.jpg"
    assert meta["genre"] == "Pop"
    assert meta["year"] == "2005"


def test_parse_missing_fields() -> None:
    meta = _parse_shazam_track({"title": "只有标题"})
    assert meta["title"] == "只有标题"
    assert meta["artist"] == "" and meta["album"] == ""
    assert meta["cover_url"] == "" and meta["year"] == ""


def test_parse_garbage() -> None:
    meta = _parse_shazam_track({"sections": "not-a-list"})
    assert meta["title"] == ""
    meta2 = _parse_shazam_track({"sections": [None, {"metadata": "x"}]})
    assert meta2["album"] == ""


def test_unsupported_ext_rejected() -> None:
    assert ".txt" not in SUPPORTED_EXT
    assert recognize_file("/tmp/foo.txt") is None
    assert recognize_file("") is None
    assert recognize_file("/nonexistent/path/x.mp3") is None


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"全部 {len(fns)} 个用例通过")
