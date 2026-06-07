<div align="center">
  <h1>🎵 Py-Music-DL</h1>
  <p>
    <strong>Multi-platform Music Downloader</strong><br>
    纯 Python 实现 · 四平台聚合 · CLI + GUI 双模
  </p>
</div>


<p align="center">
  <img src="https://img.shields.io/badge/python-3.8+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License">
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-orange.svg" alt="Platform">
</p>

---

## ✨ 特性

- **四平台聚合搜索** — 同时搜索 咪咕音乐、网易云音乐、QQ音乐、酷我音乐，结果交错公平展示
- **CLI + GUI 双模** — 命令行极速操作，图形界面直观浏览，满足不同使用场景
- **音质自动识别** — 根据链接扩展名自动标注 320K 高品质 / LOSSLESS 无损
- **并发预取音质** — `ThreadPoolExecutor` 6 线程并行获取各平台音质信息，大幅缩短等待时间
- **搜索历史与筛选**（GUI） — 搜索历史自动保存、下拉补全；按歌手 / 平台实时筛选结果
- **流式下载** — 支持大文件分块下载，实时显示进度条与文件大小
- **多格式支持** — MP3 / FLAC / WAV / APE / M4A / OGG 自动识别
- **BeautifulSoup 教学** — 内置 BS4 实战演示模块，抓取并解析真实网页

## 📦 环境要求

| 依赖             | 最低版本           |
|----------------|----------------|
| Python         | 3.8+（推荐 3.10+） |
| requests       | 2.28+          |
| beautifulsoup4 | 4.11+          |
| lxml           | 4.9+           |
| urllib3        | 1.26+          |

## 🚀 快速开始

```bash
# 1. 克隆项目
git clone <repo-url> py-dl && cd py-dl

# 2. 安装依赖
pip install -r requirements.txt

# 3. 运行
python3 music.py       # CLI 模式
python3 music_gui.py   # GUI 模式
```

### CLI 模式

```
请输入要搜索的歌曲名：晴天

[*] 正在多平台搜索：晴天
    [→] 搜索 咪咕音乐...      找到 10 首
    [→] 搜索 网易云音乐...    找到 10 首
    [→] 搜索 QQ音乐...        找到 10 首
    [→] 搜索 酷我音乐...      找到 10 首
    [→] 预取音质信息（30 首）...

[✓] 共找到 40 首歌曲（已交错排列）

序号    歌曲名                    歌手          来源        音质
══════════════════════════════════════════════════════════
1      晴天                       周杰伦        咪咕音乐    320K
2      晴天                       周杰伦        网易云      LOSSLESS
...

请输入要下载的歌曲序号（输入 0 退出）：2
[*] 下载进度: [████████████████████████] 100.0%
[✓] 下载完成！保存位置：downloaded_music/周杰伦 - 晴天.flac
```

### GUI 模式

```
python3 music_gui.py
```

- 搜索框支持历史记录下拉补全
- 双击或选中后点击「下载选中歌曲」
- 支持按歌手 / 平台筛选结果
- 日志面板实时显示下载状态

## 🎯 支持平台

| 平台    |  搜索   |  下载   | 音质              |
|-------|:-----:|:-----:|-----------------|
| 咪咕音乐  |   ✅   |   ✅   | 320K / LOSSLESS |
| 网易云音乐 |   ✅   |   ✅   | 320K / LOSSLESS |
| QQ音乐  |   ✅   |   ✅   | 320K / LOSSLESS |
| 酷我音乐  |   ✅   |   ✅   | 320K / LOSSLESS |

## 📁 项目结构

```
py-dl/
├── music.py                # CLI 主程序
│   ├── MusicAPI            #   四平台搜索 & 详情 API
│   ├── MusicDownloader     #   下载流程管理器
│   └── BS4Demo             #   BeautifulSoup 教学演示
├── music_gui.py            # Tkinter GUI 程序
│   ├── MusicDownloaderGUI  #   图形界面主类
│   └── SearchHistory       #   搜索历史管理
├── downloaded_music/       # 下载文件保存目录
├── requirements.txt        # 依赖清单
└── README.md
```

## ⚙️ 自定义

可在 `music.py` 顶部修改配置常量：

```python
HEADERS = { ... }          # HTTP 请求头
DOWNLOAD_DIR = "downloaded_music"  # 下载保存目录
TIMEOUT = 15               # 请求超时（秒）
```

GUI 模式下可在界面中直接切换下载目录。

## 📝 更新日志

### v1.0
- 四平台聚合搜索与下载
- 并发音质预取，6 线程并行
- Tkinter GUI 界面，搜索历史 & 筛选
- BeautifulSoup 教学演示模块

## 📄 开源协议

[MIT License](LICENSE)

---

<p align="center">
  <sub>Made with ❤️ for learning purposes</sub>
</p>
