#!/bin/bash
# macOS 手动修复脚本
# 运行此脚本来修复 MusicDownloader 应用的 Python 库问题

set -e

APP_PATH="/Applications/MusicDownloader.app"
BACKUP_PATH="/Applications/MusicDownloader.app.backup"

echo "🔧 MusicDownloader 修复脚本"
echo "=========================="

# 1. 创建备份
if [ -d "$APP_PATH" ]; then
    echo "📦 创建应用备份..."
    cp -R "$APP_PATH" "$BACKUP_PATH"
fi

# 2. 复制 Python 库
echo "📁 复制 Python 库..."
mkdir -p "$APP_PATH/Contents/Resources/lib/python3.14"
cp -r /Library/Frameworks/Python.framework/Versions/3.14/lib/python3.14/* "$APP_PATH/Contents/Resources/lib/python3.14/" || true

# 3. 复制 Python framework
echo "🐍 复制 Python Framework..."
mkdir -p "$APP_PATH/Contents/MacOS"
if [ ! -f "$APP_PATH/Contents/MacOS/Python" ]; then
    cp /Library/Frameworks/Python.framework/Versions/3.14/Python "$APP_PATH/Contents/MacOS/Python"
fi

# 4. 设置权限
echo "🔐 设置执行权限..."
chmod +x "$APP_PATH/Contents/MacOS/Python"
chmod +x "$APP_PATH/Contents/MacOS/MusicDownloader"

# 5. 修复符号链接
echo "🔗 创建符号链接..."
cd "$APP_PATH/Contents/Resources/lib"
if [ ! -L "libpython3.14.dylib" ]; then
    ln -sf "/Applications/MusicDownloader.app/Contents/MacOS/Python" libpython3.14.dylib
fi

echo "✅ 修复完成！"
echo ""
echo "请尝试重新运行应用："
echo "open $APP_PATH"
echo ""
echo "如果仍有问题，备份位于："
echo "$BACKUP_PATH"
