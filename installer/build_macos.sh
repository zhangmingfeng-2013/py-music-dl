#!/usr/bin/env bash
# =============================================================================
# 拾音 —— macOS .pkg 构建脚本
#
# 产物：dist/Shiyin-<version>-macos-<arch>.pkg
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
APP_NAME="Shiyin"
APP_DISPLAY_NAME="拾音"
WORK="build/pkg"
OUT="dist/${APP_NAME}-${VERSION}-macos-${ARCH}.pkg"

PYTHON="${PYTHON:-python3}"

echo "==> [1/5] 生成图标资源（PNG/ICO/ICNS）"
QT_QPA_PLATFORM=offscreen "$PYTHON" assets/icons/gen_icons.py

echo "==> [2/5] PyInstaller 冻结 .app"
"$PYTHON" -m PyInstaller music-dl.spec --noconfirm

APP_BUNDLE="dist/${APP_NAME}.app"
[ -d "$APP_BUNDLE" ] || { echo "未找到 $APP_BUNDLE" >&2; exit 1; }

echo "==> [3/5] 本地化显示名、清理扩展属性并临时签名（ad-hoc）"
# Finder/启动台按当前语言显示中文应用名（与微信等应用同机制）
RES_DIR="$APP_BUNDLE/Contents/Resources"
mkdir -p "$RES_DIR/zh-Hans.lproj" "$RES_DIR/en.lproj"
cat > "$RES_DIR/zh-Hans.lproj/InfoPlist.strings" <<EOF
"CFBundleDisplayName" = "${APP_DISPLAY_NAME}";
"CFBundleName" = "${APP_DISPLAY_NAME}";
EOF
cat > "$RES_DIR/en.lproj/InfoPlist.strings" <<EOF
"CFBundleDisplayName" = "${APP_NAME}";
"CFBundleName" = "${APP_NAME}";
EOF
xattr -cr "$APP_BUNDLE" || true
codesign --force --deep --sign - "$APP_BUNDLE" 2>/dev/null || \
  echo "    ad-hoc 签名跳过（无需处理）"

echo "==> [4/5] 生成组件包（安装到 /Applications）"
rm -rf "$WORK"
mkdir -p "$WORK"
COMP_PKG="$WORK/Shiyin-component.pkg"
pkgbuild --component "$APP_BUNDLE" \
         --install-location /Applications \
         --identifier "com.shiyin.app" \
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
