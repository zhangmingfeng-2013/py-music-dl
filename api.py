#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""多平台音乐搜索与详情 API。

支持平台
    咪咕音乐 / 网易云音乐 / QQ 音乐 / 酷我音乐

对外接口
    * :func:`search_all_platforms` —— 四平台并发搜索，结果交错排列
    * :func:`prefetch_quality` —— 并发回填音质
    * :func:`resolve_song` —— 解析真实下载链接（不做版本拦截）
    * :func:`get_song_detail` —— 解析下载链接并拦截高置信伴奏版本
    * :func:`fetch_lyrics` —— 四级歌词兜底
    * :func:`detect_version_risk` —— 伴奏 / 翻唱版本识别
    * :func:`strip_lrc_timestamps` —— LRC 转纯文本

上游均为第三方聚合接口，返回结构不稳定。本模块对所有响应做类型校验，
单个平台异常只会退化为空结果，不影响其余平台与主流程。
"""

from __future__ import annotations

import datetime
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Final

import requests
import urllib3

from utils import USER_AGENT, log, quality_from_url

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

HEADERS: Final[dict[str, str]] = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "http://qjjlb.quanjian.com.cn/musicdl/",
}

TIMEOUT: Final = 10
MAX_WORKERS: Final = 10

SongDict = dict[str, Any]

#: 平台显示顺序（同时用于结果交错与 GUI 平台筛选）
_DISPLAY_ORDER: Final[tuple[str, ...]] = (
    "咪咕音乐", "网易云音乐", "QQ音乐", "酷我音乐",
)
PLATFORM_NAMES: Final[tuple[str, ...]] = _DISPLAY_ORDER

# 高置信：伴奏/无人声版本，搜索目标本身不含该标记时直接拦截
BAD_VERSION_MARKERS: Final[tuple[str, ...]] = (
    "伴奏", "无人声", "纯伴奏", "消音", "instrumental", "karaoke", "ktv伴奏",
    "off vocal", "offvocal", "inst.", "(inst)", "（inst",
)
# 低置信：翻唱/现场/剪辑等变体，标记提示但允许用户自行决定
VARIANT_VERSION_MARKERS: Final[tuple[str, ...]] = (
    "翻唱", "cover", "live", "现场", "演唱会", "remix", "dj版", "铃声",
    "片段", "剪辑", "节选", "cover版", "女声版", "男声版", "钢琴版",
)

_LRC_LINE_RE: Final = re.compile(r"\[\d{1,2}:\d{2}(?:[.:]\d{1,3})?\]")
_LRC_META_RE: Final = re.compile(
    r"\[(?:ti|ar|al|by|offset|length|re|ve):[^\]]*\]", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# HTTP 与响应校验
# ---------------------------------------------------------------------------


def _get_json(url: str, params: dict[str, Any] | None = None,
              headers: dict[str, str] | None = None,
              timeout: int = TIMEOUT, quiet: bool = False) -> Any:
    """GET 请求并解析 JSON；网络/解析失败返回 ``None``。"""
    try:
        response = requests.get(
            url, headers=headers or HEADERS, params=params,
            timeout=timeout, verify=False,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        if not quiet:
            log.warning("请求失败 %s: %s", url, exc)
        return None
    except json.JSONDecodeError:
        if not quiet:
            log.warning("非 JSON 响应: %s", url)
        return None


def _get_text(url: str, params: dict[str, Any] | None = None,
              headers: dict[str, str] | None = None,
              timeout: int = 8) -> str | None:
    """GET 纯文本（歌词），失败返回 ``None``。"""
    try:
        response = requests.get(
            url, headers=headers or HEADERS, params=params,
            timeout=timeout, verify=False,
        )
        response.raise_for_status()
        response.encoding = response.apparent_encoding or "utf-8"
        return response.text
    except requests.RequestException:
        return None


def _as_dict(value: Any) -> dict[str, Any]:
    """类型安全地收窄为 dict，供上游响应解析使用。"""
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    """类型安全地收窄为 list。"""
    return value if isinstance(value, list) else []


def _pick_text(value: Any) -> str:
    """把上游字段归一化为字符串；``None`` → 空串。"""
    return "" if value is None else str(value)


# ---------------------------------------------------------------------------
# 搜索结果交错
# ---------------------------------------------------------------------------


def _interleave(groups: dict[str, list[SongDict]],
                order: list[str] | tuple[str, ...]) -> list[SongDict]:
    """按平台轮流取一条，交错排列，保证各平台曝光公平。"""
    indices = {name: 0 for name in order}
    result: list[SongDict] = []
    display_order = 0
    added = True
    while added:
        added = False
        for source_name in order:
            songs = groups.get(source_name, [])
            index = indices[source_name]
            if index >= len(songs):
                continue
            song = songs[index]
            song["display_order"] = display_order
            song["source_name"] = source_name
            result.append(song)
            display_order += 1
            indices[source_name] = index + 1
            added = True
    return result


# ---------------------------------------------------------------------------
# 各平台搜索
# ---------------------------------------------------------------------------


def _search_migu(keyword: str, limit: int = 10) -> list[SongDict]:
    """搜索咪咕音乐。"""
    data = _get_json(
        "https://api.xcvts.cn/api/music/migu",
        params={"gm": keyword, "n": "", "num": limit, "type": "json"},
    )
    if not isinstance(data, dict) or data.get("code") != 200:
        message = _as_dict(data).get("message", "无响应")
        log.warning("咪咕搜索失败: %s", message)
        return []
    items = _as_list(data.get("data"))
    results: list[SongDict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        results.append({
            "source": "migu",
            "title": _pick_text(item.get("title")),
            "artist": _pick_text(item.get("singer")),
            "index": item.get("n", 0),
            "cover": item.get("cover"),
            "keyword": keyword,
            "request_num": limit,
        })
    return results


def _search_netease(keyword: str, page: int = 1, num: int = 10) -> list[SongDict]:
    """搜索网易云音乐。"""
    data = _get_json(
        "https://api.vkeys.cn/v2/music/netease",
        params={"word": keyword, "page": page, "num": num},
    )
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        log.warning("网易云搜索失败: 上游返回异常响应")
        return []
    results: list[SongDict] = []
    for index, item in enumerate(data["data"]):
        if not isinstance(item, dict):
            continue
        results.append({
            "source": "netease",
            "title": _pick_text(item.get("song")),
            "artist": _pick_text(item.get("singer")),
            "song_id": item.get("id"),
            "album": _pick_text(item.get("album")),
            "cover": item.get("cover"),
            "display_index": (page - 1) * num + index + 1,
            "keyword": keyword,
        })
    return results


def _search_qq(keyword: str, limit: int = 10) -> list[SongDict]:
    """搜索 QQ 音乐。"""
    data = _get_json(
        "https://tang.api.s01s.cn/music_open_api.php",
        params={"msg": keyword, "type": "json"},
    )
    raw = data if isinstance(data, list) else _as_dict(data).get("data", [])
    items = _as_list(raw)
    results: list[SongDict] = []
    for index, item in enumerate(items[:limit]):
        if not isinstance(item, dict):
            continue
        mid = _pick_text(item.get("song_mid"))
        if not mid:
            continue
        results.append({
            "source": "qq",
            "title": _pick_text(item.get("song_title")),
            "artist": _pick_text(item.get("singer_name")),
            "song_mid": mid,
            "qq_index": index + 1,
            "display_index": index + 1,
            "keyword": keyword,
            "qq_search_key": keyword,
            "cover": None,
        })
    return results


def _kuwo_song_list(data: Any) -> list[Any]:
    """从酷我响应的多种嵌套结构中提取歌曲列表。"""
    payload = _as_dict(data).get("data")
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        nested = payload.get("list") or payload.get("data") or []
        return _as_list(nested)
    return []


def _search_kuwo(keyword: str, limit: int = 10) -> list[SongDict]:
    """搜索酷我音乐。"""
    data = _get_json(
        "https://kw-api.cenguigui.cn/",
        params={"name": keyword, "page": 1, "limit": limit},
    )
    if not isinstance(data, dict) or not isinstance(data.get("data"), (list, dict)):
        reason = "空/非 JSON 响应" if data is None else (
            f"data 字段类型 {type(_as_dict(data).get('data')).__name__}"
        )
        log.warning("酷我搜索失败: 上游返回异常响应（%s）", reason)
        return []

    results: list[SongDict] = []
    for index, item in enumerate(_kuwo_song_list(data)):
        if not isinstance(item, dict):
            continue
        rid = item.get("rid") or item.get("id") or item.get("musicrid", "")
        audio_url = item.get("url", "")
        results.append({
            "source": "kuwo",
            "title": _pick_text(item.get("name") or item.get("songname")),
            "artist": _pick_text(item.get("artist") or item.get("singer")),
            "rid": _pick_text(rid).replace("MUSIC_", ""),
            "display_index": index + 1,
            "keyword": keyword,
            "cover": item.get("pic") or item.get("cover"),
            "audio_url": audio_url,
            "quality": quality_from_url(audio_url) if audio_url else "?",
        })
    return results


# ---------------------------------------------------------------------------
# 各平台详情
# ---------------------------------------------------------------------------


def _detail_migu(song: SongDict) -> SongDict | None:
    """获取咪咕歌曲详情（含下载链接）。"""
    keyword = song.get("keyword")
    if not keyword:
        return None
    data = _get_json(
        "https://api.xcvts.cn/api/music/migu",
        params={
            "gm": keyword,
            "n": song.get("index", 1),
            "num": song.get("request_num", 20),
            "type": "json",
        },
        quiet=True,
    )
    if not isinstance(data, dict) or data.get("code") != 200:
        return None
    audio_url = data.get("music_url")
    return {
        "title": _pick_text(data.get("title") or song.get("title")),
        "artist": _pick_text(data.get("singer") or song.get("artist")),
        "album": _pick_text(
            data.get("album") or data.get("album_name") or song.get("album")
        ),
        "year": _pick_text(data.get("year") or data.get("publish_year")),
        "cover": data.get("cover") or song.get("cover"),
        "audio_url": audio_url,
        "lrc_url": data.get("lrc_url"),
        "quality": quality_from_url(audio_url) if audio_url else "?",
    }


def _detail_netease(song: SongDict) -> SongDict | None:
    """获取网易云歌曲详情（含下载链接）。"""
    song_id = song.get("song_id")
    if not song_id:
        return None
    data = _get_json(
        f"https://api.qijieya.cn/meting/?type=song&id={song_id}", quiet=True
    )
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return None
    item = data[0]
    audio_url = item.get("url", "")
    detail: SongDict = {
        "title": _pick_text(item.get("name") or song.get("title")),
        "artist": _pick_text(item.get("artist") or song.get("artist")),
        "album": _pick_text(song.get("album") or item.get("album")),
        "year": "",
        "cover": item.get("pic") or song.get("cover"),
        "audio_url": audio_url,
        # Meting 标准响应的 lrc 字段为歌词链接
        "lrc_url": item.get("lrc") or None,
        "quality": quality_from_url(audio_url) if audio_url else "?",
    }
    # 网易云官方详情补全专辑名/发行年份（失败不影响主流程）
    extra = _netease_extra(song_id)
    if extra:
        detail["album"] = detail["album"] or extra.get("album", "")
        detail["year"] = extra.get("year", "") or detail["year"]
        detail["cover"] = detail["cover"] or extra.get("cover")
    return detail


def _detail_qq(song: SongDict) -> SongDict | None:
    """获取 QQ 音乐歌曲详情（含下载链接）。"""
    mid = song.get("song_mid")
    if not mid:
        return None
    keyword = song.get("qq_search_key") or song.get("keyword", "")
    data = _get_json(
        "https://tang.api.s01s.cn/music_open_api.php",
        params={"msg": keyword, "type": "json", "mid": mid},
        quiet=True,
    )
    if not isinstance(data, dict):
        return None
    audio_url = (
        data.get("song_play_url_sq") or data.get("song_play_url_pq")
        or data.get("song_play_url_hq") or data.get("song_play_url_standard")
        or data.get("song_play_url")
    )
    if not audio_url:
        if data.get("vip") == "付费":
            log.info("QQ 付费歌曲无下载链接: %s",
                     data.get("song_title") or song.get("title"))
        return None
    return {
        "title": _pick_text(data.get("song_title") or song.get("title")),
        "artist": _pick_text(data.get("singer_name") or song.get("artist")),
        "album": _pick_text(data.get("album_name") or song.get("album")),
        "year": _pick_text(data.get("publish_time") or data.get("year")),
        "cover": data.get("song_cover") or data.get("cover") or song.get("cover"),
        "audio_url": audio_url,
        "lrc_url": data.get("lrc_url") or data.get("song_lrc") or None,
        "quality": quality_from_url(audio_url),
    }


def _kuwo_detail_payload(data: Any) -> str:
    """从酷我详情响应中提取音频地址。"""
    if not isinstance(data, dict):
        return ""
    audio_url = data.get("url") or data.get("play_url", "")
    nested = _as_dict(data.get("data")).get("url", "")
    return audio_url or nested


def _detail_kuwo(song: SongDict) -> SongDict | None:
    """获取酷我音乐歌曲详情（含下载链接）。"""
    audio_url = song.get("audio_url", "")
    if not audio_url:
        rid = song.get("rid", "")
        if not rid:
            return None
        detail_url = (
            f"https://kw-api.cenguigui.cn?id={rid}&type=song"
            "&level=exhigh&format=mp3"
        )
        try:
            response = requests.get(
                detail_url, headers=HEADERS, timeout=TIMEOUT,
                verify=False, allow_redirects=True,
            )
        except requests.RequestException:
            return None
        if response.status_code == 200:
            content_type = response.headers.get("content-type", "")
            if content_type.startswith("audio"):
                audio_url = detail_url
            else:
                try:
                    audio_url = _kuwo_detail_payload(response.json())
                except (json.JSONDecodeError, ValueError):
                    audio_url = ""
        if not audio_url:
            return None
    return {
        "title": _pick_text(song.get("title")),
        "artist": _pick_text(song.get("artist")),
        "album": _pick_text(song.get("album")),
        "year": _pick_text(song.get("year")),
        "cover": song.get("cover"),
        "audio_url": audio_url,
        "lrc_url": song.get("lrc_url"),
        "quality": quality_from_url(audio_url),
    }


# ---------------------------------------------------------------------------
# 平台注册表
# ---------------------------------------------------------------------------

Searcher = Callable[[str], list[SongDict]]
Detailer = Callable[[SongDict], SongDict | None]

_SEARCHERS: Final[dict[str, tuple[str, Searcher]]] = {
    "migu": ("咪咕音乐", _search_migu),
    "netease": ("网易云音乐", _search_netease),
    "qq": ("QQ音乐", _search_qq),
    "kuwo": ("酷我音乐", _search_kuwo),
}

_DETAILERS: Final[dict[str, Detailer]] = {
    "migu": _detail_migu,
    "netease": _detail_netease,
    "qq": _detail_qq,
    "kuwo": _detail_kuwo,
}


# ---------------------------------------------------------------------------
# 公共接口：搜索与音质预取
# ---------------------------------------------------------------------------


def search_all_platforms(keyword: str,
                         max_workers: int = MAX_WORKERS) -> list[SongDict]:
    """并发搜索四个平台，并按平台交错排列结果。

    单平台失败只记录日志并退化为空列表，不影响其他平台；总耗时约等于
    最慢平台的响应时间。
    """
    log.info("并发搜索: %s", keyword)

    groups: dict[str, list[SongDict]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(searcher, keyword): platform
            for platform, (_display, searcher) in _SEARCHERS.items()
        }
        for future in as_completed(futures):
            platform = futures[future]
            display_name = _SEARCHERS[platform][0]
            try:
                results = future.result()
            except Exception:  # noqa: BLE001  单平台异常不得中断整体搜索
                log.exception("搜索异常 [%s]", display_name)
                results = []
            groups[display_name] = results
            log.debug("  %s: %d 首", display_name, len(results))

    # 补齐未返回结果的平台（防御性：正常路径下 as_completed 已覆盖）
    for _platform, display_name in _SEARCHERS.values():
        groups.setdefault(display_name, [])

    interleaved = _interleave(groups, _DISPLAY_ORDER)
    log.info("共找到 %d 首歌曲（交错排列）", len(interleaved))
    return interleaved


def prefetch_quality(songs: list[SongDict],
                     max_workers: int = MAX_WORKERS) -> None:
    """并发预取音质信息，直接回填 ``songs`` 元素的 ``quality`` 字段。

    酷我搜索结果已带音质；咪咕/网易云/QQ 需要请求详情后才能判断。
    任一详情失败都保持原值，不阻塞其他歌曲。
    """
    targets = [
        (index, song) for index, song in enumerate(songs)
        if song.get("source") in ("migu", "netease", "qq")
        and not song.get("quality")
    ]
    if not targets:
        return

    log.info("预取音质信息（%d 首）...", len(targets))

    def fetch_one(target: tuple[int, SongDict]) -> None:
        index, song = target
        detail_fn = _DETAILERS.get(str(song.get("source", "")))
        if detail_fn is None:
            return
        try:
            detail = detail_fn(song)
        except Exception:  # noqa: BLE001  单首失败不影响预取批次
            log.debug("音质预取失败: %s", song.get("title"), exc_info=True)
            return
        if isinstance(detail, dict) and detail.get("quality"):
            songs[index]["quality"] = detail["quality"]

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(executor.map(fetch_one, targets))

    known = sum(
        1 for song in songs
        if song.get("quality") and song["quality"] != "?"
    )
    log.info("音质预取完成（%d/%d 首已知）", known, len(songs))


# ---------------------------------------------------------------------------
# 版本识别
# ---------------------------------------------------------------------------


def _norm_key(value: Any) -> str:
    """标题/歌手一致性比较用归一化：小写 + 去空白。"""
    return "".join(str(value or "").split()).lower()


def _find_marker(title: str, markers: tuple[str, ...]) -> str:
    """返回标题中命中的第一个标记词，未命中返回空串。"""
    lowered = (title or "").lower()
    for marker in markers:
        if marker in lowered:
            return marker
    return ""


def detect_version_risk(candidate_title: str,
                        base_title: str = "") -> tuple[str, str]:
    """识别候选音源相对搜索目标的版本风险。

    Returns:
        ``(level, marker)``：

        * ``("bad", 标记)`` —— 疑似伴奏/纯音乐等错误版本
        * ``("variant", 标记)`` —— 翻唱/现场/剪辑等变体
        * ``("", "")`` —— 未发现风险

    仅当标记出现在候选标题、而搜索目标本身不含该标记时才告警，
    因此用户主动搜索「XX 伴奏」不会被误杀。
    """
    candidate = str(candidate_title or "")
    base = str(base_title or "").lower()

    marker = _find_marker(candidate, BAD_VERSION_MARKERS)
    if marker and marker not in base:
        return "bad", marker

    marker = _find_marker(candidate, VARIANT_VERSION_MARKERS)
    if marker and marker not in base:
        return "variant", marker
    return "", ""


def _titles_consistent(search_title: Any, detail_title: Any) -> bool:
    """详情标题与搜索标题是否指向同一首歌。

    一方为另一方的前缀/子串即视为一致：部分平台详情返回截短标题，
    完全相同的字符串必然满足该规则。
    """
    search_key = _norm_key(search_title)
    detail_key = _norm_key(detail_title)
    if not search_key or not detail_key:
        return True
    return search_key.startswith(detail_key) or detail_key.startswith(search_key)


def _backfill_detail(detail: SongDict, song: SongDict) -> None:
    """用搜索项补齐详情缺失的歌手/专辑/年份/封面/歌词链接。"""
    if not detail.get("artist"):
        detail["artist"] = song.get("artist", "") or song.get("singer", "")
    for key in ("album", "year", "cover", "lrc_url"):
        if not detail.get(key) and song.get(key):
            detail[key] = song[key]


def resolve_song(song: SongDict) -> SongDict | None:
    """解析音源（下载链接 / 音质 / 版本标记），不拦截任何版本。

    供试听与音质预取使用。返回的详情额外带：

    * ``version_tag``：``"bad"`` / ``"variant"`` / ``""``
    * ``version_label``：触发的标记词（可空）
    """
    source = str(song.get("source", ""))
    detail_fn = _DETAILERS.get(source)
    if detail_fn is None:
        log.warning("未知平台: %s", source)
        return None

    try:
        detail = detail_fn(song)
    except Exception:  # noqa: BLE001  详情解析失败按无结果处理
        log.exception("获取详情异常: %s", song.get("title"))
        return None
    if not isinstance(detail, dict) or not detail.get("audio_url"):
        log.warning("未获取到下载链接")
        return None

    if not _titles_consistent(
        song.get("title") or song.get("name"), detail.get("title")
    ):
        log.warning("详情与搜索项不一致（%s ≠ %s），已丢弃",
                    detail.get("title"), song.get("title"))
        return None

    _backfill_detail(detail, song)

    level, marker = detect_version_risk(
        str(detail.get("title") or ""), str(song.get("title") or song.get("name") or "")
    )
    detail["version_tag"] = level
    detail["version_label"] = marker
    log.info("获取到下载链接: %s - %s%s",
             detail.get("artist"), detail.get("title"),
             f"（{marker}）" if marker else "")
    return detail


def get_song_detail(song: SongDict) -> SongDict | None:
    """获取下载详情；疑似伴奏/无人声版本直接拦截。"""
    detail = resolve_song(song)
    if detail and detail.get("version_tag") == "bad":
        log.warning("疑似伴奏/无人声音源（%s），已拦截: %s",
                    detail.get("version_label"), detail.get("title"))
        return None
    return detail


# ---------------------------------------------------------------------------
# 歌词与发行信息补全
# ---------------------------------------------------------------------------

_NETEASE_HEADERS: Final[dict[str, str]] = {**HEADERS, "Referer": "https://music.163.com/"}


def _netease_extra(song_id: Any) -> SongDict | None:
    """网易云官方歌曲详情：专辑名 / 发行年份 / 封面。"""
    data = _get_json(
        f"https://music.163.com/api/song/detail/?ids=%5B{song_id}%5D",
        headers=_NETEASE_HEADERS, timeout=6, quiet=True,
    )
    songs = _as_list(_as_dict(data).get("songs"))
    if not songs or not isinstance(songs[0], dict):
        return None
    info = songs[0]
    album = _as_dict(info.get("al") or info.get("album"))

    # publishTime 为毫秒时间戳（个别专辑为脏数据如 9992678400000），
    # 统一换算并校验年份范围
    year = ""
    try:
        timestamp = int(album.get("publishTime") or 0)
        if timestamp > 0:
            if timestamp < 10_000_000_000:      # 秒级时间戳兜底
                timestamp *= 1000
            value = datetime.datetime.fromtimestamp(
                timestamp / 1000, datetime.timezone.utc
            ).year
            if 1900 <= value <= 2100:
                year = str(value)
    except (TypeError, ValueError, OSError, OverflowError):
        year = ""

    cover = _pick_text(album.get("picUrl") or _as_dict(info.get("al")).get("picUrl"))
    return {
        "album": _pick_text(album.get("name")),
        "year": year,
        "cover": cover,
    }


def _netease_lyrics_by_id(song_id: Any) -> str | None:
    """按网易云歌曲 ID 取同步歌词原文。"""
    data = _get_json(
        "https://music.163.com/api/song/lyric",
        params={"id": song_id, "lv": 1, "kv": 1, "tv": -1},
        headers=_NETEASE_HEADERS, timeout=8, quiet=True,
    )
    if not isinstance(data, dict):
        return None
    text = _as_dict(data.get("lrc")).get("lyric")
    if isinstance(text, str) and text.strip():
        return text
    return None


def _netease_search_lyric(title: str, artist: str = "") -> str | None:
    """跨平台兜底：在网易云按「歌名 歌手」检索后取歌词。"""
    keyword = f"{title} {artist}".strip()
    if not keyword:
        return None
    search = _get_json(
        "https://music.163.com/api/search/get/web",
        params={"s": keyword, "type": 1, "limit": 3, "offset": 0},
        headers=_NETEASE_HEADERS, timeout=8, quiet=True,
    )
    songs = _as_list(_as_dict(_as_dict(search).get("result")).get("songs"))
    if not songs:
        return None

    normalized_title = _norm_key(title)
    for item in songs:
        if not isinstance(item, dict):
            continue
        # 歌名匹配才用，避免拿到同名错误版本
        item_name = _norm_key(item.get("name"))
        if normalized_title and normalized_title not in item_name:
            if item_name not in normalized_title:
                continue
        text = _netease_lyrics_by_id(item.get("id"))
        if text:
            return text
    return None


def _lrclib_pick(item: Any) -> str | None:
    """从 lrclib 结果项中取同步歌词或纯文本歌词。"""
    if not isinstance(item, dict):
        return None
    text = item.get("syncedLyrics") or item.get("plainLyrics")
    return text if isinstance(text, str) and text else None


def _lrclib_lyrics(title: str, artist: str = "",
                   album: str = "") -> str | None:
    """lrclib.net 免费歌词库：优先精确匹配，再退化到搜索。"""
    if not title:
        return None
    headers = {**HEADERS, "Accept": "application/json"}

    data = _get_json(
        "https://lrclib.net/api/get",
        params={"artist_name": artist, "track_name": title,
                "album_name": album, "duration": 0},
        headers=headers, timeout=8, quiet=True,
    )
    text = _lrclib_pick(data)
    if text:
        return text

    items = _get_json(
        "https://lrclib.net/api/search",
        params={"track_name": title, "artist_name": artist},
        headers=headers, timeout=8, quiet=True,
    )
    for item in _as_list(items)[:5]:
        text = _lrclib_pick(item)
        if text:
            return text
    return None


def fetch_lyrics(meta: SongDict) -> str | None:
    """按优先级获取 LRC 歌词文本，全部失败返回 ``None``。

    优先级：现成歌词文本 → 平台歌词链接 → 网易云 ID → 网易云模糊搜索
    → lrclib。``meta`` 可用键：``lyrics`` / ``lrc_url`` / ``source`` /
    ``song_id`` / ``title`` / ``artist`` / ``album``。
    """
    meta = _as_dict(meta)
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
    """去掉 LRC 时间轴与元信息标签，返回可读纯文本歌词。"""
    if not lrc:
        return ""
    lines: list[str] = []
    for raw in str(lrc).splitlines():
        line = _LRC_META_RE.sub("", raw)
        line = _LRC_LINE_RE.sub("", line).strip()
        if line:
            lines.append(line)

    # 去重相邻重复行（逐字歌词常见）
    deduped: list[str] = []
    for line in lines:
        if not deduped or deduped[-1] != line:
            deduped.append(line)
    return "\n".join(deduped)
