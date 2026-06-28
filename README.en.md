<div align="center">
  <h1>🎵 Py-Music-DL</h1>
  <p>
    <strong>Multi-platform Music Downloader</strong><br>
    Pure Python · 4 Platforms · CLI + GUI · Concurrent Search · Batch Download
  </p>
</div>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License">
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-orange.svg" alt="Platform">
  <img src="https://img.shields.io/badge/version-2.0-brightgreen.svg" alt="Version">
</p>

---

## ✨ Features

### Search & Discovery
- **Concurrent Multi-platform Search** — `ThreadPoolExecutor` with 4 workers queries Migu, NetEase Cloud Music, QQ Music, and Kuwo Music simultaneously, reducing total time from 4-8s to ~2s
- **Fair Interleaved Results** — Rotates through platforms to prevent any single source from dominating the top slots
- **Concurrent Quality Prefetch** — 6 threads fetch quality metadata in parallel; auto-labels each track as 320K or LOSSLESS
- **Multi-format Detection** — MP3 / FLAC / WAV / APE / M4A / OGG auto-detection

### Download Engine
- **Batch Download** — Multi-select (`1,3,5-8` / `all` in CLI; Ctrl/Shift+Click in GUI), queued sequential download
- **Resume Support** — HTTP `Range` header enables resume from interruption point, with 2 automatic retries
- **Streaming Chunks** — 8KB chunked writes with real-time progress bar
- **Pause / Resume / Cancel** — Per-task or batch operations, full control mid-download

### GUI (v2.0 Redesigned)
- **Download Task Panel** — Individual progress bar + status icon + pause/resume + cancel per task
- **Queue Management** — Pause all, cancel all, clear completed
- **Multi-select Batch Add** — Ctrl/Shift+Click to select multiple tracks, one-click add to queue
- **Search History & Filters** — Auto-saved history with dropdown autocomplete; filter by artist or platform
- **Status Bar + Log Panel** — Real-time search & download feedback

### Code Quality
- **Modular Architecture** — `api.py` / `downloader.py` / `cli.py` / `gui.py` / `utils.py`, each with a clear responsibility
- **Full Type Annotations** — `from __future__ import annotations` with complete type hints throughout
- **Unified Logging** — Standard `logging` module; stderr for CLI, log panel for GUI

## 📦 Requirements

| Dependency       | Minimum Version |
|------------------|-----------------|
| Python           | 3.10+           |
| requests         | 2.28+           |
| beautifulsoup4   | 4.11+           |
| lxml             | 4.9+            |
| urllib3          | 1.26+           |

## 🚀 Quick Start

```bash
# 1. Clone the repository
git clone https://gitee.com/zhangmf9773/py-music-dl && cd py-music-dl

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run
python3 cli.py       # CLI mode (v2.0)
python3 gui.py       # GUI mode (v2.0, recommended)
```

### CLI Mode — `python3 cli.py`

```
═────────────────────────────────────────────────────
           🎵  Music Downloader v2.0  🎵
                Multi-platform
     Supports: Migu | NetEase | QQ Music | Kuwo
═────────────────────────────────────────────────────
  New: Concurrent Search · Batch Download · Resume
═────────────────────────────────────────────────────

Download directory (Enter for default downloaded_music/):

Search for a song: 晴天

[✓] 40 tracks found (interleaved)

═─────────────────────────────────────────────────────────
  #    Title                        Artist         Source       Quality
═─────────────────────────────────────────────────────────
1     晴天                           周杰伦          Migu         320K
2     晴天                           周杰伦          NetEase      LOSSLESS
3     晴天                           周杰伦          QQ Music     320K
4     晴天                           周杰伦          Kuwo         320K
...

Enter track numbers (e.g. 1,3,5-8 or all, 0 to quit): 1,3

[*] 2 tracks selected, fetching download links...
[*] Starting download of 2 tracks...

  [↓] 周杰伦 - 晴天                    [████████████████████] 100.0%
  [↓] 周杰伦 - 晴天                    [████████████████████] 100.0%

═────────────────────────────────────────────────────
  Done: 2 succeeded, 0 failed
  Files saved in: downloaded_music/
═────────────────────────────────────────────────────
```

## 🎯 Supported Platforms

| Platform              | Search  | Download  | Quality          |
|-----------------------|:-------:|:---------:|------------------|
| Migu Music            |    ✅    |     ✅     | 320K / LOSSLESS  |
| NetEase Cloud Music   |    ✅    |     ✅     | 320K / LOSSLESS  |
| QQ Music              |    ✅    |     ✅     | 320K / LOSSLESS  |
| Kuwo Music            |    ✅    |     ✅     | 320K / LOSSLESS  |

## 📁 Project Structure

```
py-music-dl/
├── api.py                       # API layer — concurrent search + quality prefetch + detail
│   ├── search_all_platforms()   # ThreadPoolExecutor 4-worker concurrent search
│   ├── prefetch_quality()       # 6-worker concurrent quality prefetch
│   ├── get_song_detail()        # Fetch download link for a song
│   └── _SEARCHERS / _DETAILERS  # Platform registry (add/remove platforms via dict)
├── downloader.py                # Download engine — queue scheduling + resume + callbacks
│   ├── DownloadTask             # Single-task state machine (7 states + pause/cancel events)
│   └── DownloadQueue            # Queue manager (sequential download, retries, progress/status callbacks)
├── cli.py                       # CLI entry — interactive command-line interface
│   ├── _display_table()         # Search results table rendering
│   ├── _multi_select()          # Multi-select parser (1,3,5-8 / all)
│   └── _print_progress()        # Real-time progress bar
├── gui.py                       # GUI entry — Tkinter graphical interface (v2.0 redesigned)
│   ├── SearchHistory            # Persistent search history manager
│   ├── TaskRow                  # Task panel row widget (progress bar + controls)
│   └── MusicDownloaderGUI       # Main GUI class (full layout + queue callbacks)
├── utils.py                     # Utilities — formatting, logging, filename sanitization
│   ├── safe_filename()          # Illegal character removal
│   ├── format_size()            # Bytes → human-readable size
│   ├── format_progress_bar()    # Text progress bar
│   ├── quality_from_url()       # URL → quality inference
│   └── log                      # logging.Logger instance
├── music.py                     # [v1.0 legacy] Monolithic CLI (includes BS4Demo)
├── music_gui.py                 # [v1.0 legacy] Old GUI
├── downloaded_music/            # Download output directory
├── search_history.json          # Persistent search history file
├── requirements.txt             # Dependency manifest
└── README.md
```

## 🔧 Configuration

**CLI / API / Download Engine** — Edit constants at the top of each file:

```python
# api.py
HEADERS = { ... }          # HTTP request headers
TIMEOUT = 10               # Request timeout (seconds)
MAX_WORKERS = 10           # Concurrent worker threads

# downloader.py
CHUNK_SIZE = 8192          # Download chunk size (bytes)
DEFAULT_TIMEOUT = 60       # Download timeout (seconds)

# utils.py
DEFAULT_DOWNLOAD_DIR = "downloaded_music"  # Default download directory
```

**GUI** — Switch download directory directly in the interface; search history is auto-persisted to `search_history.json`.

## 📝 Changelog

### v2.0
- **Concurrent Search** — `ThreadPoolExecutor` 4-worker parallel search across all platforms, ~2s total
- **Batch Download** — Multi-select input in CLI (`1,3,5-8` / `all`), multi-select batch add in GUI
- **Resume Download** — HTTP `Range` header support with auto-resume and 2 retries
- **GUI Redesign** — Download task panel (per-task progress bar + pause/cancel), queue management buttons, settings panel
- **Code Modularization** — Split into `api.py` / `downloader.py` / `cli.py` / `gui.py` / `utils.py`
- **Full Type Annotations** — `from __future__ import annotations` with complete type hints
- **Unified Logging** — `logging` module replaces scattered `print()` calls
- **Pause Fix** — Corrected `DownloadTask` pause event semantics; pause/resume now works reliably

### v1.0
- Four-platform aggregated search & download
- Concurrent quality prefetch with 6 workers
- Tkinter GUI with search history & filters

## 📄 License

[MIT License](LICENSE)

---

<p align="center">
  <sub>Made with ❤️ for learning purposes</sub>
</p>
