#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
多平台音乐搜索 & 详情 API
支持：咪咕 / 网易云 / QQ / 酷我
并发搜索：ThreadPoolExecutor 并行发起四个平台请求
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests
import urllib3

from utils import log, quality_from_url

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---- 常量 ----

HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "http://qjjlb.quanjian.com.cn/musicdl/",
}

TIMEOUT: int = 10
MAX_WORKERS: int = 10

# ---- 类型别名 ----

SongDict = dict[str, Any]

# ---- 工具 ----


def _get_json(url: str, params: dict | None = None, headers: dict | None = None,
              timeout: int = TIMEOUT, quiet: bool = False) -> Any:
    """发送 GET 请求并解析 JSON，失败返回 None"""
    try:
        resp = requests.get(
            url, headers=headers or HEADERS, params=params,
            timeout=timeout, verify=False,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        if not quiet:
            log.warning("请求失败 %s: %s", url, e)
        return None
    except json.JSONDecodeError:
        if not quiet:
            log.warning("非 JSON 响应: %s", url)
        return None


def _interleave(groups: dict[str, list[SongDict]],
                order: list[str]) -> list[SongDict]:
    """交错排列各平台结果，公平展示"""
    indices = {k: 0 for k in order}
    result: list[SongDict] = []
    global_idx = 0
    added = True
    while added:
        added = False
        for src in order:
            arr = groups[src]
            i = indices[src]
            if i < len(arr):
                song = arr[i]
                song["display_order"] = global_idx
                song["source_name"] = src
                result.append(song)
                global_idx += 1
                indices[src] += 1
                added = True
    return result

# ---- 各平台搜索 ----


def _search_migu(keyword: str, limit: int = 10) -> list[SongDict]:
    """搜索咪咕音乐"""
    url = "https://api.xcvts.cn/api/music/migu"
    data = _get_json(url, params={
        "gm": keyword, "n": "", "num": limit, "type": "json",
    })
    if not data or data.get("code") != 200 or not isinstance(data.get("data"), list):
        return []
    return [
        {
            "source": "migu", "title": item.get("title", ""),
            "artist": item.get("singer", ""), "index": item.get("n", 0),
            "cover": item.get("cover"), "keyword": keyword, "request_num": limit,
        }
        for item in data["data"]
    ]


def _search_netease(keyword: str, page: int = 1, num: int = 10) -> list[SongDict]:
    """搜索网易云音乐"""
    url = "https://api.vkeys.cn/v2/music/netease"
    data = _get_json(url, params={"word": keyword, "page": page, "num": num})
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        return []
    results: list[SongDict] = []
    for idx, item in enumerate(data["data"]):
        results.append({
            "source": "netease", "title": item.get("song", ""),
            "artist": item.get("singer", ""), "song_id": item.get("id"),
            "album": item.get("album", ""), "cover": item.get("cover"),
            "display_index": (page - 1) * num + idx + 1,
            "keyword": keyword,
        })
    return results


def _search_qq(keyword: str, limit: int = 10) -> list[SongDict]:
    """搜索QQ音乐"""
    url = "https://tang.api.s01s.cn/music_open_api.php"
    data = _get_json(url, params={"msg": keyword, "type": "json"})
    raw = data if isinstance(data, list) else (data or {}).get("data", [])
    if not isinstance(raw, list):
        return []
    results: list[SongDict] = []
    for idx, item in enumerate(raw[:limit]):
        mid = item.get("song_mid", "")
        if not mid:
            continue
        results.append({
            "source": "qq", "title": item.get("song_title", ""),
            "artist": item.get("singer_name", ""), "song_mid": mid,
            "qq_index": idx + 1, "display_index": idx + 1,
            "keyword": keyword, "qq_search_key": keyword, "cover": None,
        })
    return results


def _search_kuwo(keyword: str, limit: int = 10) -> list[SongDict]:
    """搜索酷我音乐"""
    url = "https://kw-api.cenguigui.cn/"
    data = _get_json(url, params={"name": keyword, "page": 1, "limit": limit})
    songs: list = []
    if isinstance(data, dict) and data.get("data"):
        raw = data["data"]
        if isinstance(raw, list):
            songs = raw
        elif isinstance(raw, dict):
            songs = raw.get("list", []) or raw.get("data", []) or []
    results: list[SongDict] = []
    for idx, item in enumerate(songs):
        rid = item.get("rid") or item.get("id") or item.get("musicrid", "")
        audio_url = item.get("url", "")
        results.append({
            "source": "kuwo", "title": item.get("name") or item.get("songname", ""),
            "artist": item.get("artist") or item.get("singer", ""),
            "rid": str(rid).replace("MUSIC_", ""),
            "display_index": idx + 1, "keyword": keyword,
            "cover": item.get("pic") or item.get("cover"),
            "audio_url": audio_url, "quality": quality_from_url(audio_url) if audio_url else "?",
        })
    return results

# ---- 各平台详情 ----


def _detail_migu(song: SongDict) -> SongDict | None:
    """获取咪咕歌曲详情（含下载链接）"""
    num = song.get("request_num", 20)
    url = "https://api.xcvts.cn/api/music/migu"
    data = _get_json(url, params={
        "gm": song["keyword"], "n": song.get("index", 1), "num": num, "type": "json",
    }, quiet=True)
    if not data or data.get("code") != 200:
        return None
    audio_url = data.get("music_url")
    return {
        "title": data.get("title") or song.get("title", ""),
        "artist": data.get("singer") or song.get("artist", ""),
        "cover": data.get("cover") or song.get("cover"),
        "audio_url": audio_url,
        "lrc_url": data.get("lrc_url"),
        "quality": quality_from_url(audio_url) if audio_url else "?",
    }


def _detail_netease(song: SongDict) -> SongDict | None:
    """获取网易云歌曲详情（含下载链接）"""
    song_id = song.get("song_id")
    if not song_id:
        return None
    meting_url = f"https://api.qijieya.cn/meting/?type=song&id={song_id}"
    data = _get_json(meting_url, quiet=True)
    if not isinstance(data, list) or not data:
        return None
    d = data[0]
    audio_url = d.get("url", "")
    return {
        "title": d.get("name") or song.get("title", ""),
        "artist": d.get("artist") or song.get("artist", ""),
        "cover": d.get("pic") or song.get("cover"),
        "audio_url": audio_url,
        "quality": quality_from_url(audio_url) if audio_url else "?",
    }


def _detail_qq(song: SongDict) -> SongDict | None:
    """获取QQ音乐歌曲详情（含下载链接）"""
    mid = song.get("song_mid")
    keyword = song.get("qq_search_key") or song.get("keyword", "")
    if not mid:
        return None
    url = "https://tang.api.s01s.cn/music_open_api.php"
    data = _get_json(url, params={"msg": keyword, "type": "json", "mid": mid}, quiet=True)
    if not isinstance(data, dict):
        return None
    audio_url = (
        data.get("song_play_url_sq") or data.get("song_play_url_pq")
        or data.get("song_play_url_hq") or data.get("song_play_url_standard")
        or data.get("song_play_url")
    )
    if not audio_url:
        return None
    return {
        "title": data.get("song_title") or song.get("title", ""),
        "artist": data.get("singer_name") or song.get("artist", ""),
        "cover": song.get("cover"),
        "audio_url": audio_url,
        "quality": quality_from_url(audio_url),
    }


def _detail_kuwo(song: SongDict) -> SongDict | None:
    """获取酷我音乐歌曲详情（含下载链接）"""
    audio_url = song.get("audio_url", "")
    if audio_url:
        return {
            "title": song.get("title", ""),
            "artist": song.get("artist", ""),
            "cover": song.get("cover"),
            "audio_url": audio_url,
            "quality": quality_from_url(audio_url),
        }
    # 备用方案：通过 rid 请求
    rid = song.get("rid", "")
    if not rid:
        return None
    detail_url = f"https://kw-api.cenguigui.cn?id={rid}&type=song&level=exhigh&format=mp3"
    try:
        resp = requests.get(detail_url, headers=HEADERS, timeout=TIMEOUT,
                            verify=False, allow_redirects=True)
        audio_url = ""
        if resp.status_code == 200:
            ct = resp.headers.get("content-type", "")
            if ct.startswith("audio"):
                audio_url = detail_url
            else:
                try:
                    j = resp.json()
                    audio_url = j.get("url") or j.get("play_url", "")
                    if isinstance(j.get("data"), dict):
                        audio_url = audio_url or j["data"].get("url", "")
                except json.JSONDecodeError:
                    pass
        if audio_url:
            return {
                "title": song.get("title", ""), "artist": song.get("artist", ""),
                "cover": song.get("cover"), "audio_url": audio_url,
                "quality": quality_from_url(audio_url),
            }
    except requests.RequestException:
        pass
    return None

# ---- 平台注册表 ----

_SEARCHERS: dict[str, tuple[str, callable]] = {
    "migu":    ("咪咕音乐",   _search_migu),
    "netease": ("网易云音乐", _search_netease),
    "qq":      ("QQ音乐",    _search_qq),
    "kuwo":    ("酷我音乐",   _search_kuwo),
}

_DETAILERS: dict[str, callable] = {
    "migu": _detail_migu, "netease": _detail_netease,
    "qq": _detail_qq, "kuwo": _detail_kuwo,
}

_DISPLAY_ORDER = ["咪咕音乐", "网易云音乐", "QQ音乐", "酷我音乐"]

# ---- 公共接口 ----


def search_all_platforms(keyword: str, max_workers: int = MAX_WORKERS) -> list[SongDict]:
    """
    并发搜索四个音乐平台，交错排列结果

    用 ThreadPoolExecutor 同时发起四个平台请求，
    总时间从 4-8 秒降到最慢平台约 2 秒。
    """
    log.info("并发搜索: %s", keyword)

    groups: dict[str, list[SongDict]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(fn, keyword): name
            for name, (_, fn) in _SEARCHERS.items()
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                results = future.result()
            except Exception:
                log.exception("搜索异常 [%s]", name)
                results = []
            groups[_SEARCHERS[name][0]] = results
            log.debug("  %s: %d 首", _SEARCHERS[name][0], len(results))

    # 补齐可能未完成的平台
    for _, display_name in _SEARCHERS.values():
        groups.setdefault(display_name, [])

    interleaved = _interleave(groups, _DISPLAY_ORDER)
    log.info("共找到 %d 首歌曲（交错排列）", len(interleaved))
    return interleaved


def prefetch_quality(songs: list[SongDict], max_workers: int = MAX_WORKERS) -> None:
    """
    并发预取各平台音质信息（酷我已有，只补咪咕/网易云/QQ）
    直接修改 songs 列表中元素的 quality 字段
    """
    targets = [
        (i, s) for i, s in enumerate(songs)
        if s.get("source") in ("migu", "netease", "qq")
        and not s.get("quality")
    ]
    if not targets:
        return

    log.info("预取音质信息（%d 首）...", len(targets))

    def _fetch_one(args: tuple[int, SongDict]) -> None:
        idx, song = args
        source = song.get("source")
        detail_fn = _DETAILERS.get(source)
        if not detail_fn:
            return
        try:
            detail = detail_fn(song)
            if detail and detail.get("quality"):
                songs[idx]["quality"] = detail["quality"]
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(executor.map(_fetch_one, targets))

    known = sum(1 for s in songs if s.get("quality") and s["quality"] != "?")
    log.info("音质预取完成（%d/%d 首已知）", known, len(songs))


def get_song_detail(song: SongDict) -> SongDict | None:
    """根据歌曲来源获取详情（含下载链接）"""
    source = song.get("source", "")
    detail_fn = _DETAILERS.get(source)
    if not detail_fn:
        log.warning("未知平台: %s", source)
        return None
    detail = detail_fn(song)
    if detail and detail.get("audio_url"):
        log.info("获取到下载链接: %s - %s", detail.get("artist"), detail.get("title"))
        return detail
    log.warning("未获取到下载链接")
    return None
