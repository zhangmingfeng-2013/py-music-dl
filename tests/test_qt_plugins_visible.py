# -*- coding: utf-8 -*-

"""ensure_qt_plugins_visible 自愈逻辑验证用例（bug: UF_HIDDEN 致 Qt 平台插件不可见）

运行：.venv/bin/python tests/test_qt_plugins_visible.py
也可被 pytest 收集（函数均以 test_ 开头）。
"""

import contextlib
import io
import os
import stat
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # 无 WindowServer 环境可运行

from PyQt6.QtCore import QDir  # noqa: E402

import gui_qt  # noqa: E402


def _platforms_dir() -> Path:
    import PyQt6

    return Path(PyQt6.__file__).parent / "Qt6" / "plugins" / "platforms"


def _qdir_count(path: Path) -> int:
    return QDir(str(path)).count()  # 含 "." 与 ".."，空目录为 2


def test_healthy_tree_is_noop():
    """健康环境：函数为无副作用空操作，插件目录保持可见。"""
    platforms = _platforms_dir()
    assert platforms.is_dir(), "PyQt6 platforms 插件目录不存在"
    before = _qdir_count(platforms)
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        gui_qt.ensure_qt_plugins_visible()
        gui_qt.ensure_qt_plugins_visible()  # 幂等：重复调用不报错
    assert _qdir_count(platforms) == before, "健康环境下目录可见性被改变"
    assert "hidden 标志" not in stderr.getvalue(), "健康环境不应触发自愈告警"


def test_reproduce_and_heal():
    """复现→自愈：全部插件 dylib 打 hidden 标志后 QDir 视为空目录，自愈后恢复。

    Qt 逐文件过滤 hidden 条目（count = 2 + 未打标文件数），全量打标才会
    复现线上故障"插件目录为空"；自愈函数对单个/部分打标同样生效。
    """
    platforms = _platforms_dir()
    targets = list(platforms.glob("*.dylib"))
    try:
        for t in targets:
            os.chflags(str(t), stat.UF_HIDDEN)
        assert _qdir_count(platforms) == 2, (
            "未复现 bug：QDir 应因 UF_HIDDEN 枚举为空（count==2）"
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            gui_qt.ensure_qt_plugins_visible()
        assert _qdir_count(platforms) > 2, "自愈失败：QDir 仍不可见插件"
        assert "hidden 标志" in stderr.getvalue(), "自愈时未输出告警信息"
        for t in targets:
            assert not (os.stat(str(t)).st_flags & stat.UF_HIDDEN), (
                f"{t.name} 的 UF_HIDDEN 标志未被清除"
            )
    finally:
        # 兜底恢复，避免用例失败时遗留坏环境
        for t in targets:
            if os.stat(str(t)).st_flags & stat.UF_HIDDEN:
                os.chflags(str(t), 0)


def test_scope_limited_to_qt6_plugins():
    """边界：自愈只处理 Qt6/plugins 子树，不影响外部被打标志的文件。"""
    outside = PROJECT_ROOT / ".tmp_ufhidden_probe"
    outside.write_text("probe")
    try:
        os.chflags(str(outside), stat.UF_HIDDEN)
        with contextlib.redirect_stderr(io.StringIO()):
            gui_qt.ensure_qt_plugins_visible()
        assert os.stat(str(outside)).st_flags & stat.UF_HIDDEN, (
            "越界修复：Qt6/plugins 之外的文件不应被改动"
        )
    finally:
        os.chflags(str(outside), 0)  # 还原标志以便删除
        outside.unlink()


def main() -> None:
    cases = [
        test_healthy_tree_is_noop,
        test_reproduce_and_heal,
        test_scope_limited_to_qt6_plugins,
    ]
    for case in cases:
        case()
        print(f"PASS {case.__name__}")
    print(f"全部 {len(cases)} 个用例通过")


if __name__ == "__main__":
    main()
