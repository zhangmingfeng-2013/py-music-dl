# -*- coding: utf-8 -*-

"""ffmpeg 检测逻辑回归测试（bug: installer/bin 内 Linux ELF 被误选导致检测失败）

运行：.venv/bin/python tests/test_ffmpeg_detect.py
也可被 pytest 收集。
"""

import os
import stat
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import media  # noqa: E402

BUNDLED_DIR = PROJECT_ROOT / "installer" / "bin"


def test_bundled_linux_elf_rejected_on_macos():
    """installer/bin 内的 Linux x86-64 ELF 在 macOS 上必须被魔数校验排除。"""
    if sys.platform != "darwin":
        return
    bundled = BUNDLED_DIR / "ffmpeg"
    if not bundled.exists():
        return  # 仓库未携带打包用二进制时跳过
    with open(bundled, "rb") as f:
        assert f.read(4) == b"\x7fELF", "前置假设变化：installer/bin 已非 ELF"
    assert not media._matches_host_platform(str(bundled)), (
        "Linux ELF 被误判为当前平台可执行文件"
    )


def test_resolve_tool_falls_back_to_path():
    """bundled 二进制平台不匹配时，必须回退到系统 PATH 中的 ffmpeg。"""
    resolved = media._resolve_tool("ffmpeg")
    bundled = BUNDLED_DIR / "ffmpeg"
    if bundled.exists() and not media._matches_host_platform(str(bundled)):
        assert Path(resolved) != bundled, "仍选中了平台不匹配的 bundled 二进制"


def test_ffmpeg_available():
    """本机已安装 ffmpeg（brew）时检测必须通过。"""
    import shutil

    if shutil.which("ffmpeg") is None:
        return  # 环境未装 ffmpeg 时跳过（CI 差异）
    assert media.ffmpeg_available(), "ffmpeg 存在但检测失败"


def test_magic_edge_cases():
    """边界：不存在文件与空文件均返回 False，不抛异常。"""
    assert not media._matches_host_platform(str(PROJECT_ROOT / "no_such_file"))
    probe = PROJECT_ROOT / ".tmp_empty_bin"
    probe.write_bytes(b"")
    try:
        os.chmod(str(probe), stat.S_IRWXU)
        assert not media._matches_host_platform(str(probe))
    finally:
        probe.unlink()


def main() -> None:
    cases = [
        test_bundled_linux_elf_rejected_on_macos,
        test_resolve_tool_falls_back_to_path,
        test_ffmpeg_available,
        test_magic_edge_cases,
    ]
    for case in cases:
        case()
        print(f"PASS {case.__name__}")
    print(f"全部 {len(cases)} 个用例通过")


if __name__ == "__main__":
    main()
