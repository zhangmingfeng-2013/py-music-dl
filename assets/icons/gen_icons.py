#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
应用图标资源生成器
==================
从唯一矢量源 app.svg 派生出全部平台图标，保证各尺寸视觉一致：

  PNG  16/24/32/48/64/128/256/512/1024  → icon_<size>.png（Linux 主题/界面/安装包）
  ICO  16/24/32/48/64/128/256            → app.ico（Windows 窗口/exe/安装程序）
  ICNS iconset（16~512 + @2x）           → app.icns（macOS .app）

用法：
  .venv/bin/python assets/icons/gen_icons.py
仅依赖 PyQt6.QtSvg（渲染）+ Pillow（合成 ICO）；ICNS 调用 macOS 自带 iconutil。
"""

from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SVG = os.path.join(HERE, "app.svg")

PNG_SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

# macOS iconset 文件名 -> PNG 像素边长
ICONSET = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}


def render_pngs() -> dict[int, str]:
    """用 Qt SVG 引擎逐尺寸矢量渲染，避免位图缩放失真。"""
    from PyQt6.QtCore import QByteArray, Qt
    from PyQt6.QtGui import QImage, QPainter
    from PyQt6.QtSvg import QSvgRenderer

    with open(SVG, "rb") as f:
        renderer = QSvgRenderer(QByteArray(f.read()))
    if not renderer.isValid():
        raise RuntimeError(f"SVG 无效或无法解析: {SVG}")

    paths: dict[int, str] = {}
    for size in PNG_SIZES:
        # 超采样：1024 以下尺寸先按 2x 渲染再平滑缩回，得到更锐利的边缘
        scale = 2 if size < 512 else 1
        big = QImage(size * scale, size * scale,
                     QImage.Format.Format_ARGB32_Premultiplied)
        big.fill(Qt.GlobalColor.transparent)
        p = QPainter(big)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        renderer.render(p)
        p.end()
        img = big.scaled(
            size, size,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        out = os.path.join(HERE, f"icon_{size}.png")
        img.save(out, "PNG")
        paths[size] = out
        print(f"  PNG  {size:>4}x{size:<4} -> {os.path.basename(out)}")
    return paths


def build_ico(paths: dict[int, str]) -> None:
    from PIL import Image

    ico = os.path.join(HERE, "app.ico")
    # 以 256 源图让 Pillow 生成全尺寸帧（含 PNG 压缩的 256 Vista 帧）
    src = Image.open(paths[256]).convert("RGBA")
    src.save(ico, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    print(f"  ICO  {ICO_SIZES} -> app.ico")


def build_icns() -> None:
    iconset = os.path.join(HERE, "app.iconset")
    os.makedirs(iconset, exist_ok=True)
    for name, size in ICONSET.items():
        src = os.path.join(HERE, f"icon_{size}.png")
        dst = os.path.join(iconset, name)
        with open(src, "rb") as fr, open(dst, "wb") as fw:
            fw.write(fr.read())
    icns = os.path.join(HERE, "app.icns")
    if os.path.exists(icns):
        os.remove(icns)
    r = subprocess.run(["iconutil", "-c", "icns", iconset, "-o", icns],
                       capture_output=True, text=True)
    if r.returncode != 0:
        # 非 macOS 环境：保留 iconset，给出明确提示（CI 在 macOS runner 执行）
        print(f"  ICNS iconutil 不可用，已保留 app.iconset：{r.stderr.strip()}")
        return
    print("  ICNS 16~1024(@2x) -> app.icns")


def main() -> int:
    if not os.path.exists(SVG):
        print(f"找不到矢量源: {SVG}", file=sys.stderr)
        return 1
    print(f"从 {os.path.basename(SVG)} 生成图标资源 …")
    paths = render_pngs()
    build_ico(paths)
    if sys.platform == "darwin":
        build_icns()
    else:
        print("  ICNS 跳过（仅 macOS 可生成，由 macOS CI 产出）")
    print("完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
