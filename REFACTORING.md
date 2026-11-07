# 重构说明（v3.2 代码质量专项）

本文档记录本次重构的范围、结构变化、修复的缺陷与验证结果。重构目标是
**在不改变既有业务流程与用户可见功能的前提下**，提升代码质量、可读性、
可测试性与逻辑安全性。

## 1. 重构范围

| 层 | 模块 | 处理方式 |
|---|---|---|
| 基础工具 | `utils.py` | 重写：类型标注、输入防御、JSON 原子写入、音质归一化整理 |
| 命名模板 | `naming.py` | 重写：校验/渲染拆分、非字符串输入防御、行为保持 |
| 网络 API | `api.py` | 重写：统一响应类型校验、平台解析器拆分、歌词链路整理 |
| 下载引擎 | `downloader.py` | 重写：队列状态机、Range 续传、限速器、线程安全加固 |
| 媒体后处理 | `media.py` | 重写：转码/歌词/标签三段式管线、可选依赖容错 |
| 媒体工具 | `ffmpeg.py` | **新增**：ffmpeg 定位、魔数校验、统一调用与 WAV 提取 |
| Whisper | `transcribe.py` | 重构：模型单例加锁、LRC 生成整理、元信息标签修复 |
| 识歌 | `recognize.py` | 重构：Shazam 响应解析拆分、超时/清理逻辑整理 |
| CLI | `cli.py` | 重构：输入解析/展示/进度/入队拆分，主函数瘦身 |
| 配置与记录 | `config.py` | **新增**：设置、历史、打赏记录的统一持久化层 |
| 设计系统 | `theme.py` | **新增**：调色板与系统外观探测，供双 GUI 共用 |
| Tkinter GUI | `gui.py` | 删除已下沉的业务/主题代码，改为导入共享层；修复队列完成提示 |
| PyQt6 GUI | `gui_qt.py` | 解除对 `gui.py`（Tkinter）的依赖；统一任务状态判断 |
| 测试 | `tests/` | 恢复历史用例并扩展到 214 个用例 |

`music.py` / `music_gui.py` 是 README 标注的 v1.0 参考实现，不属于当前
运行入口，本次未做行为修改（避免破坏仍在使用旧入口的用户）。

## 2. 结构调整

### 2.1 新增共享层

重构前 `gui_qt.py` 通过 `from gui import ...` 复用设置、历史、打赏与主题
定义，导致 Qt 版在导入阶段隐式依赖 Tkinter。现在拆为两层：

```
config.py   设置 / 搜索历史 / 歌手历史 / 打赏记录 / 启动配置文件创建
theme.py    Palette / 三套配色 / 色彩混合 / 模式→调色板解析 / 系统深浅色探测（缓存 + 后台监视）
```

* `gui.py` 从这两个模块导入，并保留原有模块级名字（如 `gui.SCHEMES`、
  `gui.load_settings`），外部脚本无需修改；
* `gui_qt.py` 直接导入 `config` / `theme`，**不再导入 `gui` 或 `tkinter`**；
* 新增架构回归测试，在子进程中验证该依赖边界。

### 2.2 消除 ffmpeg 重复逻辑

`media.py`、`transcribe.py`、`recognize.py` 原先各自维护：

* 二进制候选路径与平台魔数校验；
* `subprocess.run` 调用与超时处理；
* 临时 WAV 生成、失败清理；
* 空输出文件判断。

统一收敛到 `ffmpeg.py`：

```
matches_host_platform() / resolve_bundled() / resolve_tool()
run_ffmpeg() / output_is_valid() / extract_pcm_wav()
```

`media` 继续导出 `ffmpeg_available`、`FFMPEG_BIN`、`_matches_host_platform`、
`_resolve_tool` 等旧名字，保持向后兼容。

### 2.3 拆分过长函数

| 原实现 | 现实现 |
|---|---|
| `DownloadQueue._process_task` 约 150 行，混合冲突处理/请求/重试/落盘/后处理 | `_resolve_file_conflict` / `_download_once` / `_resolve_download_range` / `_throttle` / `_finish_*` |
| `media.post_process` 单函数完成转码/歌词/标签 | `_convert_audio` / `_acquire_lyrics` / `_apply_tags` |
| `cli.main` 约 120 行，交互与展示耦合 | `parse_selection` / `_ProgressPrinter` / `_enqueue_details` / `_print_summary` |
| `api._detail_kuwo` 两段重复返回字典 | 统一构造返回值 + `_kuwo_detail_payload` |
| `naming.render_name` 内联替换/清理 | `_substitute` / `_normalize_segments` |

## 3. 修复的缺陷

以下问题均在重构过程中修复，并通过新增测试锁定。

### 3.1 下载安全（高）

1. **低速限速死循环**：令牌桶容量只有 1 秒额度，当单次 `chunk`（8 KiB）
   大于限速值（如 < 8 KB/s）时，令牌永远攒不够，下载线程永久阻塞。
   现按「最多 1 秒额度」切片消费，低限速可以正常完成。
2. **断点续传污染文件**：服务端忽略 `Range` 返回 200 时，旧实现仍以
   `ab` 模式追加，导致文件内容重复。现校验响应必须为 `206` 且
   `Content-Range` 起点与本地偏移一致，否则以 `wb` 完整重下。
3. **同名文件被追加**：无 UI 决策回调（CLI / 程序化调用）时，旧实现把
   已存在的完整文件当作「未下完」继续追加。现在默认跳过并标记取消，
   绝不修改未知内容的旧文件；GUI 仍提供覆盖 / 跳过 / 重命名三选一。
4. **Content-Range 崩溃**：`bytes 0-99/*`、畸形头、`Content-Range` 与
   本地偏移不一致等情况可能抛 `ValueError` 或写错文件；现已安全解析并
   自动回退完整下载。
5. **队列线程被单任务异常杀死**：未预期异常会让 `_run` 退出，后续任务
   永远停在 FETCHING。现在 `_process_safely` 兜底标记 FAILED 并继续。
6. **重复消费者**：`start_async` 可被重复调用产生两个线程同时抢任务；
   现在幂等，`start` 在已有后台线程时改为等待其结束。
7. **清理任务误删进行中任务**：`clear_completed` 原先只保留 PENDING，
   会移除正在下载/暂停的任务；现在保留所有非终态任务并重新定位索引。
8. **空响应标记成功**：0 字节响应现在标记失败（「下载内容为空」），
   避免留下空音频文件。

### 3.2 配置与持久化（高）

1. 设置文件改为**原子写入**（临时文件 + `os.replace` + `fsync`），
   崩溃/断电不再产生半截 JSON。
2. 历史与打赏记录统一走 `config.JsonHistoryStore` / `TipRecordStore`，
   去掉两份完全相同的 `SearchHistory` / `ArtistHistory` 实现。
3. 损坏的打赏记录继续采用「备份为 `.bak` 后重置」，保留现场。
4. 修复 `download_dir` 已写入 `settings.json` 但读取时被丢弃、导致
   下载目录无法持久化的问题。
5. 配置值统一校验：主题、方案、限速、码率、转码格式、布尔开关、
   命名模板非法值都会回退默认值，不再让脏配置影响启动。
6. `PostOptions.from_config` 对 `mp3_bitrate="abc"` 等脏值不再抛异常。

### 3.3 上游响应健壮性（中）

1. 咪咕 / 网易云 / QQ / 酷我搜索与详情：所有 `data`、列表元素均做类型
   校验，上游返回字符串、`None`、异构数组时不再触发
   `AttributeError` / `TypeError`。
2. 酷我详情 JSON 为数组时不再调用 `.get` 崩溃。
3. `_netease_extra` 缺失 `songs` / 非 dict 专辑时安全返回空值。
4. 歌词解析对 `result.songs` 非列表、条目非 dict 做防御。
5. 封面下载增加 8 MiB 上限，避免异常响应耗尽内存。

### 3.4 音频与转写（中）

1. 修复 Whisper 生成的 LRC **丢失 `[ti:]` / `[ar:]` 元信息**的回归
   （拆分 `_transcribe_once` 时参数未透传）。
2. Whisper 模型加载加锁，避免并发首次调用重复加载模型。
3. `_split_segment` 保持原有时间分配比例（标点计入前一分句长度）。
4. 转码/标签写入的异常继续被限制在后处理层，不影响已下载文件。

## 4. 行为兼容性说明

* 所有公开函数、类、常量与状态值保持不变；`TaskStatus` 新增的只是
  `is_running` / `is_terminal` / `is_pending` 只读属性。
* CLI 参数、交互提示、输出格式保持不变。
* 两套 GUI 的窗口结构、主题、设置项与交互保持不变。
* 唯一有意的行为修正：**同名文件在无回调时跳过**（此前会追加导致文件
  损坏）；这属于缺陷修复，不是新增功能。

## 5. 验证

### 5.1 单元 / 集成测试

```bash
# 项目虚拟环境
.venv/bin/python -m pytest tests -q

# 结果（本次重构后）
214 passed in 9.90s
```

覆盖范围：

| 测试文件 | 覆盖点 |
|---|---|
| `test_utils.py` | 文件名清理、格式化、扩展名/音质分档、JSON 原子读写 |
| `test_naming.py` | 模板校验/渲染/回退、下载任务命名集成 |
| `test_api.py` | 四平台响应解析、交错排序、版本识别、详情一致性、歌词四级兜底 |
| `test_downloader.py` | 限速器、状态机、冲突策略、Range/200 回退、断线重试、取消、队列管理 |
| `test_media.py` | 配置校验、封面 MIME/大小、MP3/FLAC 标签、转码、后处理管线 |
| `test_ffmpeg.py` | 平台魔数、工具定位、WAV 提取、临时文件清理 |
| `test_transcribe.py` | LRC 时间轴/拆分/去重、元信息透传、解码回退 |
| `test_recognize.py` | Shazam 结果解析、入口边界 |
| `test_config.py` | 设置校验/合并/原子写入/写入去抖、历史、打赏记录、损坏备份 |
| `test_cli.py` | 多选解析、表格、进度输出、入队与汇总 |
| `test_theme.py` | 色彩运算、调色板完整性、外观探测缓存、模式解析、后台监视 |
| `test_architecture.py` | Qt GUI 不依赖 Tkinter、核心层无 GUI 依赖、公共 API 兼容 |
| `test_ffmpeg_detect.py` / `test_qt_plugins_visible.py` | 历史回归（ffmpeg 魔数、Qt 插件自愈） |

### 5.2 静态检查

```bash
.venv/bin/python -m pylint --rcfile=.pylintrc \
  utils.py naming.py api.py downloader.py media.py ffmpeg.py \
  transcribe.py recognize.py cli.py config.py theme.py
# 9.91/10（剩余为数据类/校验函数固有的设计度量提示）

ruff check <核心模块> --select E,F   # All checks passed
```

### 5.3 GUI 冒烟

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python - <<'PY'
from PyQt6.QtWidgets import QApplication
import gui_qt
app = QApplication([])
win = gui_qt.MainWindow(demo=True)
win.show(); app.processEvents(); win.close()
PY

.venv/bin/python - <<'PY'
import tkinter as tk, gui
root = tk.Tk(); root.withdraw()
app = gui.MusicDownloaderGUI(root, demo=True)
root.update(); root.destroy()
PY
```

两套 GUI 均可在无窗口环境完成构建、主题应用与销毁。

## 6. 后续建议

* `gui.py` / `gui_qt.py` 仍包含大量自绘控件代码（分别约 2.8k / 4.4k 行），
  后续可按「基础控件 / 弹窗 / 主窗口」继续拆分，但需要更细的视觉回归
  手段，本次未做高风险搬迁。
* `music.py` / `music_gui.py` 为 v1.0 参考实现，建议在下一个大版本中
  正式移除，避免与 `api.py` / `cli.py` 的重复实现继续漂移。
