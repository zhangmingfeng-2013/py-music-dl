<div align="center">
  <h1>🎵 Py-Music-DL </h1>
  <p>
    <strong>Multi-platform Music Downloader</strong><br>
    Pure Python · 4 Platforms · CLI + GUI
  </p>
</div>
<p align="center">
  <img src="https://img.shields.io/badge/python-3.8+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License">
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-orange.svg" alt="Platform">
</p>

---

## ✨ Features

- **Multi-platform Aggregated Search** — Simultaneously queries Migu, NetEase Cloud Music, QQ Music, and Kuwo Music with interleaved results
- **Dual-mode: CLI + GUI** — Fast command-line operations or an intuitive graphical interface
- **Automatic Quality Detection** — Labels each track as 320K or LOSSLESS based on file extension
- **Concurrent Quality Prefetch** — `ThreadPoolExecutor` with 6 workers fetches quality metadata in parallel, minimizing wait time
- **Search History & Filters** (GUI) — Auto-saved search history with dropdown suggestions; filter by artist or platform
- **Streaming Download** — Chunked download with real-time progress bar and file size display
- **Multi-format Support** — MP3 / FLAC / WAV / APE / M4A / OGG with auto-detection
- **BeautifulSoup Tutorial** — Built-in BS4 demo that scrapes and parses a real webpage

## 📦 Requirements

| Dependency     | Minimum Version          |
|----------------|--------------------------|
| Python         | 3.8+ (3.10+ recommended) |
| requests       | 2.28+                    |
| beautifulsoup4 | 4.11+                    |
| lxml           | 4.9+                     |
| urllib3        | 1.26+                    |

## 🚀 Quick Start

```bash
# 1. Clone the repository
git clone https://gitee.com/zhangmf9773/py-music-dl && cd py-music-dl

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run
python3 music.py       # CLI mode
python3 music_gui.py   # GUI mode
```

### CLI Mode

```
Enter song name: 晴天

[*] Searching across platforms: 晴天
    [→] Migu Music...       10 results
    [→] NetEase Music...    10 results
    [→] QQ Music...         10 results
    [→] Kuwo Music...       10 results
    [→] Prefetching quality info (30 tracks)...

[✓] 40 tracks found (interleaved)

 #    Title                      Artist         Source       Quality
═══════════════════════════════════════════════════════════════
1    晴天                        周杰伦         Migu         320K
2    晴天                        周杰伦         NetEase      LOSSLESS
...

Enter track number to download (0 to quit): 2
[*] Progress: [████████████████████████] 100.0%
[✓] Done! Saved to: downloaded_music/周杰伦 - 晴天.flac
```

### GUI Mode

```
python3 music_gui.py
```

- Search box with history dropdown and autocomplete
- Double-click or select + "Download Selected" to download
- Filter results by artist or platform
- Log panel with real-time download status

## 🎯 Supported Platforms

| Platform            | Search  | Download  | Quality         |
|---------------------|:-------:|:---------:|-----------------|
| Migu Music          |    ✅    |     ✅     | 320K / LOSSLESS |
| NetEase Cloud Music |    ✅    |     ✅     | 320K / LOSSLESS |
| QQ Music            |    ✅    |     ✅     | 320K / LOSSLESS |
| Kuwo Music          |    ✅    |     ✅     | 320K / LOSSLESS |

## 📁 Project Structure

```
py-dl/
├── music.py                # CLI application
│   ├── MusicAPI            #   Platform search & detail APIs
│   ├── MusicDownloader     #   Download workflow manager
│   └── BS4Demo             #   BeautifulSoup tutorial
├── music_gui.py            # Tkinter GUI application
│   ├── MusicDownloaderGUI  #   GUI main class
│   └── SearchHistory       #   Search history manager
├── downloaded_music/       # Download output directory
├── requirements.txt        # Dependency manifest
└── README.md
```

## ⚙️ Configuration

Edit constants at the top of `music.py`:

```python
HEADERS = { ... }                     # HTTP request headers
DOWNLOAD_DIR = "downloaded_music"     # Download directory
TIMEOUT = 15                          # Request timeout (seconds)
```

In GUI mode, the download directory can be changed directly from the interface.

## 📝 Changelog

### v1.0
- Four-platform aggregated search & download
- Concurrent quality prefetch with 6 threads
- Tkinter GUI with search history & filters
- BeautifulSoup tutorial module

## 📄 License

[MIT License](LICENSE)

---

<p align="center">
  <sub>Made with ❤️ for learning purposes</sub>
</p>
