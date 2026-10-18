#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""naming 模块单元测试：模板校验、命名渲染、异常回退、下载任务集成"""

import os
import sys
import unittest
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from naming import (
    DEFAULT_TEMPLATE,
    render_filename, render_name, sample_meta, validate_template,
)
from downloader import DownloadQueue
from utils import safe_filename

META = sample_meta()  # 晴天 / 周杰伦 / 叶惠美 / 2003 / qq / 无损


class TestValidateTemplate(unittest.TestCase):
    """模板合法性校验"""

    def test_valid_default(self):
        ok, err, used = validate_template("{artist} - {title}")
        self.assertTrue(ok)
        self.assertEqual(err, "")
        self.assertEqual(used, ["artist", "title"])

    def test_valid_all_vars(self):
        ok, _err, used = validate_template(
            "{year} {artist} [{album}] {title} ({source}-{quality})")
        self.assertTrue(ok)
        self.assertEqual(len(used), 6)

    def test_empty(self):
        for tpl in ("", "   "):
            ok, err, _ = validate_template(tpl)
            self.assertFalse(ok)
            self.assertIn("为空", err)

    def test_newline_tab(self):
        ok, err, _ = validate_template("{title}\n")
        self.assertFalse(ok)
        self.assertIn("换行", err)
        ok, err, _ = validate_template("{title}\t{artist}")
        self.assertFalse(ok)

    def test_illegal_chars(self):
        for ch in ('\\', '/', ':', '*', '?', '"', '<', '>', '|'):
            ok, err, _ = validate_template(f"{{title}}{ch}x")
            self.assertFalse(ok)
            self.assertIn("非法字符", err)
            self.assertIn(repr(ch), err)

    def test_empty_placeholder(self):
        ok, err, _ = validate_template("{title}{}")
        self.assertFalse(ok)
        self.assertIn("空的占位符", err)

    def test_unclosed_brace(self):
        ok, err, _ = validate_template("{artist - {title}")
        self.assertFalse(ok)
        self.assertIn("花括号不匹配", err)
        ok, err, _ = validate_template("}title")
        self.assertFalse(ok)
        self.assertIn("花括号不匹配", err)

    def test_unknown_var(self):
        ok, err, _ = validate_template("{title} - {singer}")
        self.assertFalse(ok)
        self.assertIn("未知变量", err)
        self.assertIn("{singer}", err)
        self.assertIn("可用", err)

    def test_no_placeholder_delimiter_only(self):
        # 无占位符且字面全为分隔符 → 渲染必为空
        ok, err, _ = validate_template(" - _ · ")
        self.assertFalse(ok)
        self.assertIn("不含任何有效内容", err)

    def test_literal_only_valid(self):
        # 纯字面文本合法（虽无变量）
        ok, _err, used = validate_template("我的音乐")
        self.assertTrue(ok)
        self.assertEqual(used, [])

    def test_none_input(self):
        ok, _err, _used = validate_template(None)  # type: ignore[arg-type]
        self.assertFalse(ok)


class TestRenderName(unittest.TestCase):
    """命名渲染"""

    def test_basic(self):
        self.assertEqual(
            render_name("{artist} - {title}", META), "周杰伦 - 晴天")

    def test_all_vars(self):
        self.assertEqual(
            render_name("{year} {artist} - {album} - {title}", META),
            "2003 周杰伦 - 叶惠美 - 晴天")

    def test_missing_fields_skipped(self):
        # 缺失字段渲染为空段，整段被丢弃
        self.assertEqual(
            render_name("{artist} - {album} - {title}",
                        {"artist": "A", "title": "B"}),
            "A - B")

    def test_empty_var_drops_segment(self):
        self.assertEqual(
            render_name("{artist} - {title}",
                        {"title": "晴天"}),
            "晴天")

    def test_illegal_chars_cleaned(self):
        meta = {"title": 'a/b\\c:d*e?f"g<h>i|j'}
        self.assertEqual(render_name("{title}", meta), "abcdefghij")

    def test_multi_space_collapse(self):
        self.assertEqual(
            render_name("{artist}  -  {title}", META), "周杰伦 - 晴天")

    def test_trim_edges(self):
        self.assertEqual(render_name("{title} - ", {"title": "晴天"}), "晴天")
        self.assertEqual(render_name("- {title}", {"title": "晴天"}), "晴天")

    def test_truncate(self):
        meta = {"title": "长" * 300}
        name = render_name("{title}", meta, max_len=50)
        self.assertLessEqual(len(name), 50)

    def test_fallback_default_when_empty_tpl(self):
        self.assertEqual(
            render_name("", META), render_name(DEFAULT_TEMPLATE, META))

    def test_fallback_artist_title_when_render_empty(self):
        # 全部字段缺失 → 回退 artist - title，再缺失 → untitled
        self.assertEqual(render_name("{album}", {}), "untitled")
        self.assertEqual(
            render_name("{album}", {"artist": "A", "title": "B"}), "A - B")

    def test_fallback_strips_separators(self):
        # 回退结果同样清理首尾分隔符
        self.assertEqual(
            render_name("{album}", {"artist": "", "title": "B"}), "B")


class TestRenderFilename(unittest.TestCase):
    """完整文件名渲染与兜底"""

    def test_normal(self):
        self.assertEqual(
            render_filename("{artist} - {title}", META, "flac"),
            "周杰伦 - 晴天.flac")

    def test_ext_with_dot(self):
        self.assertEqual(
            render_filename("{title}", META, ".mp3"), "晴天.mp3")

    def test_ext_uppercase(self):
        self.assertEqual(
            render_filename("{title}", META, "FLAC"), "晴天.flac")

    def test_invalid_template_fallback(self):
        # 非法模板 → 使用 fallback 整名
        out = render_filename("{title}/{singer}", META, "mp3",
                              fallback="周杰伦 - 晴天")
        self.assertEqual(out, "周杰伦 - 晴天.mp3")

    def test_invalid_template_no_fallback(self):
        out = render_filename(None, META, "mp3")  # type: ignore[arg-type]
        self.assertEqual(out, "周杰伦 - 晴天.mp3")

    def test_fallback_sanitized(self):
        out = render_filename("", META, "mp3", fallback='a/b"c')
        self.assertEqual(out, "abc.mp3")


class TestDownloadQueueIntegration(unittest.TestCase):
    """add_task 命名模板集成"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.queue = DownloadQueue(directory=self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _add(self, tpl, **kw):
        return self.queue.add_task(
            title="晴天", artist="周杰伦", audio_url="https://x/song.flac",
            quality="无损", source="qq", name_template=tpl, **kw)

    def test_template_applied(self):
        task = self._add("{artist} - {title}")
        self.assertEqual(os.path.basename(task.filepath), "周杰伦 - 晴天.flac")

    def test_meta_vars(self):
        task = self._add(
            "{source}_{quality}_{title}",
            meta={"album": "叶惠美", "year": "2003"})
        self.assertEqual(
            os.path.basename(task.filepath), "qq_无损_晴天.flac")

    def test_invalid_template_fallback(self):
        task = self._add("{title}/{singer}")
        self.assertEqual(os.path.basename(task.filepath), "周杰伦 - 晴天.flac")

    def test_none_template_default(self):
        task = self._add(None)
        self.assertEqual(os.path.basename(task.filepath), "周杰伦 - 晴天.flac")

    def test_meta_not_mutated(self):
        meta = {"album": "叶惠美"}
        self._add("{title}", meta=meta)
        self.assertEqual(meta, {"album": "叶惠美"})

    def test_title_with_illegal_chars(self):
        task = self.queue.add_task(
            title='a/b:c', artist="周杰伦", audio_url="https://x/s.mp3",
            name_template="{artist} - {title}")
        self.assertEqual(
            os.path.basename(task.filepath),
            f"{safe_filename('周杰伦 - abc')}.mp3")


if __name__ == "__main__":
    unittest.main(verbosity=2)
