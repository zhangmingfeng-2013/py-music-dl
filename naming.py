#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
自定义文件命名模板
- 变量占位符：{title} {artist} {album} {year} {source} {quality}
- 校验：非法字符、花括号不闭合、空占位符、未知变量、渲染结果为空
- 渲染：占位符替换 → 非法字符清理 → 空段/分隔符规整 → 长度截断
"""

from __future__ import annotations

import re
from typing import Optional

from utils import safe_filename

DEFAULT_TEMPLATE = "{artist} - {title}"

# 支持的变量及说明
VARIABLES: dict[str, str] = {
    "title": "歌名",
    "artist": "歌手",
    "album": "专辑",
    "year": "年份",
    "source": "音源平台",
    "quality": "音质",
}

_VAR_RE = re.compile(r"\{([a-zA-Z_]+)\}")
_EMPTY_VAR_RE = re.compile(r"\{\s*\}")
_ILLEGAL_IN_TEMPLATE_RE = re.compile(r'[\\/:*?"<>|\r\n\t]')

# 预设模板（标签, 模板）
PRESET_TEMPLATES: list[tuple[str, str]] = [
    ("歌手 - 歌名", "{artist} - {title}"),
    ("歌名 - 歌手", "{title} - {artist}"),
    ("仅歌名", "{title}"),
    ("歌手·专辑·歌名", "{artist} - {album} - {title}"),
    ("年份 歌手-歌名", "{year} {artist} - {title}"),
    ("[歌手] 歌名", "[{artist}] {title}"),
]

# 渲染结果 basename 上限（不含扩展名，预留路径长度）
MAX_BASENAME = 120

_TRIM_EDGE_RE = re.compile(r"^[\s\-_.·]+|[\s\-_.]+$")
_MULTI_SPACE_RE = re.compile(r" {2,}")


def validate_template(tpl: str) -> tuple[bool, str, list[str]]:
    """校验模板合法性。

    返回 (是否合法, 错误信息, 使用到的变量列表)；合法时错误信息为空串。
    """
    text = (tpl or "").strip()
    if not text:
        return False, "模板不能为空", []

    if "\n" in tpl or "\r" in tpl or "\t" in tpl:
        return False, "模板不能包含换行或制表符", []

    illegal = sorted({m.group(0) for m in _ILLEGAL_IN_TEMPLATE_RE.finditer(tpl)})
    if illegal:
        disp = "、".join(repr(c) for c in illegal)
        return False, f"包含文件名非法字符: {disp}（字符会被系统拒绝或清理）", []

    empty_vars = _EMPTY_VAR_RE.findall(tpl)
    if empty_vars:
        return False, "存在空的占位符 {}，请填写变量名", []

    # 剥离合法 token 后残留花括号 → 未闭合 / 多余 / 嵌套错误
    residue_before = _VAR_RE.sub("", tpl)
    if "{" in residue_before or "}" in residue_before:
        return False, "花括号不匹配（存在未闭合的 '{' 或多余的 '}'）", []

    used = _VAR_RE.findall(tpl)
    unknown = sorted({v for v in used if v not in VARIABLES})
    if unknown:
        bad = "} {".join(unknown)
        known = "、".join(f"{{{v}}}" for v in VARIABLES)
        return False, f"未知变量: {{{bad}}}（可用: {known}）", []

    # 无占位符且字面部分全为分隔符 → 冲突规则（渲染必为空或纯符号）
    residue = residue_before.strip()
    if not used and not residue.strip(" -_·[]()《》"):
        return False, "模板不含任何有效内容（无占位符且无有效文字）", []
    return True, "", used


def render_name(tpl: str, meta: dict, *, max_len: int = MAX_BASENAME) -> str:
    """按模板渲染文件名 basename（不含扩展名）。

    - 未知变量原样保留（校验阶段已拦截，此处兜底）
    - 缺失字段替换为空串，随后清理空段与多余分隔符
    - 渲染结果为空时回退 "artist - title"，再为空则回退 "untitled"
    """
    if not tpl or not tpl.strip():
        tpl = DEFAULT_TEMPLATE
    meta = meta or {}

    def _sub(m: re.Match) -> str:
        val = str(meta.get(m.group(1)) or "").strip()
        return val

    name = _VAR_RE.sub(_sub, tpl)
    name = safe_filename(name)                     # 去除系统非法字符
    name = _MULTI_SPACE_RE.sub(" ", name).strip()  # 折叠多余空格

    # 逐段丢弃空占位段：按 "-" 切分后过滤空段再拼接
    parts = [p.strip() for p in name.split("-")]
    parts = [p for p in parts if p]
    name = " - ".join(parts) if parts else ""

    name = _TRIM_EDGE_RE.sub("", name)
    if not name:
        fb = safe_filename(
            f"{meta.get('artist', '')} - {meta.get('title', '')}").strip(" -_")
        name = fb or "untitled"

    if len(name) > max_len:
        name = name[:max_len].rstrip(" ._-·")
    return name


def render_filename(tpl: str, meta: dict, ext: str, *,
                    max_len: int = MAX_BASENAME,
                    fallback: Optional[str] = None) -> str:
    """渲染完整文件名（含扩展名）。ext 带或不带点均可。

    fallback: 模板渲染失败（校验不通过）时的整名回退，如 "歌手 - 歌名"。
    """
    ext = ext.lower().lstrip(".")
    ok, _err, _used = validate_template(tpl or "")
    if not ok:
        base = safe_filename(fallback) if fallback else ""
        base = base or render_name(DEFAULT_TEMPLATE, meta)
    else:
        base = render_name(tpl, meta, max_len=max_len)
    return f"{base}.{ext}"


def sample_meta() -> dict:
    """设置页实时预览用的示例元数据。"""
    return {
        "title": "晴天",
        "artist": "周杰伦",
        "album": "叶惠美",
        "year": "2003",
        "source": "qq",
        "quality": "无损",
    }
