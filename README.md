<div align="center">
  <h1>🎵 Py-Music-DL</h1>
  <p>
    <strong>Multi-platform Music Downloader</strong><br>
    纯 Python 实现 · 四平台聚合 · CLI + GUI 双模 · 并发搜索 · 批量下载
  </p>
</div>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License">
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-orange.svg" alt="Platform">
  <img src="https://img.shields.io/badge/version-2.0-brightgreen.svg" alt="Version">
</p>

---

## ✨ 特性

### 搜索与发现
- **四平台并发搜索** — `ThreadPoolExecutor` 4 线程同时搜索 咪咕音乐、网易云音乐、QQ音乐、酷我音乐，耗时从串行 4-8 秒降至最慢平台 ~2 秒
- **公平交错展示** — 各平台结果轮流排列，避免单一平台占据前排
- **音质并发预取** — 6 线程并行获取各平台音质信息，自动标注 320K / LOSSLESS
- **多格式识别** — MP3 / FLAC / WAV / APE / M4A / OGG 自动检测

### 下载引擎
- **批量下载** — 支持多选（`1,3,5-8` / `all`），队列顺序下载
- **断点续传** — HTTP `Range` 头实现，中断后自动从断点继续
- **流式分块** — 8KB 分块写入，实时进度条，2 次自动重试
- **暂停/恢复/取消** — 单个任务或批量操作，下载中途可控

### GUI 界面（v2.0 全新）
- **下载任务面板** — 每个任务独立进度条 + 状态图标 + 暂停/恢复 + 取消按钮
- **队列管理** — 暂停全部、取消全部、清除已完成
- **多选批量下载** — Ctrl/Shift+点击多选，一键批量添加
- **搜索历史与筛选** — 历史自动保存/下拉补全；按歌手、平台实时筛选
- **状态栏 + 日志** — 实时反馈搜索/下载状态

### 代码质量
- **模块化架构** — `api.py` / `downloader.py` / `cli.py` / `gui.py` / `utils.py` 各司其职
- **完整类型注解** — `from __future__ import annotations` + 全量类型标注
- **统一日志** — `logging` 模块，CLI 输出到 stderr，GUI 输出到日志面板

## 📦 环境要求

| 依赖                | 最低版本      |
|-------------------|-----------|
| Python            | 3.10+     |
| requests          | 2.28+     |
| beautifulsoup4    | 4.11+     |
| lxml              | 4.9+      |
| urllib3           | 1.26+     |

## 🚀 快速开始

```bash
# 1. 克隆项目
git clone https://gitee.com/zhangmf9773/py-music-dl && cd py-music-dl

# 2. 安装依赖
pip install -r requirements.txt

# 3. 运行
python3 cli.py       # CLI 模式（v2.0，推荐）
python3 gui.py       # GUI 模式（v2.0）
```

### CLI 模式 — `python3 cli.py`

```
═────────────────────────────────────────────────────
           🎵  音乐下载器 v2.0  🎵
                多平台聚合
     支持：咪咕 | 网易云 | QQ音乐 | 酷我
═────────────────────────────────────────────────────
  新特性：并发搜索 · 批量下载 · 断点续传
═────────────────────────────────────────────────────

下载目录（回车默认 downloaded_music/）：

请输入要搜索的歌曲名：晴天

[✓] 共找到 40 首歌曲（已交错排列）

═─────────────────────────────────────────────────────────
序号    歌曲名                          歌手                来源          音质
═─────────────────────────────────────────────────────────
1      晴天                             周杰伦              咪咕音乐      320K
2      晴天                             周杰伦              网易云音乐    LOSSLESS
3      晴天                             周杰伦              QQ音乐       320K
4      晴天                             周杰伦              酷我音乐      320K
...

请输入要下载的歌曲序号，多选用逗号分隔（如 1,3,5-8），输入 all 全选，输入 0 退出：1,3

[*] 已选择 2 首歌曲，开始获取下载链接...
[*] 开始下载 2 首...

  [↓] 周杰伦 - 晴天                    [████████████████████] 100.0%
  [↓] 周杰伦 - 晴天                    [████████████████████] 100.0%

═────────────────────────────────────────────────────
  下载完成：2 成功, 0 失败
  文件保存在: downloaded_music/
═────────────────────────────────────────────────────
```

## 🎯 支持平台

| 平台        |   搜索    |   下载    | 音质                 |
|-----------|:-------:|:-------:|--------------------|
| 咪咕音乐      |    ✅    |    ✅    | 320K / LOSSLESS    |
| 网易云音乐     |    ✅    |    ✅    | 320K / LOSSLESS    |
| QQ音乐      |    ✅    |    ✅    | 320K / LOSSLESS    |
| 酷我音乐      |    ✅    |    ✅    | 320K / LOSSLESS    |

## 📁 项目结构

```
py-music-dl/
├── api.py                       # API 层 — 并发搜索 + 音质预取 + 详情获取
│   ├── search_all_platforms()   # ThreadPoolExecutor 4线程并发搜索
│   ├── prefetch_quality()       # 6线程并发预取音质
│   ├── get_song_detail()        # 获取歌曲下载链接
│   └── _SEARCHERS / _DETAILERS  # 平台注册表（增删平台只需改字典）
├── downloader.py                # 下载引擎 — 队列调度 + 断点续传 + 进度回调
│   ├── DownloadTask             # 单任务状态机（7 种状态 + 暂停/取消事件）
│   └── DownloadQueue            # 队列管理器（顺序下载、重试、回调通知）
├── cli.py                       # CLI 入口 — 交互式命令行界面
│   ├── _display_table()         # 搜索结果表格渲染
│   ├── _multi_select()          # 多选解析（1,3,5-8 / all）
│   └── _print_progress()        # 实时进度条
├── gui.py                       # GUI 入口 — Tkinter 图形界面（v2.0 全新）
│   ├── SearchHistory            # 搜索历史持久化管理
│   ├── TaskRow                  # 任务面板行组件（进度条 + 控制按钮）
│   └── MusicDownloaderGUI       # 主界面类（完整布局 + 队列回调）
├── utils.py                     # 工具模块 — 格式化、日志、文件名校验
│   ├── safe_filename()          # 非法字符清理
│   ├── format_size()            # 字节 → 可读大小
│   ├── format_progress_bar()    # 文本进度条
│   ├── quality_from_url()       # URL → 音质推断
│   └── log                      # logging.Logger 实例
├── music.py                     # [v1.0 参考] 巨石版 CLI（含 BS4Demo）
├── music_gui.py                 # [v1.0 参考] 旧版 GUI
├── downloaded_music/            # 下载文件保存目录
├── search_history.json          # 搜索历史持久化文件
├── requirements.txt             # 依赖清单
└── README.md
```

## 🔧 自定义

**CLI / API / 下载引擎** — 在对应文件顶部修改常量：

```python
# api.py
HEADERS = { ... }          # HTTP 请求头
TIMEOUT = 10               # 请求超时（秒）
MAX_WORKERS = 10           # 并发线程数

# downloader.py
CHUNK_SIZE = 8192          # 下载分块大小
DEFAULT_TIMEOUT = 60       # 下载超时（秒）

# utils.py
DEFAULT_DOWNLOAD_DIR = "downloaded_music"  # 默认下载目录
```

**GUI** — 界面中直接切换下载目录，搜索历史自动持久化。

## 📝 更新日志

### v2.0
- **并发搜索** — `ThreadPoolExecutor` 4 线程并行搜索四平台，耗时降至 ~2 秒
- **批量下载** — CLI 多选输入（`1,3,5-8` / `all`），GUI 多选批量添加
- **断点续传** — HTTP `Range` 头实现，中断自动续传，2 次重试
- **GUI 全新设计** — 下载任务面板（独立进度条 + 暂停/取消）、队列管理按钮、设置面板
- **代码模块化** — 拆分 `api.py` / `downloader.py` / `cli.py` / `gui.py` / `utils.py`
- **完整类型注解** — `from __future__ import annotations` + 全量类型标注
- **统一日志** — `logging` 模块替代 `print()`
- **暂停修复** — 修正 `DownloadTask` 暂停事件语义，暂停/恢复可靠工作

### v1.0
- 四平台聚合搜索与下载
- 并发音质预取，6 线程并行
- Tkinter GUI 界面，搜索历史 & 筛选

## 📄 开源协议

[MIT License](LICENSE)

---

<p align="center">
  <sub>Made with ❤️ for learning purposes</sub>
</p>
