#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""transcribe.py 纯逻辑测试：LRC 后处理（不触网、不加载模型）。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from transcribe import _hundredths, _segments_to_lrc  # noqa: E402


class _Seg:
    """模拟 faster-whisper 的 Segment 对象。"""

    def __init__(self, start: float, end: float, text: str) -> None:
        self.start = start
        self.end = end
        self.text = text


def test_hundredths_format() -> None:
    assert _hundredths(0) == "[00:00.00]"
    assert _hundredths(61.234) == "[01:01.23]"
    assert _hundredths(59.999) == "[00:59.99]"  # 进位钳制到 99


def test_basic_lines() -> None:
    segs = [_Seg(1.0, 3.0, " 夜空中最亮的星 "), _Seg(3.5, 5.0, "能否听清")]
    lrc = _segments_to_lrc(segs)
    assert "[ti:" not in lrc and "[ar:" not in lrc
    assert lrc.splitlines() == ["[00:01.00]夜空中最亮的星", "[00:03.50]能否听清"]


def test_meta_tags() -> None:
    lrc = _segments_to_lrc([_Seg(0, 2, "词")], meta_title="歌名", meta_artist="歌手")
    lines = lrc.splitlines()
    assert lines[0] == "[ti:歌名]"
    assert lines[1] == "[ar:歌手]"
    assert lines[2].endswith("词")


def test_long_segment_split_by_punctuation() -> None:
    # 12s 长句含句末标点，应按标点拆分且时间线性递增
    segs = [_Seg(10.0, 22.0, "第一句词。第二句词！第三句词")]
    lrc = _segments_to_lrc(segs)
    lines = lrc.splitlines()
    assert len(lines) == 3
    assert "第一句词。" in lines[0] and "第二句词！" in lines[1] and "第三句词" in lines[2]
    # 时间戳递增
    ts = [line[1:9] for line in lines]
    assert ts == sorted(ts)


def test_short_segment_not_split() -> None:
    # ≤8s 的 segment 即使含标点也不拆
    segs = [_Seg(0.0, 6.0, "短句。不拆")]
    lrc = _segments_to_lrc(segs)
    assert len(lrc.splitlines()) == 1


def test_dedup_and_empty() -> None:
    segs = [_Seg(0, 2, "重复"), _Seg(2.5, 4, "重复"), _Seg(5, 6, "  "), _Seg(7, 8, "正常")]
    lines = _segments_to_lrc(segs).splitlines()
    assert lines == ["[00:00.00]重复", "[00:07.00]正常"]


def test_empty_segments() -> None:
    assert _segments_to_lrc([]) == ""


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"全部 {len(fns)} 个用例通过")
