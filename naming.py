#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""自定义文件命名模板。

变量占位符
    ``{title}`` ``{artist}`` ``{album}`` ``{year}`` ``{source}`` ``{quality}``

处理流程
    校验（非法字符 / 花括号 / 空占位符 / 未知变量）
    → 占位符替换 → 非法字符清理 → 空段与多余分隔符规整 → 长度截断

设计约束
    * 校验与渲染都是纯函数，不依赖 GUI，便于单元测试与复用；
    * 任何异常输入（``None`` / 非字符串 / 缺失字段）都必须得到可用的
      文件名，绝不能让命名失败中断下载流程。
"""

from __future__ import annotations

import re
from typing import Any, Final, Optional

from utils import safe_filename

DEFAULT_TEMPLATE: Final = "{artist} - {title}"

#: 支持的变量及其中文说明（GUI 设置页直接展示）
VARIABLES: Final[dict[str, str]] = {
    "title": "歌名",
    "artist": "歌手",
    "album": "专辑",
    "year": "年份",
    "source": "音源平台",
    "quality": "音质",
}

#: 预设模板（展示名, 模板串）
PRESET_TEMPLATES: Final[list[tuple[str, str]]] = [
    ("歌手 - 歌名", "{artist} - {title}"),
    ("歌名 - 歌手", "{title} - {artist}"),
    ("仅歌名", "{title}"),
    ("歌手·专辑·歌名", "{artist} - {album} - {title}"),
    ("年份 歌手-歌名", "{year} {artist} - {title}"),
    ("[歌手] 歌名", "[{artist}] {title}"),
]

#: 渲染结果 basename 上限（不含扩展名，预留路径长度）
MAX_BASENAME: Final = 120

_VAR_RE: Final = re.compile(r"\{([a-zA-Z_]+)\}")
_EMPTY_VAR_RE: Final = re.compile(r"\{\s*\}")
_ILLEGAL_IN_TEMPLATE_RE: Final = re.compile(r'[\\/:*?"<>|\r\n\t]')
_TRIM_EDGE_RE: Final = re.compile(r"^[\s\-_.·]+|[\s\-_.]+$")
_MULTI_SPACE_RE: Final = re.compile(r" {2,}")

#: 无占位符时，字面内容只含这些“装饰字符”视为空模板
_DECORATION_CHARS: Final = " -_·[]()《》"


def validate_template(tpl: str) -> tuple[bool, str, list[str]]:
    """校验命名模板合法性。

    Args:
        tpl: 待校验的模板字符串（允许 ``None``，按空模板处理）。

    Returns:
        ``(is_valid, error_message, used_variables)``。合法时 ``error_message``
        为空串；``used_variables`` 按出现顺序返回，重复变量会重复出现。
    """
    if not isinstance(tpl, str):
        return False, "模板不能为空", []
    text = tpl.strip()
    if not text:
        return False, "模板不能为空", []

    if any(ch in tpl for ch in ("\n", "\r", "\t")):
        return False, "模板不能包含换行或制表符", []

    illegal = sorted({
        match.group(0) for match in _ILLEGAL_IN_TEMPLATE_RE.finditer(tpl)
    })
    if illegal:
        display = "、".join(repr(char) for char in illegal)
        return False, f"包含文件名非法字符: {display}（字符会被系统拒绝或清理）", []

    if _EMPTY_VAR_RE.search(tpl):
        return False, "存在空的占位符 {}，请填写变量名", []

    # 剥离合法 token 后仍有花括号 → 未闭合 / 多余 / 嵌套错误
    residue = _VAR_RE.sub("", tpl)
    if "{" in residue or "}" in residue:
        return False, "花括号不匹配（存在未闭合的 '{' 或多余的 '}'）", []

    used = _VAR_RE.findall(tpl)
    unknown = sorted({name for name in used if name not in VARIABLES})
    if unknown:
        bad = "} {".join(unknown)
        known = "、".join(f"{{{name}}}" for name in VARIABLES)
        return False, f"未知变量: {{{bad}}}（可用: {known}）", []

    # 无占位符且字面部分全为分隔符 → 渲染必然为空或纯符号
    if not used and not residue.strip(_DECORATION_CHARS):
        return False, "模板不含任何有效内容（无占位符且无有效文字）", []
    return True, "", used


def _substitute(tpl: str, meta: dict[str, Any]) -> str:
    """替换已知占位符；缺失字段渲染为空串，未知占位符原样保留。"""

    def replace(match: re.Match[str]) -> str:
        value = meta.get(match.group(1))
        # 与历史行为保持一致：0 / False 等假值视同缺失
        return str(value).strip() if value else ""

    return _VAR_RE.sub(replace, tpl)


def _normalize_segments(name: str) -> str:
    """清理空占位段与多余分隔符。

    缺失字段会留下形如 ``"A -  - B"`` 的空段。这里按 ``-`` 切分、丢弃空段后
    用 ``" - "`` 重新拼接，并去掉首尾装饰字符。
    """
    name = safe_filename(name)
    name = _MULTI_SPACE_RE.sub(" ", name).strip()
    parts = [part.strip() for part in name.split("-")]
    parts = [part for part in parts if part]
    name = " - ".join(parts)
    return _TRIM_EDGE_RE.sub("", name)


def render_name(tpl: str, meta: dict[str, Any], *, max_len: int = MAX_BASENAME) -> str:
    """按模板渲染文件名 basename（不含扩展名）。

    * 未知占位符原样保留（校验阶段已拦截，此处仅兜底）；
    * 缺失字段替换为空串，随后清理空段与多余分隔符；
    * 渲染结果为空时回退 ``artist - title``，仍为空则回退 ``untitled``；
    * 结果超过 ``max_len`` 时截断，并去掉截断处的尾部分隔符。
    """
    if not isinstance(tpl, str) or not tpl.strip():
        tpl = DEFAULT_TEMPLATE
    if not isinstance(meta, dict):
        meta = {}

    name = _normalize_segments(_substitute(tpl, meta))
    if not name:
        fallback = safe_filename(
            f"{meta.get('artist', '')} - {meta.get('title', '')}"
        ).strip(" -_")
        name = fallback or "untitled"

    limit = max(0, int(max_len))
    if len(name) > limit:
        name = name[:limit].rstrip(" ._-·")
    return name


def render_filename(tpl: str, meta: dict[str, Any], ext: str, *,
                    max_len: int = MAX_BASENAME,
                    fallback: Optional[str] = None) -> str:
    """渲染完整文件名（含扩展名）。``ext`` 带不带点均可。

    Args:
        tpl: 命名模板；非法或为空时使用 ``fallback``。
        meta: 元数据字典。
        ext: 扩展名，如 ``"flac"`` 或 ``".mp3"``。
        max_len: basename 最大长度。
        fallback: 模板非法时的整名回退（如 ``"歌手 - 歌名"``）。
    """
    normalized_ext = str(ext or "").lower().lstrip(".")
    ok, _error, _used = validate_template(tpl or "")
    if not ok:
        base = safe_filename(fallback) if fallback else ""
        base = base or render_name(DEFAULT_TEMPLATE, meta)
    else:
        base = render_name(tpl, meta, max_len=max_len)
    return f"{base}.{normalized_ext}"


def sample_meta() -> dict[str, str]:
    """设置页实时预览用的示例元数据。"""
    return {
        "title": "晴天",
        "artist": "周杰伦",
        "album": "叶惠美",
        "year": "2003",
        "source": "qq",
        "quality": "无损",
    }
