# py-music-dl

A command-line music downloader written purely in Python, supporting search and download of songs from multiple mainstream music platforms.

## Features

- **Multi-platform Search**: Supports platforms such as NetEase Cloud Music, QQ Music, Kuwo Music, and Migu Music
- **One-click Download**: Search and download songs by entering keywords
- **Multiple Quality Options**: Offers various audio quality choices for download
- **Command-line Interface**: Simple terminal-based interactive interface
- **Progress Display**: Real-time progress bar during downloads

## Dependencies

- Python 3.6+
- Requests library (`requests`)
- Beautiful Soup 4 (`bs4`)

## Installation

```bash
pip install requests bs4
```

## Usage

Run the program:

```bash
python music.py
```

1. Enter the name of the song you want to search for
2. Select the song number from the search results
3. Choose the desired audio quality
4. Wait for the download to complete

## Project Structure

```
music.py          # Main program file
├── MusicAPI      # API wrappers for each platform
│   ├── search_migu      # Migu Music search
│   ├── search_netease    # NetEase Cloud Music search
│   ├── search_qq        # QQ Music search
│   └── search_kuwo      # Kuwo Music search
├── MusicDownloader     # Downloader classes
│   ├── search_all       # Search across all platforms
│   ├── get_detail      # Fetch song details
│   └── download_mp3    # Download MP3 files
└── BS4Demo       # Utility demonstration classes
```

## Sample Output

```
============================================================
Welcome to py-music-dl Music Downloader
============================================================
Enter the song to search for: Actor
Searching...
----------------------------------------
[1] Actor - Xue Zhiqian
[2] Actor (Live) - Xue Zhiqian
...
Select song number: 1
```

## Notes

- Ensure your network connection is stable
- Downloaded songs are intended for personal learning purposes only; please respect copyright
- Some songs may not be downloadable due to copyright restrictions

## Contribution Guide

Issues and pull requests are welcome!

## Open Source License

MIT License