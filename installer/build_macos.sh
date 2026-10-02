#!/usr/bin/env bash
# =============================================================================
# 音乐下载器 —— macOS .pkg 构建脚本
#
# 产物：dist/MusicDownloader-<version>-macos-<arch>.pkg
# 流程：生成图标 → PyInstaller 冻结为 .app → pkgbuild 组件包
#       → productbuild 标准安装引导 .pkg
#
# 可选：将静态 ffmpeg 二进制放到 installer/bin/ffmpeg，会自动随包打入。
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
VERSION="$(tr -d ' \n' < installer/VERSION)"
ARCH="$(uname -m)"
APP_NAME="MusicDownloader"
WORK="build/pkg"
OUT="dist/${APP_NAME}-${VERSION}-macos-${ARCH}.pkg"

PYTHON="${PYTHON:-python3}"

echo "==> [1/5] 生成图标资源（PNG/ICO/ICNS）"
QT_QPA_PLATFORM=offscreen "$PYTHON" assets/icons/gen_icons.py

echo "==> [2/5] PyInstaller 冻结 .app"
"$PYTHON" -m PyInstaller music-dl.spec --noconfirm

APP_BUNDLE="dist/${APP_NAME}.app"
[ -d "$APP_BUNDLE" ] || { echo "未找到 $APP_BUNDLE" >&2; exit 1; }

echo "==> [3/5] 清理扩展属性并临时签名（ad-hoc，保证 Gatekeeper 可启动）"
xattr -cr "$APP_BUNDLE" || true
codesign --force --deep --sign - "$APP_BUNDLE" 2>/dev/null || \
  echo "    ad-hoc 签名跳过（无需处理）"

echo "==> [4/5] 生成组件包（安装到 /Applications）"
rm -rf "$WORK"
mkdir -p "$WORK"
COMP_PKG="$WORK/MusicDownloader-component.pkg"
pkgbuild --component "$APP_BUNDLE" \
         --install-location /Applications \
         --identifier "com.musicdownloader.app" \
         --version "$VERSION" \
         "$COMP_PKG"

echo "==> [5/5] productbuild 组装安装引导包"
# 注入版本号到 Distribution.xml
sed "s/__VERSION__/${VERSION}/g" installer/macos/Distribution.xml > "$WORK/Distribution.xml"
mkdir -p "$WORK/resources"
cp installer/macos/welcome.txt installer/macos/license.txt "$WORK/resources/"
productbuild --distribution "$WORK/Distribution.xml" \
             --package-path "$WORK" \
             --resources "$WORK/resources" \
             "$OUT"

echo ""
echo "完成：$ROOT/$OUT"
ls -lh "$OUT"
