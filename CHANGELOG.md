# 更新日志

## v3.2.0 — 拾音 · 全平台发行版

发布日期：2026-10-04

本版本正式启用品牌名 **拾音（Shiyin）**，首次提供 Windows / macOS / Linux 三平台开箱即用的安装包，并内置 ffmpeg 媒体工具链；同时新增音频后处理管线、下载限速与音质识别等能力。

### 新功能

- **品牌重塑**：应用正式命名为「拾音」，配套全新品牌图标系统
  - 矢量源 `app.svg` + 9 档 PNG（16–1024px）
  - Windows 多帧 `.ico`、macOS 全规格 `.icns`（含 Retina @2x）
  - 窗口标题栏、Dock / 任务栏、启动台、安装向导、快捷方式全链路统一显示
- **三平台安装包**
  - Windows：Inno Setup 6 安装向导（开始菜单 / 桌面快捷方式 / 标准卸载）
  - macOS：`.pkg` 标准安装引导（安装到 /Applications，ad-hoc 签名，Finder 显示中文名「拾音」）
  - Linux：`.deb`（/opt 程序 + /usr/bin 命令 + hicolor 全尺寸图标 + 桌面项）
  - GitHub Actions 三平台 CI，推送 `v*` 标签即自动出包
- **ffmpeg / ffprobe 随包内置**（6.0 静态构建）：转码功能开箱即用，无需用户另行安装
- **音频后处理管线**：下载后自动转码（MP3 128/192/320K、FLAC 无损）、ID3 标签写入、专辑封面嵌入、歌词写入
- **下载限速**：可配置下载速率上限
- **音质版本识别**：自动标注标准 / 高品质 / 无损音质档位
- **历史记录持久化**：搜索关键词与歌手历史本地存储、下拉补全
- **PyQt6 液态玻璃界面**：基于 pyglass-qt 的玻璃拟态 UI，多主题与浅色 / 深色外观

### 改进

- 打包后用户配置自动写入各平台标准目录（`%APPDATA%` / `Application Support` / `~/.config`），默认下载目录移至用户下载文件夹，避免安装目录只读问题
- 运行时按「包内二进制 → 系统 PATH」顺序定位 ffmpeg，路径解析兼容源码运行与冻结环境
- 优化下拉菜单布局，修复背景透明导致文字不可读的问题

### 修复

- 修复跨搜索筛选状态残留与歌手下拉关联错误
- 增加歌曲详情一致性护栏与搜索失败可观测日志
- 修复网易云音源年份信息解析问题
- 其他细节稳定性修复

### 移除

- 移除歌单导入与 CSV 导出功能（精简主流程）
- 移除界面中的「清空历史」按钮与菜单项

### 下载与安装

| 平台 | 产物 | 安装方式 |
|------|------|----------|
| macOS 12+（Apple 芯片） | `Shiyin-3.2.0-macos-arm64.pkg` | 双击安装，或 `sudo installer -pkg Shiyin-3.2.0-macos-arm64.pkg -target /` |
| Windows 10/11 x64 | `Shiyin-3.2.0-windows-x64-setup.exe` | 双击安装向导 |
| Linux（Debian/Ubuntu amd64） | `shiyin_3.2.0-1_amd64.deb` | `sudo apt install ./shiyin_3.2.0-1_amd64.deb` |

源码运行：

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python gui_qt.py
```

### 说明

- macOS 安装包为 ad-hoc 签名；首次打开如被 Gatekeeper 拦截，可在「系统设置 → 隐私与安全性」中允许
- 本软件仅供个人学习与合法下载已获授权的音乐内容，请遵守当地著作权法律法规
