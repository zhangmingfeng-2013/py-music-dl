<div align="center">
  <h1>🎵 Py-Music-DL</h1>
  <p>
    <strong>Multi-platform Music Downloader</strong><br>
    纯 Python 实现 · 四平台聚合 · CLI + GUI 双模 · 液态玻璃界面 · 并发搜索 · 批量下载
  </p>
</div>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License">
  <img src="https://img.shields.io/badge/platform-MacOS%20%7C%20Linux%20%7C%20Windows-orange.svg" alt="Platform">
  <img src="https://img.shields.io/badge/version-3.2-brightgreen.svg" alt="Version">
</p>

---

## ✨ 项目概览

Py-Music-DL 是一个基于聚合音乐站 API 的多平台音乐搜索与下载工具，提供 **CLI 命令行**与 **GUI 图形界面**两种使用方式：

- **CLI（`cli.py`）** — 轻量交互式命令行，适合脚本化与服务器环境
- **GUI·PyQt6（`gui_qt.py`，推荐）** — 基于 pyglass-qt 的液态玻璃界面，对齐 Apple Liquid Glass 设计语言：真折射玻璃面板（Snell 透镜边缘、色散、Fresnel 反射、磨砂散射）、环境光背景、玻璃弹窗与控件动效
- **GUI·Tkinter（`gui.py`）** — 零额外 GUI 依赖的经典版本（v3.1 设计系统，三套可切换方案）

核心能力：

| 能力 | 说明 |
|------|------|
| 四平台并发搜索 | `ThreadPoolExecutor` 4 线程同时搜索 咪咕 / 网易云 / QQ音乐 / 酷我，耗时降至最慢平台 ~2 秒 |
| 公平交错展示 | 各平台结果轮流排列，避免单一平台占据前排 |
| 音质并发预取 | 6 线程并行获取音质信息，自动标注 320K / LOSSLESS |
| 批量下载 | 多选输入（`1,3,5-8` / `all`），队列顺序下载 |
| 断点续传 | HTTP `Range` 头实现，中断后自动从断点继续，2 次自动重试 |
| 任务队列 | 独立进度条 + 暂停 / 恢复 / 取消，单任务或批量可控 |
| 历史记录 | 搜索关键词与歌手历史持久化，下拉补全 |
| 多主题 | 3 套设计方案（Liquid / Mono / Aurora）× 自动 / 浅色 / 深色外观 |

## 🖥️ 三种运行形态

| 入口 | 形态 | 依赖 | 说明 |
|------|------|------|------|
| `cli.py` | 命令行 | 仅基础依赖 | 交互式搜索下载，`Ctrl+C` 优雅退出 |
| `gui_qt.py` | PyQt6 GUI | PyQt6 + pyglass + numpy | 液态玻璃界面（功能最全，推荐） |
| `gui.py` | Tkinter GUI | 仅标准库 | 经典界面，v3.1 设计系统 |

## 📦 环境要求

| 依赖 | 最低版本 | 用途 |
|------|----------|------|
| Python | 3.10+ | 运行环境 |
| requests | 2.28+ | HTTP 请求 |
| beautifulsoup4 | 4.11+ | 页面解析 |
| lxml | 4.9+ | 解析引擎 |
| urllib3 | 1.26+ | 连接管理 |
| PyQt6 | 6.5+ | 液态玻璃 GUI |
| pyglass | 0.1.0+ | 玻璃渲染引擎 |
| numpy | 1.26+ | 折射计算 |

> 仅使用 CLI 或 Tkinter GUI 时，PyQt6 / pyglass / numpy 仍需安装（`requirements.txt` 统一管理）；Tkinter 随 Python 标准库提供。

## 🚀 安装

```bash
# 1. 克隆项目
git clone https://gitee.com/zhangmf9773/py-music-dl.git && cd py-music-dl

# 2.（推荐）创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt
```

## 📖 使用指南

### 一键启动（GUI）

```bash
# macOS / Linux
./start.sh              # 默认启动 gui.py，自动检查环境与依赖
./start.sh --check      # 仅检查运行环境，不启动
./start.sh --demo       # 设计预览模式（演示数据，不写历史文件）
./start.sh -- --demo    # `--` 后参数透传给 gui.py
```

```bat
:: Windows 10 / 11（依赖 chcp 65001，不支持 Win7/8）
start.bat
start.bat --check
```

> 启动脚本默认拉起 Tkinter 版 `gui.py`；如需 PyQt6 液态玻璃界面，请直接运行 `python3 gui_qt.py`。

### GUI 模式

```bash
python3 gui_qt.py        # PyQt6 液态玻璃界面（推荐）
python3 gui_qt.py --demo # 设计预览模式
python3 gui.py           # Tkinter 经典界面
python3 gui.py --demo    # 设计预览模式
```

界面内操作：输入关键词搜索 → 结果列表按歌手 / 平台筛选 → `Ctrl/Shift+点击` 多选 → 一键加入下载队列（进度条实时刷新，支持暂停 / 恢复 / 取消）；可切换下载目录、设计方案（Liquid / Mono / Aurora）与外观（自动 / 浅色 / 深色），偏好自动持久化。

### CLI 模式

```bash
python3 cli.py
```

```
═────────────────────────────────────────────────────
           🎵  音乐下载器 v2.0  🎵
                多平台聚合
     支持：咪咕 | 网易云 | QQ音乐 | 酷我
═────────────────────────────────────────────────────

下载目录（回车默认 downloaded_music/）：
请输入要搜索的歌曲名：晴天

[✓] 共找到 40 首歌曲（已交错排列）

序号    歌曲名          歌手          来源        音质
1      晴天             周杰伦        咪咕音乐    320K
2      晴天             周杰伦        网易云音乐  LOSSLESS
...

请输入要下载的歌曲序号，多选用逗号分隔（如 1,3,5-8），输入 all 全选，输入 0 退出：1,3

  [↓] 周杰伦 - 晴天   [████████████████████] 100.0%

  下载完成：2 成功, 0 失败
  文件保存在: downloaded_music/
```

### 模块化调用

```python
from api import search_all_platforms, get_song_detail
from downloader import DownloadQueue

# 1. 并发搜索四平台
songs = search_all_platforms("晴天")
song = songs[0]

# 2. 获取下载链接
detail = get_song_detail(song)

# 3. 加入下载队列并后台启动
queue = DownloadQueue(directory="downloaded_music")
queue.add_task(
    title=detail["title"],
    artist=detail["artist"],
    audio_url=detail["audio_url"],
    quality=detail.get("quality", "?"),
    source=song.get("source", ""),
)
queue.start_async()
```

## ⚙️ 配置选项

### GUI 偏好（自动生成 `settings.json`）

```json
{
  "scheme": "liquid",
  "theme_mode": "dark"
}
```

- `scheme` — 设计方案：`liquid`（液态玻璃，默认）| `mono`（单色极简）| `aurora`（极光柔彩）
- `theme_mode` — 外观：`auto`（跟随系统，默认）| `light` | `dark`

`gui_qt.py` 与 `gui.py` 共用该文件；删除后下次启动恢复默认值。

### 代码常量

在对应文件顶部修改：

```python
# api.py
HEADERS = { ... }                          # HTTP 请求头
TIMEOUT = 10                               # 请求超时（秒）
MAX_WORKERS = 10                           # 并发线程数

# downloader.py
CHUNK_SIZE = 8192                          # 下载分块大小（字节）
DEFAULT_TIMEOUT = 60                       # 下载超时（秒）

# utils.py
DEFAULT_DOWNLOAD_DIR = "downloaded_music"  # 默认下载目录
```

### 运行数据文件（自动生成，可安全删除）

| 文件 | 内容 |
|------|------|
| `search_history.json` | 搜索关键词历史 |
| `artist_history.json` | 歌手历史记录 |
| `tip_records.json` | 打赏记录 |
| `settings.json` | 界面主题偏好 |
| `downloaded_music/` | 下载文件保存目录 |

## 🎯 支持平台

| 平台 | 搜索 | 下载 | 音质 |
|------|:----:|:----:|------|
| 咪咕音乐 | ✅ | ✅ | 320K / LOSSLESS |
| 网易云音乐 | ✅ | ✅ | 320K / LOSSLESS |
| QQ音乐 | ✅ | ✅ | 320K / LOSSLESS |
| 酷我音乐 | ✅ | ✅ | 320K / LOSSLESS |

## 📁 项目结构

```
py-music-dl/
├── api.py            # API 层 — 并发搜索 + 音质预取 + 详情获取
│   ├── search_all_platforms()   # 4 线程并发搜索
│   ├── prefetch_quality()       # 6 线程并发预取音质
│   └── _SEARCHERS / _DETAILERS  # 平台注册表（增删平台只需改字典）
├── downloader.py     # 下载引擎 — 队列调度 + 断点续传 + 进度回调
│   ├── DownloadTask  # 单任务状态机（7 种状态 + 暂停/取消事件）
│   └── DownloadQueue # 队列管理器（顺序下载、重试、回调通知）
├── cli.py            # CLI 入口 — 交互式命令行（v2.0）
├── gui_qt.py         # PyQt6 液态玻璃 GUI — pyglass 真折射渲染（推荐）
├── gui.py            # Tkinter GUI — v3.1 三方案设计系统
├── utils.py          # 工具模块 — 文件名清理、格式化、进度条、日志
├── music.py          # [v1.0 参考] 巨石版 CLI
├── music_gui.py      # [v1.0 参考] 旧版 GUI
├── start.sh          # 一键启动脚本（macOS / Linux）
├── start.bat         # 一键启动脚本（Windows 10 / 11）
├── LiquidGlassUI/    # Swift 原型参考实现（玻璃效果设计探索）
├── assets/           # 界面资源（打赏二维码）
├── settings.json     # GUI 主题偏好（自动生成）
├── downloaded_music/ # 默认下载目录
└── requirements.txt  # 依赖清单
```

## 🤝 参与贡献

欢迎提交 Issue 与 Pull Request：

1. **Fork** 本仓库到个人账号
2. **创建特性分支**：`git checkout -b feat/your-feature`
3. **开发并自测**：
   - 遵循 PEP 8，保持完整类型注解
   - 至少验证 `python3 cli.py` 与 `python3 gui_qt.py` 可正常启动、核心搜索下载流程无回归
4. **提交**：使用清晰的提交信息，推荐 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/) 风格（如 `feat:` / `fix:` / `docs:`）
5. **推送并发起 Pull Request** 至 `main` 分支，说明改动内容与测试情况

提交 Issue 时请附：操作系统与 Python 版本、复现步骤、控制台完整报错。

## 📝 更新日志

### v3.1
- **PyQt6 液态玻璃界面（`gui_qt.py`）** — pyglass 真折射玻璃面板（Snell 透镜、色散、Fresnel、磨砂散射）、环境光背景、玻璃控件与弹窗体系，功能与 Tkinter 版对齐
- **三套设计方案** — Liquid 液态玻璃 / Mono 单色极简 / Aurora 极光柔彩，× 自动 / 浅色 / 深色外观，偏好持久化
- **打赏支持** — GUI 内置开发者打赏弹窗
- **一键启动脚本** — `start.sh`（macOS/Linux）与 `start.bat`（Windows 10/11），含环境自检

### v2.1
- 歌手历史记录持久化、平台固定下拉列表、界面美化

### v2.0
- 并发搜索（4 线程）、批量下载、断点续传（`Range` + 2 次重试）
- GUI 全新设计：下载任务面板、队列管理、多选批量添加
- 代码模块化拆分 + 完整类型注解 + 统一 `logging`

### v1.0
- 四平台聚合搜索与下载，并发音质预取，Tkinter GUI

## 📄 开源协议

本项目基于 [MIT License](LICENSE) 开源。Copyright (c) 2026 CodeNuts

## 📮 联系方式

- **项目主页**：[gitee.com/zhangmf9773/py-music-dl](https://gitee.com/zhangmf9773/py-music-dl)
- **问题反馈**：[Gitee Issues](https://gitee.com/zhangmf9773/py-music-dl/issues)
- **功能建议 / 合作**：欢迎通过 Gitee Issues 或 Pull Request 联系
- **电话** ：[15123469773](tel:15123469773)
- **邮箱** ：[503175021@qq.com](mailto:503175021@qq.com)

---

## ⚠️ 免责声明

本项目仅供学习与研究交流使用，请勿用于商业用途。音乐作品的版权归各平台及权利方所有；因使用本项目产生的任何问题由使用者自行承担。

<p align="center">
  <sub>用心制作 ❤️ 仅用于学习用途</sub>
</p>
