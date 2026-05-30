# 音乐下载器打包说明

## 已创建的文件

### 配置文件
- `requirements.txt` - Python 依赖列表
- `setup.py` - macOS 打包配置（使用 cx_Freeze）
- `setup_windows.py` - Windows 打包配置（使用 cx_Freeze）
- `MusicDownloader.spec` - PyInstaller 配置文件（备用）

## macOS DMG 安装包

### 已生成
- **DMG 文件**：`dist/MusicDownloader.dmg`
- **应用目录**：`dist/MusicDownloader`

### 使用方法
1. 双击 `dist/MusicDownloader.dmg` 打开
2. 将 `MusicDownloader` 应用拖拽到 Applications 文件夹
3. 从 Launchpad 或 Applications 启动应用

## Windows EXE 安装包

### 构建步骤

1. **安装 Python 和依赖**
   ```bash
   # 确保已安装 Python 3.8+
   pip install cx_Freeze requests beautifulsoup4 lxml
   ```

2. **运行打包命令**
   ```bash
   python setup_windows.py bdist_msi
   ```

3. **生成的安装包**
   - MSI 安装包位于 `dist/MusicDownloader-1.0.win-amd64.msi`
   - 或使用 `python setup_windows.py build` 生成 EXE 文件

### 或者使用 PyInstaller（备选方案）

1. 安装 PyInstaller
   ```bash
   pip install pyinstaller
   ```

2. 打包命令
   ```bash
   pyinstaller --name MusicDownloader --onedir --windowed --noconfirm music_gui.py
   ```

3. 生成的文件位于 `dist/MusicDownloader/` 目录

## 跨平台打包说明

### 在 macOS 上构建
```bash
# 创建虚拟环境（推荐）
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install cx_Freeze requests beautifulsoup4 lxml

# 打包 macOS 应用
python setup.py build

# 创建 DMG（如果需要）
python setup.py bdist_dmg
```

### 在 Windows 上构建
```bash
# 创建虚拟环境
python -m venv venv
.\venv\Scripts\activate

# 安装依赖
pip install cx_Freeze requests beautifulsoup4 lxml

# 打包 Windows 应用
python setup_windows.py build

# 创建 MSI 安装包
python setup_windows.py bdist_msi
```

### 在 Linux 上构建
```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install cx_Freeze requests beautifulsoup4 lxml

# 打包 Linux 应用
python setup.py build
```

## 注意事项

1. **macOS 应用签名**
   - 如果要分发给其他用户，建议对应用进行代码签名
   - 使用 `codesign` 工具签名应用

2. **Windows 防病毒**
   - 首次运行 EXE 时，Windows 可能会警告
   - 可以选择"仍要运行"或对应用进行代码签名

3. **依赖项**
   - 确保所有依赖都包含在 `requirements.txt` 中
   - 打包时 cx_Freeze/PyInstaller 会自动检测并包含依赖

4. **Python 版本**
   - 推荐使用 Python 3.8 或更高版本
   - 避免使用过新的 Python 版本（可能存在兼容性问题）

## 故障排除

### macOS 权限问题
如果在 macOS 上遇到权限错误：
```bash
# 清理 PyInstaller 缓存
rm -rf ~/Library/Application\ Support/pyinstaller

# 重新打包
pyinstaller --name MusicDownloader --onedir --windowed --noconfirm music_gui.py
```

### Windows DLL 缺失
如果 Windows 上提示 DLL 缺失：
- 安装 Visual C++ Redistributable
- 或在 PyInstaller 命令中添加 `--add-binary` 参数

## 卸载说明

### macOS
1. 将 `MusicDownloader` 从 Applications 文件夹删除
2. 删除 `~/downloaded_music/` 目录（如果存在）

### Windows
1. 通过控制面板 > 程序和功能卸载
2. 或删除安装目录（默认 `C:\Program Files\MusicDownloader`）
3. 删除用户目录下的 `downloaded_music` 文件夹

## 技术支持

如有问题，请检查：
1. Python 版本是否兼容
2. 所有依赖是否正确安装
3. 是否有足够的磁盘空间
4. 是否有管理员/root 权限
