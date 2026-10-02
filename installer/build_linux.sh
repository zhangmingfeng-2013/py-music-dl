#!/usr/bin/env bash
# =============================================================================
# 音乐下载器 —— Linux .deb 构建脚本（Debian / Ubuntu）
#
# 产物：dist/music-downloader_<version>-1_<arch>.deb
# 安装布局：
#   /opt/music-downloader/            PyInstaller onedir 程序
#   /usr/bin/music-downloader         启动命令（符号链接）
#   /usr/share/applications/          桌面项
#   /usr/share/icons/hicolor/*/apps/  各尺寸图标
# 卸载：dpkg -r music-downloader（标准维护脚本自动刷新系统缓存）
#
# 可选：将静态 ffmpeg 二进制放到 installer/bin/ffmpeg，会自动随包打入；
#       否则 .deb 通过 Depends 声明 ffmpeg 系统依赖。
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
VERSION="$(tr -d ' \n' < installer/VERSION)"
APP_NAME="MusicDownloader"
PYTHON="${PYTHON:-python3}"

ARCH="$("${PYTHON:-python3}" - <<'PY'
import platform
m = platform.machine()
print({"x86_64": "amd64", "aarch64": "arm64", "armv7l": "armhf"}.get(m, m))
PY
)"

STAGE="build/deb/music-downloader_${VERSION}-1_${ARCH}"
OUT="dist/music-downloader_${VERSION}-1_${ARCH}.deb"

echo "==> [1/4] 生成图标并 PyInstaller 冻结"
QT_QPA_PLATFORM=offscreen "$PYTHON" assets/icons/gen_icons.py
"$PYTHON" -m PyInstaller music-dl.spec --noconfirm
[ -d "dist/${APP_NAME}" ] || { echo "未找到 dist/${APP_NAME}" >&2; exit 1; }

echo "==> [2/4] 编排 .deb 目录树"
rm -rf "$STAGE"
mkdir -p "$STAGE/opt/music-downloader" \
         "$STAGE/usr/bin" \
         "$STAGE/usr/share/applications" \
         "$STAGE/usr/share/icons/hicolor" \
         "$STAGE/DEBIAN"

cp -R "dist/${APP_NAME}/." "$STAGE/opt/music-downloader/"

# 启动命令
ln -s /opt/music-downloader/"$APP_NAME" "$STAGE/usr/bin/music-downloader"

# 桌面项
cp installer/linux/music-downloader.desktop "$STAGE/usr/share/applications/"

# 各尺寸图标（freedesktop hicolor 规范）
for SIZE in 16 24 32 48 64 128 256 512; do
    SRC="assets/icons/icon_${SIZE}.png"
    DIR="$STAGE/usr/share/icons/hicolor/${SIZE}x${SIZE}/apps"
    mkdir -p "$DIR"
    cp "$SRC" "$DIR/music-downloader.png"
done
cp assets/icons/icon_256.png "$STAGE/usr/share/icons/hicolor/256x256/apps/music-downloader.png" 2>/dev/null || true

echo "==> [3/4] 生成 control 与维护脚本"
INSTALLED_SIZE="$(du -sk "$STAGE" | cut -f1)"
sed -e "s/__VERSION__/${VERSION}/g" \
    -e "s/__ARCH__/${ARCH}/g" \
    -e "s/__INSTALLED_SIZE__/${INSTALLED_SIZE}/g" \
    installer/linux/control.tpl > "$STAGE/DEBIAN/control"
cp installer/linux/postinst installer/linux/postrm "$STAGE/DEBIAN/"
chmod 0755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm"

echo "==> [4/4] dpkg-deb 打包"
mkdir -p dist
# --root-owner-group 保证包内文件属主为 root:root
dpkg-deb --root-owner-group -Zgzip -b "$STAGE" "$OUT"

echo ""
echo "完成：$ROOT/$OUT"
ls -lh "$OUT"
echo ""
echo "安装：sudo apt install ./$(basename "$OUT")"
echo "卸载：sudo apt remove music-downloader"
