<div align="center">
  <h1>🎵 拾音 Py-Music-DL</h1>
  <p>
    <strong>Multi-platform Music Downloader</strong><br>
    纯 Python 实现 · 四平台聚合 · CLI + GUI 双模 · 液态玻璃界面 · 断点续传 · 音频后处理
  </p>
</div>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License">
  <img src="https://img.shields.io/badge/platform-MacOS%20%7C%20Linux%20%7C%20Windows-orange.svg" alt="Platform">
  <img src="https://img.shields.io/badge/version-3.2.0-brightgreen.svg" alt="Version">
</p>

---

## ✨ 项目介绍

拾音（Py-Music-DL）是一个基于聚合音乐 API 的多平台音乐搜索与下载工具，提供 **CLI 命令行**与 **GUI 图形界面**两种使用方式，覆盖搜索、筛选、试听、下载、转码、元数据写入的完整链路。

**使用场景**：本地音乐库建设、歌单批量归档、无会员平台的音质获取；CLI 适合脚本化与无桌面环境，GUI 适合日常交互式使用。

**主要特性**：

| 能力 | 说明 |
|---|---|
| 四平台并发搜索 | 4 线程同时搜索 咪咕 / 网易云 / QQ音乐 / 酷我，耗时降至最慢平台 ~2 秒 |
| 音质 / 版本筛选 | 结果列表含音质列（标准 / 高清 / 无损 / 未知）与版本列；可按 全部 / 标准及以上 / 高清及以上 / 仅无损 过滤 |
| 版本风险识别 | 自动识别伴奏（红色 ⚠，拦截试听与下载）与翻唱 / 现场 / Remix（黄色提示），用户主动搜索"伴奏"时不拦截 |
| 后台音质预取 | 搜索后 4 线程并行获取详情回填音质与版本，不阻塞界面 |
| 批量下载 | 多选输入（`1,3,5-8` / `all` / `Ctrl·Shift+点击`），队列顺序下载 |
| 断点续传 | HTTP `Range` 头实现，中断自动续传，2 次自动重试 |
| 任务队列 | 独立进度条 + 暂停 / 恢复 / 取消；任务行显示 进度·速度·已下/总大小，面板头部实时汇总总速度 |
| 双重限速 | 单任务与全局总带宽独立限速（KB/s，0 = 不限速），令牌桶实现，动态生效 |
| 内置试听 | 迷你播放条（QMediaPlayer）：播放 / 暂停 / 停止 / 进度拖拽，点击"试听"后台取流播放 |
| 音频后处理 | ffmpeg 转码（MP3 128/192/320 kbps / FLAC），成功后自动删除源文件 |
| 元数据补全 | MP3 写 ID3v2.3（标题 / 歌手 / 专辑 / 年份 / 封面 / 歌词），FLAC 写 Vorbis Comment + Picture |
| 歌词获取 | 平台直取 LRC → 网易云 ID → 网易云模糊搜索 → lrclib 四级兜底；可存同名 `.lrc` 或内嵌音频标签，歌词窗口支持 LRC / 纯文本切换预览 |
| Whisper 歌词兜底 | 所有检索均失败且音频已下载时，本地 faster-whisper 语音识别生成带时间轴的 LRC 歌词 |
| 音频指纹识歌 | 基于 Shazam 协议（shazamio，免 Key），支持主流格式；多窗口采样 + 命中偏移校验 + 多窗口共识投票，误报率大幅下降，中文歌名 / 歌手本地化 |
| 自定义命名模板 | `{title}` `{artist}` `{album}` `{year}` `{source}` `{quality}` 六变量占位，预设快捷选择、实时预览、语法高亮、导入导出，异常三级回退不阻塞下载 |
| 历史记录 | 搜索关键词与歌手历史持久化，下拉补全 |
| 多主题 | 3 套设计方案（Liquid / Mono / Aurora）× 自动 / 浅色 / 深色外观，偏好自动持久化 |

## 🖥️ 运行形态

| 入口 | 形态 | 依赖 | 说明 |
|---|---|---|---|
| `gui_qt.py` | PyQt6 GUI | PyQt6 + pyglass-qt + numpy | **液态玻璃界面（推荐）**，功能最全：真折射玻璃面板（Snell 透镜、色散、Fresnel 反射、磨砂散射）、环境光背景、玻璃弹窗与控件动效 |
| `gui.py` | Tkinter GUI | 仅标准库 GUI 层 | 经典零依赖版本（v3.1 设计系统，三套可切换方案） |
| `cli.py` | 命令行 | 基础依赖 | 交互式搜索下载，`Ctrl+C` 优雅退出 |
| `installer/` | 安装包构建 | PyInstaller | macOS `.pkg` / Windows `.exe`(Inno Setup) / Linux `.deb` 三平台打包脚本 |

## 📦 环境要求

| 依赖 | 最低版本 | 用途 |
|---|---|---|
| Python | 3.10+ | 运行环境（3.13+ 自动装 `audioop-lts`；3.14 见下方注意事项） |
| requests | 2.28+ | HTTP 请求 |
| beautifulsoup4 / lxml | 4.11+ / 4.9+ | 页面解析 |
| urllib3 | 1.26+ | 连接管理 |
| PyQt6 | 6.5+ | 液态玻璃 GUI |
| pyglass-qt | 0.1.0+ | 玻璃渲染引擎 |
| numpy | 1.26+ | 折射计算（线程池异步执行，不阻塞 UI） |
| mutagen | 1.46+ | 音频元数据 / 歌词内嵌 |
| faster-whisper | 1.0+ | Whisper 歌词兜底（首次使用自动下载 base 模型约 140MB） |
| shazamio | 0.5+ | 音频指纹识歌 |
| pyobjc-framework-Cocoa | 9.0+ | 仅 macOS：注入应用身份（Dock / 菜单栏名称） |

**可选系统依赖 — ffmpeg**：音频转码（MP3 / FLAC）与识歌预处理需要。不安装不影响搜索下载，仅转码相关功能自动禁用，GUI 设置弹窗会提示检测状态。

```bash
brew install ffmpeg          # macOS
sudo apt install ffmpeg      # Debian / Ubuntu
# Windows: 下载静态构建并加入 PATH
```

## 🚀 快速开始

```bash
# 1. 克隆项目
git clone https://gitee.com/zhangmf9773/py-music-dl.git && cd py-music-dl

# 2.（推荐）创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 启动
python3 gui_qt.py                # PyQt6 液态玻璃界面（推荐）
```

> **Python 3.14 注意事项**：`shazamio-core` 官方 wheel 在 3.14 下导入即段错误，需源码编译替换：
> ```bash
> pip install --no-binary :all: --force-reinstall shazamio-core==2.0.0
> ```
> （shazamio 声明锁定 1.1.2，实测与 2.0.0 API 兼容，仅 pip 版本告警，可忽略）

## 📖 使用指南

### 一键启动脚本

```bash
# macOS / Linux（默认启动 Tkinter 版 gui.py，自动检查环境与依赖）
./start.sh              # 启动 GUI
./start.sh --check      # 仅检查 Python / Tkinter / 依赖
./start.sh --demo       # 设计预览模式（演示数据，不写历史文件）
./start.sh -- --demo    # `--` 后参数透传给 gui.py
```

```bat
:: Windows 10 / 11（依赖 chcp 65001，不支持 Win7/8）
start.bat
start.bat --check
```

> 需要 PyQt6 液态玻璃界面请直接运行 `python3 gui_qt.py`。

### GUI 核心流程

1. **搜索**：输入关键词回车，四平台并发检索，结果按平台交错展示；状态栏实时显示筛选条件（如 `筛选结果: 32 首（平台=QQ音乐 · 音质≥高清）`）
2. **筛选**：按歌手 / 平台 / 音质 / 版本过滤；搜索后音质与版本信息由后台线程预取回填
3. **试听**：选中歌曲点击「试听」，底部迷你播放条后台取流播放，支持播放 / 暂停 / 停止 / 进度拖拽
4. **下载**：`Ctrl/Shift+点击` 多选 → 加入下载队列；任务行显示 `进度% · 速度 · 已下/总大小`，支持暂停 / 恢复 / 取消；同名文件冲突可选 覆盖 / 跳过 / 重命名
5. **设置**：顶栏齿轮按钮打开设置弹窗——单任务 / 全局限速、转码格式与码率、元数据 / 封面 / 歌词开关、Whisper 兜底开关、命名模板编辑（实时预览 + 语法高亮 + 导入导出），全部即时生效并持久化
6. **识歌**：工具栏「识歌」选择本地音频文件，多窗口指纹识别返回歌名 / 歌手 / 专辑 / 封面，并标注置信度（多窗口一致 / 单窗口命中）
7. **歌词**：工具栏「歌词」弹出预览窗，一键切换 LRC / 纯文本

### CLI 模式

```bash
python3 cli.py
```

```
═────────────────────────────────────────────────────
           🎵  音乐下载器  🎵
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

### 模块化调用（API 概览）

| 模块 | 关键接口 | 说明 |
|---|---|---|
| `api.py` | `search_all_platforms(keyword)` | 4 线程并发搜索，返回交错结果列表 |
| | `prefetch_quality(songs)` | 并发预取音质信息 |
| | `get_song_detail(song)` | 解析真实下载链接与音质 |
| | `fetch_lyrics(...)` / `detect_version_risk(...)` | 歌词四级兜底 / 伴奏·翻唱识别 |
| `downloader.py` | `DownloadQueue` / `DownloadTask` | 队列调度 + 断点续传 + 令牌桶限速 + 暂停/取消事件 |
| `naming.py` | `validate_template(tpl)` / `render_name(tpl, meta)` | 命名模板校验与渲染（三级异常回退） |
| `media.py` | `ffmpeg_available()` / `PostOptions` / `post_process` | 转码、歌词落盘、MP3/FLAC 标签后处理 |
| `ffmpeg.py` | `resolve_tool()` / `extract_pcm_wav()` | ffmpeg 定位、平台魔数校验、统一调用与临时 WAV 提取 |
| `transcribe.py` | Whisper 歌词转写 | faster-whisper 本地识别，句末标点拆分 + 时间插值输出 LRC |
| `recognize.py` | 音频指纹识歌 | shazamio，多窗口 12s 采样 + 偏移校验 + 共识投票，中文元数据，20 秒总预算 |
| `config.py` | `load_settings()` / `SearchHistory` / `TipRecordStore` | 设置、历史、打赏记录的统一持久化（原子写入；设置写入去抖） |
| `theme.py` | `SCHEMES` / `Palette` / `palette_for()` | 三套配色与模式解析；系统深浅色探测带缓存 + 后台监视，Tkinter / Qt 共用 |
| `utils.py` | `quality_tier` / `safe_filename` / `format_size` | 音质档位、文件名清理、格式化、JSON 读写工具 |

```python
from api import search_all_platforms, get_song_detail
from downloader import DownloadQueue

songs = search_all_platforms("晴天")          # 1. 并发搜索
detail = get_song_detail(songs[0])            # 2. 解析下载链接

queue = DownloadQueue(directory="downloaded_music")
queue.add_task(title=detail["title"], artist=detail["artist"],
               audio_url=detail["audio_url"], quality=detail.get("quality", "?"))
queue.start_async()                            # 3. 后台队列下载
```

## ⚙️ 配置说明

### GUI 偏好（`settings.json`，启动时自动创建）

```json
{
  "scheme": "liquid",
  "theme_mode": "auto",
  "download_dir": "",
  "per_task_speed": 0,
  "global_speed": 0,
  "convert_mode": "off",
  "mp3_bitrate": 320,
  "write_tags": true,
  "embed_cover": true,
  "save_lrc": true,
  "embed_lyrics": true,
  "whisper_fallback": true,
  "naming_template": "{artist} - {title}"
}
```

| 键 | 取值 | 说明 |
|---|---|---|
| `scheme` | `liquid` / `mono` / `aurora` | 设计方案 |
| `theme_mode` | `auto` / `light` / `dark` | 外观模式 |
| `download_dir` | 路径字符串，空 = 平台默认 | 下载目录（Qt 版设置弹窗保存后持久化） |
| `per_task_speed` / `global_speed` | KB/s，0 = 不限速 | 单任务 / 全局总带宽限速 |
| `convert_mode` / `mp3_bitrate` | `off`/`mp3`/`flac` · `128`/`192`/`320` | 下载后转码 |
| `write_tags` / `embed_cover` | bool | 元数据与封面写入 |
| `save_lrc` / `embed_lyrics` | bool | 独立 `.lrc` 文件 / 内嵌歌词 |
| `whisper_fallback` | bool | 歌词检索失败时 Whisper 兜底 |
| `naming_template` | 含 6 个占位符的模板串 | 非法模板自动回退默认值 |

`gui_qt.py` 与 `gui.py` 共用该文件；删除后下次启动恢复默认值。打包运行时配置写入系统标准配置目录（macOS `~/Library/Application Support`）。

### 运行数据文件（自动生成，可安全删除）

| 文件 | 内容 |
|---|---|
| `search_history.json` | 搜索关键词历史 |
| `artist_history.json` | 歌手历史记录 |
| `tip_records.json` | 打赏记录（仅本地） |
| `downloaded_music/` | 默认下载目录 |

### 代码常量

在对应文件顶部修改：`api.py`（`HEADERS` / `TIMEOUT` / `MAX_WORKERS`）、`downloader.py`（`CHUNK_SIZE` / `DEFAULT_TIMEOUT` / `IDLE_TIMEOUT`）、`utils.py`（`DEFAULT_DOWNLOAD_DIR` / `USER_AGENT`）、`ffmpeg.py`（二进制候选路径）。

## 🎯 支持平台

| 平台 | 搜索 | 下载 | 音质 |
|---|:---:|:---:|---|
| 咪咕音乐 | ✅ | ✅ | 320K / LOSSLESS |
| 网易云音乐 | ✅ | ✅ | 320K / LOSSLESS |
| QQ音乐 | ✅ | ✅ | 320K / LOSSLESS |
| 酷我音乐 | ✅ | ✅ | 320K / LOSSLESS |

## 📁 项目结构

```
py-music-dl/
├── gui_qt.py         # PyQt6 液态玻璃 GUI（推荐）— pyglass 真折射渲染
├── gui.py            # Tkinter GUI — v3.1 三方案设计系统（复用 config/theme）
├── cli.py            # CLI 入口 — 交互式命令行
├── api.py            # API 层 — 并发搜索 / 音质预取 / 详情 / 歌词 / 版本识别
├── downloader.py     # 下载引擎 — 队列调度 / 断点续传 / 令牌桶限速
├── naming.py         # 自定义文件命名模板 — 校验 / 渲染 / 三级回退
├── media.py          # 音频后处理 — 转码 / 歌词 / 元数据 / 封面
├── ffmpeg.py         # ffmpeg 定位与安全调用 — 平台魔数 / WAV 提取
├── transcribe.py     # Whisper 歌词兜底 — faster-whisper 本地转写
├── recognize.py      # 音频指纹识歌 — shazamio
├── config.py         # 配置与本地记录 — 设置 / 历史 / 打赏（原子写入）
├── theme.py          # 设计系统 — 三套配色 / 色彩工具 / 深浅色探测
├── utils.py          # 工具模块 — 文件名清理 / 格式化 / 路径解析 / JSON
├── music.py          # [v1.0 参考] 早期单体版 CLI（不再维护）
├── music_gui.py      # [v1.0 参考] 旧版 GUI（不再维护）
├── tests/            # pytest 单元 / 集成测试（214 个用例）
├── REFACTORING.md    # 本次代码质量重构的变更说明
├── start.sh / start.bat   # 一键启动脚本（macOS·Linux / Windows）
├── installer/        # 打包脚本：macOS .pkg / Windows .exe / Linux .deb
│   ├── build_macos.sh · build_windows.ps1 · build_linux.sh
│   └── bin/          # 随包 ffmpeg 静态构建（按平台校验魔数）
├── assets/           # 界面资源（图标、打赏二维码）
├── settings.json     # GUI 偏好（自动生成）
├── downloaded_music/ # 默认下载目录
├── requirements.txt  # 运行依赖清单
└── requirements-dev.txt  # 测试依赖（pytest）
```

## 🧪 测试

```bash
# 安装测试依赖（运行时依赖见 requirements.txt）
pip install -r requirements-dev.txt

# 全量单元 + 集成测试
python3 -m pytest tests -q

# 仅核心逻辑（不依赖网络与 GUI）
python3 -m pytest tests/test_utils.py tests/test_naming.py tests/test_api.py \
                 tests/test_downloader.py tests/test_media.py -q
```

测试覆盖下载引擎（本地 HTTP 服务模拟 Range / 断线 / 200 回退）、四平台
响应解析、歌词四级兜底、命名模板、标签写入、配置持久化、CLI 输入与
双 GUI 导入边界。重构范围与缺陷修复清单见 [REFACTORING.md](REFACTORING.md)。

## ❓ 常见问题

**Q：GUI 启动崩溃 `Could not find the Qt platform plugin "cocoa"`？**
A：macOS BSD 隐藏标志导致 Qt 扫描不到插件目录。新版已内置启动自愈；手动修复：`chflags -R nohidden .venv`。

**Q：设置弹窗显示 ffmpeg 未检测到，但系统已安装？**
A：若从源码运行且项目内含 `installer/bin/ffmpeg`（Linux ELF 构建），程序会按二进制魔数校验自动跳过并回退到系统 PATH。确认 `ffmpeg -version` 可用；Windows/Linux 需将 ffmpeg 加入 PATH。

**Q：Python 3.14 下识歌功能导入崩溃？**
A：`shazamio-core` 官方 wheel 不兼容 3.14，按[快速开始](#-快速开始)中的源码编译命令替换 2.0.0 版本。

**Q：Whisper 兜底第一次特别慢？**
A：首次使用需下载 base 模型（约 140MB），之后本地推理无需网络。识别仅在歌词四级检索全部失败且音频已下载时触发。

**Q：搜索结果里音质显示"未知"？**
A：音质由后台线程预取详情回填，刚出结果时短暂为未知；部分平台不提供无损音质标注。选中具体音质档位时，未知音源会被自动隐藏。

**Q：伴奏 / 翻唱歌曲被拦截？**
A：高置信伴奏会阻止试听与下载（红色 ⚠）；翻唱 / 现场 / Remix 仅黄色提示。若想获取伴奏，直接在搜索词中包含"伴奏"即可解除拦截。

**Q：如何重置所有偏好？**
A：删除 `settings.json` 及三个历史 JSON 文件，重启即恢复默认。

## 📦 打包与安装

```bash
cd installer
./build_macos.sh          # macOS .pkg（产物 dist/）
./build_linux.sh          # Linux .deb（shiyin_<ver>-1_<arch>.deb，装至 /opt/shiyin）
powershell build_windows.ps1   # Windows（PyInstaller + Inno Setup）
```

打包版将 ffmpeg 静态构建置于包内 `bin/`，运行时优先使用且仅接受与宿主平台魔数匹配的二进制；配置与历史文件写入系统标准配置目录，下载目录固定为用户 `Downloads/shiyin`。

## 🤝 参与贡献

欢迎提交 Issue 与 Pull Request：

1. **Fork** 本仓库到个人账号
2. **创建特性分支**：`git checkout -b feat/your-feature`
3. **开发并自测**：遵循 PEP 8，保持完整类型注解；运行 `python3 -m pytest tests -q`，并至少验证 `python3 cli.py` 与 `python3 gui_qt.py` 正常启动、核心搜索下载流程无回归
4. **提交**：推荐 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/) 风格（`feat:` / `fix:` / `docs:`）
5. **推送并发起 Pull Request** 至 `main` 分支，说明改动内容与测试情况

提交 Issue 请附：操作系统与 Python 版本、复现步骤、控制台完整报错。

## 📝 更新日志

### v3.2.0
- **音频后处理链路** — ffmpeg 转码（MP3/FLAC）、ID3 / Vorbis 元数据与封面歌词写入、四级歌词兜底
- **自定义文件命名模板** — 6 变量占位、实时预览、语法高亮、导入导出、异常三级回退
- **Whisper 歌词兜底** — 检索失败时本地 faster-whisper 转写生成带时间轴 LRC
- **音频指纹识歌** — shazamio 免 Key 识别本地音频，多窗口采样 + 偏移校验 + 共识投票抑制误报，返回完整元数据
- **版本风险识别** — 伴奏拦截 + 翻唱/现场/Remix 提示，结果列表新增版本列
- **双重限速与任务面板增强** — 令牌桶单任务/全局限速，任务行实时速度·进度，面板总速度汇总
- **内置试听播放条** — QMediaPlayer 迷你播放，进度拖拽
- **设置弹窗** — 限速 / 转码 / 元数据 / 歌词 / 命名模板集中配置，即时生效并持久化
- **启动自愈** — Qt 插件 hidden 标志修复、macOS 应用身份注入、配置文件自动创建
- **三平台安装包** — macOS .pkg / Windows .exe / Linux .deb 构建脚本
- **修复** — ffmpeg 平台魔数校验（Linux ELF 误选）、网易云年份脏数据、搜索失败日志可观测性

### v3.1
- **PyQt6 液态玻璃界面（`gui_qt.py`）** — pyglass 真折射玻璃面板、环境光背景、玻璃控件与弹窗体系
- **三套设计方案** — Liquid / Mono / Aurora × 自动 / 浅色 / 深色外观
- **打赏支持**、**一键启动脚本**（含环境自检）

### v2.x
- 并发搜索（4 线程）、批量下载、断点续传、任务队列、历史记录、GUI 重设计、代码模块化

### v1.0
- 四平台聚合搜索与下载，并发音质预取，Tkinter GUI

## 📄 开源协议

本项目基于 [MIT License](LICENSE) 开源。Copyright (c) 2026 CodeNuts

## 📮 联系方式

- **项目主页**：[gitee.com/zhangmf9773/py-music-dl](https://gitee.com/zhangmf9773/py-music-dl)
- **邮箱**：[503175021@qq.com](mailto:503175021@qq.com)

---

## ⚠️ 免责声明

本项目仅供学习与研究交流使用，请勿用于商业用途。音乐作品的版权归各平台及权利方所有；因使用本项目产生的任何问题由使用者自行承担。

<p align="center">
  <sub>用心制作 ❤️ 仅用于学习用途</sub>
</p>
