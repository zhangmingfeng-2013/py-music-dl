#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
音乐下载器 v6.1 (多平台聚合版 · requests + BeautifulSoup)
功能：根据用户输入的歌曲名，从多平台搜索并下载MP3/FLAC音乐文件
数据源：基于 http://qjjlb.quanjian.com.cn/musicdl/ 的聚合音乐站API
支持平台：咪咕音乐 / 网易云音乐 / QQ音乐 / 酷我音乐
使用库：requests（网络请求）、bs4（HTML解析）、re（正则匹配）
注意：仅供学习爬虫技术，请遵守网站协议和版权规定，勿用于商业用途
"""

import os
import re
import json
import time
import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===================== 配置 =====================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "http://qjjlb.quanjian.com.cn/musicdl/",
}

DOWNLOAD_DIR = "downloaded_music"
TIMEOUT = 15

# ===================== 工具函数 =====================


def safe_filename(text):
    """清理文件名中的非法字符"""
    return re.sub(r'[\\/*?:"<>|]', "", text)


def format_duration(seconds):
    """将秒数格式化为 mm:ss"""
    if not seconds or seconds <= 0:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def format_size(size_bytes):
    """将字节数格式化为可读大小"""
    if not size_bytes or size_bytes <= 0:
        return "未知"
    mb = size_bytes / (1024 * 1024)
    if mb >= 1:
        return f"{mb:.2f} MB"
    return f"{size_bytes / 1024:.1f} KB"


def print_progress(downloaded, total, bar_width=40):
    """打印下载进度条"""
    if total <= 0:
        print(f"\r    已下载: {format_size(downloaded)}", end="", flush=True)
        return
    percent = downloaded / total * 100
    filled = int(bar_width * downloaded / total)
    bar = "█" * filled + "░" * (bar_width - filled)
    print(f"\r    下载进度: [{bar}] {percent:.1f}%", end="", flush=True)


def print_line(char="=", width=60):
    print(char * width)


# ===================== API 封装层 =====================


class MusicAPI:
    """封装多平台音乐搜索与详情 API"""

    @staticmethod
    def search_migu(keyword, limit=10):
        """
        搜索咪咕音乐
        API: https://api.xcvts.cn/api/music/migu
        返回: [{title, artist, index, cover, ...}]
        """
        url = "https://api.xcvts.cn/api/music/migu"
        params = {
            "gm": keyword,
            "n": "",
            "num": limit,
            "type": "json",
        }
        try:
            resp = requests.get(url, headers=HEADERS, params=params,
                                timeout=TIMEOUT, verify=False)
            # 咪咕 API 偶发 502 错误，先检查状态码
            if resp.status_code != 200:
                print(f"    [✗] 咪咕API返回 {resp.status_code}，暂时不可用")
                return []
            data = resp.json()
            if data.get("code") != 200 or not isinstance(data.get("data"), list):
                return []
            results = []
            for item in data["data"]:
                results.append({
                    "source": "migu",
                    "title": item.get("title", ""),
                    "artist": item.get("singer", ""),
                    "index": item.get("n", 0),
                    "cover": item.get("cover"),
                    "keyword": keyword,
                    "request_num": limit,
                })
            return results
        except requests.RequestException as e:
            print(f"    [✗] 咪咕搜索失败: {e}")
            return []
        except json.JSONDecodeError:
            print(f"    [✗] 咪咕API返回非JSON内容（可能暂时不可用）")
            return []

    @staticmethod
    def search_netease(keyword, page=1, num=10):
        """
        搜索网易云音乐
        API: https://api.vkeys.cn/v2/music/netease
        """
        url = "https://api.vkeys.cn/v2/music/netease"
        params = {
            "word": keyword,
            "page": page,
            "num": num,
        }
        try:
            resp = requests.get(url, headers=HEADERS, params=params,
                                timeout=TIMEOUT, verify=False)
            data = resp.json()
            # 网易云 API 偶发 505 错误，允许 data 非空时继续
            if not isinstance(data.get("data"), list) or not data["data"]:
                return []
            results = []
            for idx, item in enumerate(data["data"]):
                results.append({
                    "source": "netease",
                    "title": item.get("song", ""),
                    "artist": item.get("singer", ""),
                    "song_id": item.get("id"),
                    "album": item.get("album", ""),
                    "cover": item.get("cover"),
                    "display_index": (page - 1) * num + idx + 1,
                    "keyword": keyword,
                })
            return results
        except Exception as e:
            print(f"    [✗] 网易云搜索失败: {e}")
            return []

    @staticmethod
    def search_qq(keyword, limit=10):
        """
        搜索QQ音乐
        API: https://tang.api.s01s.cn/music_open_api.php
        """
        url = "https://tang.api.s01s.cn/music_open_api.php"
        params = {
            "msg": keyword,
            "type": "json",
        }
        try:
            resp = requests.get(url, headers=HEADERS, params=params,
                                timeout=TIMEOUT, verify=False)
            data = resp.json()
            raw = data if isinstance(data, list) else data.get("data", [])
            if not isinstance(raw, list):
                return []
            results = []
            for idx, item in enumerate(raw[:limit]):
                mid = item.get("song_mid", "")
                if not mid:
                    continue
                results.append({
                    "source": "qq",
                    "title": item.get("song_title", ""),
                    "artist": item.get("singer_name", ""),
                    "song_mid": mid,
                    "qq_index": idx + 1,
                    "display_index": idx + 1,
                    "keyword": keyword,
                    "qq_search_key": keyword,
                    "cover": None,
                })
            return results
        except Exception as e:
            print(f"    [✗] QQ音乐搜索失败: {e}")
            return []

    @staticmethod
    def search_kuwo(keyword, limit=10):
        """
        搜索酷我音乐
        API: https://kw-api.cenguigui.cn/
        """
        url = "https://kw-api.cenguigui.cn/"
        params = {
            "name": keyword,
            "page": 1,
            "limit": limit,
        }
        try:
            resp = requests.get(url, headers=HEADERS, params=params,
                                timeout=TIMEOUT, verify=False)
            data = resp.json()
            results = []
            songs = []
            if isinstance(data, dict) and data.get("data"):
                raw = data["data"]
                if isinstance(raw, list):
                    songs = raw
                elif isinstance(raw, dict):
                    songs = raw.get("list", []) or raw.get("data", []) or []
            for idx, item in enumerate(songs):
                rid = item.get("rid") or item.get("id") or item.get("musicrid", "")
                # 酷我搜索接口已直接返回下载链接 url 字段
                audio_url = item.get("url", "")
                results.append({
                    "source": "kuwo",
                    "title": item.get("name", "") or item.get("songname", ""),
                    "artist": item.get("artist", "") or item.get("singer", ""),
                    "rid": str(rid).replace("MUSIC_", ""),
                    "display_index": idx + 1,
                    "keyword": keyword,
                    "cover": item.get("pic") or item.get("cover"),
                    "audio_url": audio_url,  # 搜索阶段已包含下载链接
                })
            return results
        except Exception as e:
            print(f"    [✗] 酷我搜索失败: {e}")
            return []

    @staticmethod
    def get_migu_detail(track):
        """
        获取咪咕歌曲详情（含下载链接）
        复用同一个搜索接口，指定 n 参数定位歌曲
        """
        num = track.get("request_num", 20)
        url = "https://api.xcvts.cn/api/music/migu"
        params = {
            "gm": track["keyword"],
            "n": track.get("index", 1),
            "num": num,
            "type": "json",
        }
        try:
            resp = requests.get(url, headers=HEADERS, params=params,
                                timeout=TIMEOUT, verify=False)
            data = resp.json()
            if data.get("code") != 200:
                return None
            detail = {
                "title": data.get("title") or track.get("title"),
                "artist": data.get("singer") or track.get("artist"),
                "cover": data.get("cover") or track.get("cover"),
                "audio_url": data.get("music_url"),
                "lrc_url": data.get("lrc_url"),
                "page_url": data.get("link"),
            }
            if detail["audio_url"]:
                ext = detail["audio_url"].split("?")[0].rsplit(".", 1)[-1].lower()
                detail["quality"] = "LOSSLESS" if ext in ("flac", "wav", "ape") else "320K"
            return detail
        except Exception as e:
            print(f"    [✗] 咪咕详情获取失败: {e}")
            return None

    @staticmethod
    def get_netease_detail(track):
        """
        获取网易云歌曲详情（含下载链接）
        通过 meting API 获取音源
        """
        song_id = track.get("song_id")
        if not song_id:
            return None
        # 获取音源URL
        meting_url = f"https://api.qijieya.cn/meting/?type=song&id={song_id}"
        try:
            resp = requests.get(meting_url, headers=HEADERS,
                                timeout=TIMEOUT, verify=False)
            data = resp.json()
            if not isinstance(data, list) or not data:
                return None
            d = data[0]
            audio_url = d.get("url", "")
            detail = {
                "title": d.get("name") or track.get("title"),
                "artist": d.get("artist") or track.get("artist"),
                "cover": d.get("pic") or track.get("cover"),
                "audio_url": audio_url,
            }
            if audio_url:
                ext = audio_url.split("?")[0].rsplit(".", 1)[-1].lower()
                detail["quality"] = "LOSSLESS" if ext in ("flac", "wav", "ape") else "320K"
            return detail
        except Exception as e:
            print(f"    [✗] 网易云详情获取失败: {e}")
            return None

    @staticmethod
    def get_qq_detail(track):
        """
        获取QQ音乐歌曲详情（含下载链接）
        通过 tang API 传入 mid 获取播放链接
        """
        mid = track.get("song_mid")
        keyword = track.get("qq_search_key") or track.get("keyword", "")
        if not mid:
            return None
        url = "https://tang.api.s01s.cn/music_open_api.php"
        params = {
            "msg": keyword,
            "type": "json",
            "mid": mid,
        }
        try:
            resp = requests.get(url, headers=HEADERS, params=params,
                                timeout=TIMEOUT, verify=False)
            data = resp.json()
            # 找到最佳播放链接（优先无损）
            audio_url = (
                data.get("song_play_url_sq")
                or data.get("song_play_url_pq")
                or data.get("song_play_url_hq")
                or data.get("song_play_url_standard")
                or data.get("song_play_url")
            )
            if not audio_url:
                return None
            ext = audio_url.split("?")[0].rsplit(".", 1)[-1].lower()
            quality = "LOSSLESS" if ext in ("flac", "wav", "ape") else "320K"
            return {
                "title": data.get("song_title") or track.get("title"),
                "artist": data.get("singer_name") or track.get("artist"),
                "cover": track.get("cover"),
                "audio_url": audio_url,
                "quality": quality,
            }
        except Exception as e:
            print(f"    [✗] QQ音乐详情获取失败: {e}")
            return None

    @staticmethod
    def get_kuwo_detail(track):
        """
        获取酷我音乐歌曲详情（含下载链接）
        优先使用搜索阶段已返回的 url 字段
        """
        # 搜索阶段已包含下载链接，直接使用
        audio_url = track.get("audio_url", "")
        if audio_url:
            ext = audio_url.split("?")[0].rsplit(".", 1)[-1].lower()
            quality = "LOSSLESS" if ext in ("flac", "wav", "ape") else "320K"
            return {
                "title": track.get("title"),
                "artist": track.get("artist"),
                "cover": track.get("cover"),
                "audio_url": audio_url,
                "quality": quality,
            }

        # 备用方案：通过 rid 构造详情请求
        rid = track.get("rid", "")
        if rid:
            detail_url = f"https://kw-api.cenguigui.cn?id={rid}&type=song&level=exhigh&format=mp3"
            try:
                resp = requests.get(detail_url, headers=HEADERS,
                                    timeout=TIMEOUT, verify=False, allow_redirects=True)
                if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("audio"):
                    audio_url = detail_url
                elif resp.status_code == 200:
                    try:
                        data = resp.json()
                        audio_url = data.get("url", "") or data.get("play_url", "")
                        if isinstance(data.get("data"), dict):
                            audio_url = audio_url or data["data"].get("url", "")
                    except json.JSONDecodeError:
                        pass
                if audio_url:
                    ext = audio_url.split("?")[0].rsplit(".", 1)[-1].lower()
                    quality = "LOSSLESS" if ext in ("flac", "wav", "ape") else "320K"
                    return {
                        "title": track.get("title"),
                        "artist": track.get("artist"),
                        "cover": track.get("cover"),
                        "audio_url": audio_url,
                        "quality": quality,
                    }
            except Exception as e:
                print(f"    [✗] 酷我详情获取失败: {e}")
        return None


# ===================== BeautifulSoup 演示层 =====================


class BS4Demo:
    """
    BeautifulSoup 教学演示模块
    演示如何使用 bs4 抓取并解析 HTML 网页内容
    """

    @staticmethod
    def scrape_musicdl_page():
        """
        抓取音乐站首页，用 bs4 解析 HTML 结构
        这是 bs4 学习的核心演示

        流程：
        1. 用 requests 获取目标页面的 HTML
        2. 用 BeautifulSoup(lxml) 解析
        3. 演示 find / find_all / select / get_text 等常用API
        """
        url = "http://qjjlb.quanjian.com.cn/musicdl/"
        print(f"\n[*] --- BS4 演示：抓取并解析音乐站首页 ---")
        print(f"    目标URL: {url}")

        try:
            # 步骤1：获取 HTML
            print(f"    [1/5] 用 requests.get() 发起请求...")
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, verify=False)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            html = resp.text
            print(f"        获取到 HTML，共 {len(html)} 个字符")

            # 步骤2：创建 BeautifulSoup 对象
            print(f"    [2/5] 用 BeautifulSoup(html, 'lxml') 解析...")
            soup = BeautifulSoup(html, "lxml")

            # 步骤3：find — 查找第一个匹配的元素
            print(f"    [3/5] 使用 find() 查找关键元素:")
            title_tag = soup.find("title")
            if title_tag:
                print(f"        页面标题: {title_tag.get_text(strip=True)}")

            # 步骤4：find_all — 查找所有匹配的元素
            print(f"    [4/5] 使用 find_all() 统计页面结构:")
            tags_to_check = ["script", "link", "meta", "div", "span", "input", "button"]
            for tag in tags_to_check:
                count = len(soup.find_all(tag))
                if count > 0:
                    print(f"        <{tag}>: {count} 个")

            # 步骤5：select — CSS 选择器
            print(f"    [5/5] 使用 select() CSS选择器查找元素:")
            # 查找所有带 class 属性的元素
            elements_with_class = soup.select("[class]")
            print(f"        带 class 属性的元素: {len(elements_with_class)} 个")
            # 查找所有带 id 属性的元素
            elements_with_id = soup.select("[id]")
            if elements_with_id:
                ids = [el.get("id") for el in elements_with_id[:10] if el.get("id")]
                print(f"        带 id 属性的元素: {len(elements_with_id)} 个")
                print(f"        前10个 id: {ids}")

            return soup

        except requests.RequestException as e:
            print(f"    [✗] 网络请求失败: {e}")
            return None
        except Exception as e:
            print(f"    [✗] BS4 解析失败: {e}")
            return None

    @staticmethod
    def demo_bs4_api():
        """
        BeautifulSoup 核心 API 速览
        用一段示例 HTML 演示 bs4 的常用操作
        """
        print("\n" + "=" * 60)
        print("  【学习模块】BeautifulSoup 核心 API 速览")
        print("=" * 60)

        sample_html = """
        <!DOCTYPE html>
        <html lang="zh">
        <head>
            <title>皮卡丘的音乐站</title>
            <meta charset="UTF-8">
        </head>
        <body>
            <header>
                <h1 class="site-title">皮卡丘的音乐站</h1>
                <p class="subtitle">作者：Zhenchao Jin + GPT 5.1</p>
            </header>
            <main>
                <div class="search-panel" id="search-box">
                    <input type="text" id="search-input" placeholder="输入歌名搜索...">
                    <button class="btn-primary">搜索</button>
                </div>
                <div class="results">
                    <ul id="song-list">
                        <li class="song-item" data-id="1" data-source="migu">
                            <span class="song-name">晴天</span>
                            <span class="artist">周杰伦</span>
                            <span class="quality lossless">LOSSLESS</span>
                        </li>
                        <li class="song-item" data-id="2" data-source="netease">
                            <span class="song-name">七里香</span>
                            <span class="artist">周杰伦</span>
                            <span class="quality hq">320K</span>
                        </li>
                        <li class="song-item vip" data-id="3" data-source="qq">
                            <span class="song-name">夜曲</span>
                            <span class="artist">周杰伦</span>
                            <span class="quality lossless">LOSSLESS</span>
                        </li>
                    </ul>
                </div>
            </main>
            <footer>
                <p>音乐版权归各平台与原作者所有</p>
            </footer>
        </body>
        </html>
        """

        soup = BeautifulSoup(sample_html, "lxml")



# ===================== 下载管理器 =====================


class MusicDownloader:
    """音乐下载器主类，串联搜索、详情、下载全流程"""

    def __init__(self):
        self.api = MusicAPI()
        self.bs4_demo = BS4Demo()

        if not os.path.exists(DOWNLOAD_DIR):
            os.makedirs(DOWNLOAD_DIR)
            print(f"[✓] 创建下载目录：{DOWNLOAD_DIR}")

    def search_all(self, keyword):
        """
        跨平台搜索歌曲
        依次从咪咕、网易云、QQ音乐、酷我四个平台搜索，
        并交错排列结果（公平展示各平台）
        """
        print(f"\n[*] 正在多平台搜索：{keyword}")
        print("    " + "-" * 50)

        # 并发搜索四个平台
        all_results = []
        platforms = [
            ("咪咕音乐", self.api.search_migu),
            ("网易云音乐", self.api.search_netease),
            ("QQ音乐", self.api.search_qq),
            ("酷我音乐", self.api.search_kuwo),
        ]

        grouped = {}
        for name, search_func in platforms:
            print(f"    [→] 搜索 {name}...")
            results = search_func(keyword)
            print(f"        {name}: 找到 {len(results)} 首")
            grouped[name] = results

        # 交错排列：从各平台轮流取一首，保证展示公平
        order = ["咪咕音乐", "网易云音乐", "QQ音乐", "酷我音乐"]
        indices = {k: 0 for k in order}
        interleaved = []
        added = True
        global_idx = 0
        while added:
            added = False
            for src in order:
                arr = grouped[src]
                i = indices[src]
                if i < len(arr):
                    song = arr[i]
                    song["display_order"] = global_idx
                    song["source_name"] = src
                    interleaved.append(song)
                    global_idx += 1
                    indices[src] += 1
                    added = True

        print(f"\n[✓] 共找到 {len(interleaved)} 首歌曲（已交错排列）")
        return interleaved

    def display_songs(self, songs):
        """以表格形式展示歌曲列表"""
        if not songs:
            print("[!] 没有找到歌曲")
            return -1

        print("\n" + "=" * 90)
        print(f"{'序号':<6}{'歌曲名':<32}{'歌手':<22}{'来源':<12}{'音质':>8}")
        print("=" * 90)

        for i, song in enumerate(songs, 1):
            name = song.get("title", "") or song.get("name", "")
            artist = song.get("artist", "") or song.get("singer", "")
            src = song.get("source_name", song.get("source", "?"))

            # 截断过长文本
            name = name[:30] + ".." if len(name) > 32 else name
            artist = artist[:20] + ".." if len(artist) > 22 else artist

            quality = song.get("quality", "?")

            print(f"{i:<6}{name:<32}{artist:<22}{src:<12}{quality:>8}")

        print("=" * 90)

        while True:
            try:
                choice = input("\n请输入要下载的歌曲序号（输入 0 退出）：").strip()
                if choice == "0":
                    return -1
                choice_num = int(choice)
                if 1 <= choice_num <= len(songs):
                    return choice_num
                print(f"[!] 请输入 1 ~ {len(songs)} 之间的数字")
            except ValueError:
                print("[!] 请输入有效的数字")
            except KeyboardInterrupt:
                print("\n[!] 用户取消操作")
                return -1

    def get_detail(self, song):
        """根据歌曲来源获取详情（含下载链接）"""
        source = song.get("source", "")
        source_name = song.get("source_name", source)

        print(f"\n[*] 获取详情（{source_name}）...")

        detail = None
        if source == "migu":
            detail = self.api.get_migu_detail(song)
        elif source == "netease":
            detail = self.api.get_netease_detail(song)
        elif source == "qq":
            detail = self.api.get_qq_detail(song)
        elif source == "kuwo":
            detail = self.api.get_kuwo_detail(song)

        if detail and detail.get("audio_url"):
            print(f"    [✓] 获取到下载链接")
            print(f"    音质: {detail.get('quality', '?')}")
            return detail

        print(f"    [✗] 未获取到下载链接")
        return None

    def download_mp3(self, title, artist, audio_url, quality=""):
        """下载音乐文件"""
        safe_name = safe_filename(f"{artist} - {title}")
        # 根据音质选择扩展名
        if quality == "LOSSLESS":
            ext = audio_url.split("?")[0].rsplit(".", 1)[-1].lower() if "." in audio_url.split("?")[0] else "mp3"
        else:
            ext = "mp3"
        # 确保扩展名合法
        if ext not in ("mp3", "flac", "wav", "ape", "m4a", "ogg"):
            ext = "mp3"

        filename = f"{safe_name}.{ext}"
        filepath = os.path.join(DOWNLOAD_DIR, filename)

        print(f"\n[*] 开始下载：{filename}")

        try:
            resp = requests.get(audio_url, headers=HEADERS, stream=True,
                                timeout=120, verify=False)
            resp.raise_for_status()

            total_size = int(resp.headers.get("content-length", 0))
            if total_size > 0:
                print(f"    文件大小：{format_size(total_size)}")

            downloaded = 0
            with open(filepath, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        print_progress(downloaded, total_size)

            print(f"\n[✓] 下载完成！保存位置：{filepath}")
            return True

        except requests.RequestException as e:
            print(f"\n[✗] 下载失败：{e}")
            return False
        except IOError as e:
            print(f"\n[✗] 文件写入失败：{e}")
            return False

    def run(self):
        """主运行入口"""
        # 显示欢迎界面
        print("\n" + "=" * 60)
        print("     🎵  音乐下载器 v1.0  🎵")
        print("     多平台聚合 · requests + BeautifulSoup")
        print("     支持：咪咕 | 网易云 | QQ音乐 | 酷我")
        print("=" * 60)

        # BS4 教学演示
        self.bs4_demo.demo_bs4_api()
        print("\n" + "~" * 60)
        self.bs4_demo.scrape_musicdl_page()

        # 输入关键词
        print("\n" + "~" * 60)
        keyword = input("\n请输入要搜索的歌曲名：").strip()
        if not keyword:
            print("[!] 歌曲名不能为空，程序退出")
            return

        # 多平台搜索
        songs = self.search_all(keyword)
        if not songs:
            print("[!] 未找到相关歌曲，请更换关键词后重试")
            return

        # 选择歌曲
        choice = self.display_songs(songs)
        if choice == -1:
            print("[*] 退出程序")
            return

        selected = songs[choice - 1]
        title = selected.get("title") or selected.get("name", "")
        artist = selected.get("artist") or selected.get("singer", "")
        print(f"\n[*] 已选择：{title} - {artist}")

        # 获取详情（含下载链接）
        detail = self.get_detail(selected)
        if not detail:
            print("[✗] 无法获取下载链接，程序退出")
            return

        # 下载
        audio_url = detail["audio_url"]
        quality = detail.get("quality", "")
        title = detail.get("title", title)
        artist = detail.get("artist", artist)

        self.download_mp3(title, artist, audio_url, quality)

        # 完成
        print("\n" + "=" * 60)
        print(f"     下载任务完成，文件保存在 {DOWNLOAD_DIR}/ 目录")
        print("=" * 60)


# ===================== 程序入口 =====================

if __name__ == "__main__":
    downloader = MusicDownloader()
    downloader.run()