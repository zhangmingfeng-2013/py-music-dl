# py-music-dl

A command-line music downloader written in pure Python that supports searching and downloading songs from multiple major music platforms.

> **Disclaimer**: This project is for learning web scraping techniques, `requests`, and `BeautifulSoup` only. Please respect platform terms of service and copyright regulations. Do not use for commercial purposes.

## Features

- **Multi-platform Aggregated Search**: Simultaneously searches across Migu Music, NetEase Cloud Music, QQ Music, and Kuwo Music, with interleaved display for fair exposure
- **One-click Download**: Enter a keyword to search and download songs, supporting MP3 / FLAC / WAV formats
- **Automatic Quality Detection**: Automatically identifies 320K high quality and LOSSLESS audio from download links
- **BeautifulSoup Tutorial Demo**: Built-in BS4 core API overview and live scraping demo, ideal for learning web scraping
- **Progress Display**: Real-time progress bar and file size display during download
- **Interactive Terminal**: Simple terminal interaction — select songs by number with instant feedback

## Requirements

- Python **3.8+** (3.10+ recommended)

## Installation

```bash
pip install requests beautifulsoup4 lxml urllib3
```

Or using requirements.txt:

```bash
pip install -r requirements.txt
```

## Quick Start

```bash
python music.py
```

Follow the prompts after running:

1. The **BeautifulSoup core API tutorial** and live page scraping demo are displayed first
2. Enter the name of the song you want to search for
3. Select a song by its number from the interleaved multi-platform results
4. Details are automatically fetched and the file is downloaded to the `downloaded_music/` directory

## Supported Platforms

| Platform            | Search  | Download  | Quality         |
|---------------------|---------|-----------|-----------------|
| Migu Music          | ✅       | ✅         | 320K / LOSSLESS |
| NetEase Cloud Music | ✅       | ✅         | 320K / LOSSLESS |
| QQ Music            | ✅       | ✅         | 320K / LOSSLESS |
| Kuwo Music          | ✅       | ✅         | 320K / LOSSLESS |

## Project Structure

```
py-music-dl/
├── music.py              # Main program (single file, contains all logic)
└── downloaded_music/     # Downloaded files directory
```

## Example Output

```
============================================================
     🎵  音乐下载器 v6.1  🎵
     多平台聚合 · requests + BeautifulSoup
     支持：咪咕 | 网易云 | QQ音乐 | 酷我
============================================================

请输入要搜索的歌曲名：晴天

[*] 正在多平台搜索：晴天
    --------------------------------------------------
    [→] 搜索 咪咕音乐...
        咪咕音乐: 找到 10 首
    [→] 搜索 网易云音乐...
        网易云音乐: 找到 10 首
    [→] 搜索 QQ音乐...
        QQ音乐: 找到 10 首
    [→] 搜索 酷我音乐...
        酷我音乐: 找到 10 首

[✓] 共找到 40 首歌曲（已交错排列）

==========================================================================================
序号    歌曲名                           歌手                  来源              音质
==========================================================================================
1      晴天                              周杰伦                咪咕音乐              ?
2      晴天                              周杰伦                网易云音乐             ?
3      晴天                              周杰伦                QQ音乐               ?
...
==========================================================================================

请输入要下载的歌曲序号（输入 0 退出）：1

[*] 获取详情（咪咕音乐）...
    [✓] 获取到下载链接
    音质: LOSSLESS

[*] 开始下载：周杰伦 - 晴天.flac
    文件大小：25.63 MB
    下载进度: [████████████████████████████████████████] 100.0%
[✓] 下载完成！保存位置：downloaded_music/周杰伦 - 晴天.flac
```

## Notes

- Ensure a stable network connection; some APIs may require reliable connectivity
- Platform APIs are third-party aggregation services and may occasionally be unstable. Retry if failed.
- Downloaded songs are for personal learning purposes only. Please respect copyright.
- Some songs may not have downloadable links due to copyright restrictions.

## License

[MIT License](LICENSE)