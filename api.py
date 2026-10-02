#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
多平台音乐搜索 & 详情 API
支持：咪咕 / 网易云 / QQ / 酷我
并发搜索：ThreadPoolExecutor 并行发起四个平台请求
"""

from __future__ import annotations

import json
import datetime
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
        log.warning("咪咕搜索失败: %s", (data or {}).get("message", "无响应"))
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
        log.warning("网易云搜索失败: 上游返回异常响应")
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
    if not isinstance(data, dict) or not isinstance(data.get("data"), (list, dict)):
        log.warning("酷我搜索失败: 上游返回异常响应（%s）",
                    "空/非 JSON 响应" if data is None else f"data 字段类型 {type(data.get('data')).__name__}")
        return []
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
        "album": data.get("album") or data.get("album_name") or song.get("album", ""),
        "year": str(data.get("year") or data.get("publish_year") or ""),
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
    detail: SongDict = {
        "title": d.get("name") or song.get("title", ""),
        "artist": d.get("artist") or song.get("artist", ""),
        "album": song.get("album", "") or d.get("album", ""),
        "year": "",
        "cover": d.get("pic") or song.get("cover"),
        "audio_url": audio_url,
        # Meting 标准响应的 lrc 字段为歌词链接
        "lrc_url": d.get("lrc") or None,
        "quality": quality_from_url(audio_url) if audio_url else "?",
    }
    # 网易云官方详情补全专辑名/发行年份（失败不影响主流程）
    if song_id:
        extra = _netease_extra(song_id)
        if extra:
            detail["album"] = detail["album"] or extra.get("album", "")
            detail["year"] = extra.get("year", "") or detail["year"]
            detail["cover"] = detail["cover"] or extra.get("cover")
    return detail


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
        if data.get("vip") == "付费":
            log.info("QQ 付费歌曲无下载链接: %s", data.get("song_title") or song.get("title"))
        return None
    return {
        "title": data.get("song_title") or song.get("title", ""),
        "artist": data.get("singer_name") or song.get("artist", ""),
        "album": data.get("album_name") or song.get("album", ""),
        "year": str(data.get("publish_time") or data.get("year") or ""),
        "cover": data.get("song_cover") or data.get("cover") or song.get("cover"),
        "audio_url": audio_url,
        "lrc_url": data.get("lrc_url") or data.get("song_lrc") or None,
        "quality": quality_from_url(audio_url),
    }


def _detail_kuwo(song: SongDict) -> SongDict | None:
    """获取酷我音乐歌曲详情（含下载链接）"""
    audio_url = song.get("audio_url", "")
    if audio_url:
        return {
            "title": song.get("title", ""),
            "artist": song.get("artist", ""),
            "album": song.get("album", ""),
            "year": str(song.get("year", "") or ""),
            "cover": song.get("cover"),
            "audio_url": audio_url,
            "lrc_url": song.get("lrc_url"),
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
                "album": song.get("album", ""),
                "year": str(song.get("year", "") or ""),
                "cover": song.get("cover"), "audio_url": audio_url,
                "lrc_url": song.get("lrc_url"),
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

# 平台显示名列表（供 GUI 平台筛选下拉使用）
PLATFORM_NAMES: tuple[str, ...] = tuple(_DISPLAY_ORDER)

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


def _norm_key(s: Any) -> str:
    """标题/歌手一致性比较用归一化：小写 + 去空白"""
    return "".join(str(s or "").split()).lower()


# ---- 版本识别（元数据验证，避免伴奏/错误版本）----

# 高置信：伴奏/无人声版本，搜索目标本身不含该标记时直接拦截
BAD_VERSION_MARKERS: tuple[str, ...] = (
    "伴奏", "无人声", "纯伴奏", "消音", "instrumental", "karaoke", "ktv伴奏",
    "off vocal", "offvocal", "inst.", "(inst)", "（inst",
)
# 低置信：翻唱/现场/剪辑等变体，标记提示但允许用户自行决定
VARIANT_VERSION_MARKERS: tuple[str, ...] = (
    "翻唱", "cover", "live", "现场", "演唱会", "remix", "dj版", "铃声",
    "片段", "剪辑", "节选", "cover版", "女声版", "男声版", "钢琴版",
)


def _find_marker(title: str, markers: tuple[str, ...]) -> str:
    t = (title or "").lower()
    for m in markers:
        if m in t:
            return m
    return ""


def detect_version_risk(candidate_title: str, base_title: str = "") -> tuple[str, str]:
    """识别候选音源相对搜索目标的版本风险。

    返回 (level, marker)：
      ("bad", 标记)     疑似伴奏/纯音乐等错误版本
      ("variant", 标记) 翻唱/现场/剪辑等变体
      ("", "")          未发现风险
    仅当标记出现在候选标题、而搜索目标本身不含该标记时才告警，
    用户主动搜索“XX 伴奏”不会被误杀。
    """
    cand = str(candidate_title or "")
    base = str(base_title or "")
    marker = _find_marker(cand, BAD_VERSION_MARKERS)
    if marker and marker not in base.lower():
        return "bad", marker
    marker = _find_marker(cand, VARIANT_VERSION_MARKERS)
    if marker and marker not in base.lower():
        return "variant", marker
    return "", ""


def resolve_song(song: SongDict) -> SongDict | None:
    """解析音源（含下载链接/音质/版本标记），不拦截任何版本，供试听与预取使用。

    返回的 detail 额外带：
      version_tag:   "bad" | "variant" | ""
      version_label: 触发的标记词（可空）
    """
    source = song.get("source", "")
    detail_fn = _DETAILERS.get(source)
    if not detail_fn:
        log.warning("未知平台: %s", source)
        return None
    detail = detail_fn(song)
    if not detail or not detail.get("audio_url"):
        log.warning("未获取到下载链接")
        return None
    # 一致性校验：详情标题与搜索项完全不同才视为错误歌曲；
    # 一方为另一方前缀/子串视为一致（部分平台 detail 的 song_title 为截短版）
    st = _norm_key(song.get("title") or song.get("name"))
    dt = _norm_key(detail.get("title"))
    if st and dt and not (st.startswith(dt) or dt.startswith(st)):
        log.warning("详情与搜索项不一致（%s ≠ %s），已丢弃", detail.get("title"), song.get("title"))
        return None
    # 歌手缺失时回填搜索项，保证下载文件与列表展示一致
    if not detail.get("artist"):
        detail["artist"] = song.get("artist", "") or song.get("singer", "")
    # 专辑/年份/封面/歌词链接：详情没给时用搜索项回填
    for key in ("album", "year", "cover", "lrc_url"):
        if not detail.get(key) and song.get(key):
            detail[key] = song[key]
    # 版本识别：以详情标题为准，对照搜索目标
    level, marker = detect_version_risk(
        detail.get("title") or "", song.get("title") or song.get("name") or ""
    )
    detail["version_tag"] = level
    detail["version_label"] = marker
    log.info("获取到下载链接: %s - %s%s",
             detail.get("artist"), detail.get("title"),
             f"（{marker}）" if marker else "")
    return detail


def get_song_detail(song: SongDict) -> SongDict | None:
    """根据歌曲来源获取详情（含下载链接）；疑似伴奏/纯音乐版本直接拦截。"""
    detail = resolve_song(song)
    if detail and detail.get("version_tag") == "bad":
        log.warning("疑似伴奏/无人声音源（%s），已拦截: %s",
                    detail.get("version_label"), detail.get("title"))
        return None
    return detail


# ---- 歌词 & 发行信息补全 ----

_NETEASE_HEADERS: dict[str, str] = {**HEADERS, "Referer": "https://music.163.com/"}


def _get_text(url: str, params: dict | None = None,
              headers: dict | None = None, timeout: int = 8) -> str | None:
    """GET 纯文本（lrc 用），失败返回 None。"""
    try:
        resp = requests.get(
            url, headers=headers or HEADERS, params=params,
            timeout=timeout, verify=False,
        )
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text
    except requests.RequestException:
        return None


def _netease_extra(song_id: Any) -> SongDict | None:
    """网易云官方歌曲详情：专辑名 / 发行年份 / 封面。"""
    url = f"https://music.163.com/api/song/detail/?ids=%5B{song_id}%5D"
    data = _get_json(url, headers=_NETEASE_HEADERS, timeout=6, quiet=True)
    try:
        info = data["songs"][0]
        album = info.get("al") or info.get("album") or {}
        # publishTime 为毫秒时间戳（个别专辑为脏数据如 9992678400000），
        # 统一换算并校验年份范围
        year = ""
        try:
            ts = int(album.get("publishTime") or 0)
            if ts > 0:
                if ts < 10_000_000_000:      # 秒级时间戳兜底
                    ts *= 1000
                y = datetime.datetime.fromtimestamp(ts / 1000,
                                                     datetime.timezone.utc).year
                if 1900 <= y <= 2100:
                    year = str(y)
        except (TypeError, ValueError, OSError, OverflowError):
            year = ""
        cover = ""
        pics = album.get("picUrl") or (info.get("al") or {}).get("picUrl")
        if pics:
            cover = str(pics)
        return {
            "album": album.get("name", ""),
            "year": year,
            "cover": cover,
        }
    except (KeyError, IndexError, TypeError):
        return None


def _netease_lyrics_by_id(song_id: Any) -> str | None:
    """按网易云歌曲 ID 取同步歌词原文。"""
    url = "https://music.163.com/api/song/lyric"
    data = _get_json(url, params={"id": song_id, "lv": 1, "kv": 1, "tv": -1},
                     headers=_NETEASE_HEADERS, timeout=8, quiet=True)
    if isinstance(data, dict):
        lrc = data.get("lrc") or {}
        text = lrc.get("lyric")
        if text and text.strip():
            return text
    return None


def _netease_search_lyric(title: str, artist: str = "") -> str | None:
    """跨平台兜底：在网易云按“歌名 歌手”检索后取歌词。"""
    kw = f"{title} {artist}".strip()
    if not kw:
        return None
    search = _get_json(
        "https://music.163.com/api/search/get/web",
        params={"s": kw, "type": 1, "limit": 3, "offset": 0},
        headers=_NETEASE_HEADERS, timeout=8, quiet=True,
    )
    try:
        songs = search["result"]["songs"]
    except (KeyError, TypeError):
        return None
    for item in songs or []:
        # 歌名匹配才用，避免拿到同名错误版本
        if _norm_key(title) and _norm_key(title) not in _norm_key(item.get("name")):
            if _norm_key(item.get("name")) not in _norm_key(title):
                continue
        text = _netease_lyrics_by_id(item.get("id"))
        if text:
            return text
    return None


def _lrclib_lyrics(title: str, artist: str = "",
                   album: str = "") -> str | None:
    """lrclib.net 免费歌词库：优先精确匹配，再退化到搜索。"""
    if not title:
        return None
    headers = {**_HEADERS, "Accept": "application/json"}

    def _pick(item: dict) -> str | None:
        if not isinstance(item, dict):
            return None
        return item.get("syncedLyrics") or item.get("plainLyrics")

    data = _get_json(
        "https://lrclib.net/api/get",
        params={"artist_name": artist, "track_name": title,
                "album_name": album, "duration": 0},
        headers=headers, timeout=8, quiet=True,
    )
    text = _pick(data)
    if text:
        return text
    items = _get_json(
        "https://lrclib.net/api/search",
        params={"track_name": title, "artist_name": artist},
        headers=headers, timeout=8, quiet=True,
    )
    if isinstance(items, list):
        for item in items[:5]:
            text = _pick(item)
            if text:
                return text
    return None


def fetch_lyrics(meta: SongDict) -> str | None:
    """按优先级获取 LRC 歌词文本，全部失败返回 None。

    meta 可用键：lyrics（现成文本）/ lrc_url / source / song_id /
                 title / artist / album
    """
    meta = meta or {}
    text = str(meta.get("lyrics", "") or "").strip()
    if text:
        return text

    # 1) 平台直出歌词链接
    lrc_url = meta.get("lrc_url")
    if lrc_url:
        text = _get_text(str(lrc_url))
        if text and "[" in text:
            return text.strip()

    # 2) 网易云 ID 直取
    if meta.get("source") == "netease" and meta.get("song_id"):
        text = _netease_lyrics_by_id(meta["song_id"])
        if text:
            return text

    title = str(meta.get("title", "") or "").strip()
    artist = str(meta.get("artist", "") or "").strip()
    album = str(meta.get("album", "") or "").strip()

    # 3) 网易云模糊检索（对其他平台的歌同样适用，中文歌词覆盖最好）
    text = _netease_search_lyric(title, artist)
    if text:
        return text

    # 4) lrclib 兜底
    return _lrclib_lyrics(title, artist, album)


def strip_lrc_timestamps(lrc: str) -> str:
    """把 LRC 时间轴标签去掉，返回纯文本歌词（供预览窗口阅读）。"""
    import re as _re
    if not lrc:
        return ""
    line_re = _re.compile(r"\[\d{1,2}:\d{2}(?:[.:]\d{1,3})?\]")
    tag_re = _re.compile(r"\[(?:ti|ar|al|by|offset|length|re|ve):[^\]]*\]", _re.I)
    out: list[str] = []
    for raw in lrc.splitlines():
        line = tag_re.sub("", raw)
        line = line_re.sub("", line).strip()
        if line:
            out.append(line)
    # 去重相邻重复行（逐字歌词常见）
    deduped: list[str] = []
    for line in out:
        if not deduped or deduped[-1] != line:
            deduped.append(line)
    return "\n".join(deduped)
