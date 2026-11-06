#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""架构回归：Qt GUI 与业务层必须不依赖 Tkinter，且公共接口保持稳定。"""

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _run(code: str, env_extra=None):
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        check=False,
    )


def test_qt_gui_does_not_import_tkinter():
    """gui_qt 通过 config/theme 复用业务层，不应再经由 gui.py 拖入 Tk。"""
    result = _run(
        "import sys\n"
        "import gui_qt\n"
        "assert 'gui' not in sys.modules, 'gui_qt 仍依赖 gui.py'\n"
        "assert 'tkinter' not in sys.modules, 'gui_qt 仍依赖 tkinter'\n"
        "print('ok')\n"
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_core_layer_has_no_gui_framework_dependency():
    """核心业务模块应可在无 GUI 环境（服务器 / CI）导入。"""
    result = _run(
        "import sys\n"
        "import api, config, downloader, ffmpeg, media, naming, theme, utils\n"
        "for name in ('tkinter', 'PyQt6'):\n"
        "    assert name not in sys.modules, name\n"
        "print('ok')\n"
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_public_api_compatibility():
    """重构后保留原有公共入口与常量。"""
    sys.path.insert(0, str(PROJECT_ROOT))
    import api
    import downloader
    import media
    import naming
    import utils

    assert callable(api.search_all_platforms)
    assert callable(api.prefetch_quality)
    assert callable(api.resolve_song)
    assert callable(api.get_song_detail)
    assert callable(api.fetch_lyrics)
    assert callable(api.strip_lrc_timestamps)
    assert api.PLATFORM_NAMES == (
        "咪咕音乐", "网易云音乐", "QQ音乐", "酷我音乐",
    )

    assert callable(downloader.DownloadQueue)
    assert callable(downloader.DownloadTask)
    assert callable(downloader.RateLimiter)
    assert downloader.TaskStatus.COMPLETED.value == "completed"

    assert callable(media.post_process)
    assert callable(media.ffmpeg_available)
    assert media.CONVERT_OFF == "off"

    assert callable(naming.validate_template)
    assert callable(naming.render_filename)
    assert callable(utils.quality_tier)
