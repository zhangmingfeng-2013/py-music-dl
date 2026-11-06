#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""media.py 测试：配置校验、ffmpeg 转码、标签写入、后处理管线。"""

import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import media  # noqa: E402


class TestPostOptions:
    def test_defaults(self):
        options = media.PostOptions.from_config({})
        assert options.convert == media.CONVERT_OFF
        assert options.mp3_bitrate == 320
        assert options.write_tags is True

    def test_invalid_values_fall_back(self):
        options = media.PostOptions.from_config({
            "convert_mode": "ogg",
            "mp3_bitrate": "bad",
            "write_tags": "yes",
        })
        assert options.convert == media.CONVERT_OFF
        assert options.mp3_bitrate == 320
        # 非 bool 不参与转换，保持默认 True
        assert options.write_tags is True

    def test_valid_values(self):
        options = media.PostOptions.from_config({
            "convert_mode": "mp3",
            "mp3_bitrate": 192,
            "write_tags": False,
            "embed_cover": False,
            "save_lrc": False,
            "embed_lyrics": False,
            "whisper_fallback": False,
        })
        assert options.convert == "mp3"
        assert options.mp3_bitrate == 192
        assert options.write_tags is False
        assert options.embed_cover is False
        assert options.save_lrc is False
        assert options.embed_lyrics is False
        assert options.whisper_fallback is False

    def test_non_dict_config(self):
        options = media.PostOptions.from_config(None)  # type: ignore[arg-type]
        assert options.convert == media.CONVERT_OFF


class TestImageHelpers:
    def test_guess_mime(self):
        assert media._guess_image_mime(b"\xff\xd8\xffxx", "") == "image/jpeg"
        assert media._guess_image_mime(b"\x89PNG\r\n\x1a\nxx", "") == "image/png"
        assert media._guess_image_mime(
            b"RIFF" + b"\x00" * 4 + b"WEBP", ""
        ) == "image/webp"
        assert media._guess_image_mime(b"gif89a", "") == ""

    def test_download_cover_magic(self, monkeypatch):
        class Response:
            headers = {"Content-Type": "text/plain"}

            def raise_for_status(self):
                pass

            @property
            def content(self):
                return b"\xff\xd8\xff" + b"x" * 100

        monkeypatch.setattr(media.requests, "get", lambda *a, **k: Response())
        cover = media.download_cover("https://x/cover")
        assert cover is not None
        assert cover[1] == "image/jpeg"

    def test_download_cover_rejects_large(self, monkeypatch):
        class Response:
            headers = {"Content-Type": "image/jpeg", "Content-Length": "999999999"}

            def raise_for_status(self):
                pass

            @property
            def content(self):
                return b"\xff\xd8\xff" + b"x" * 100

        monkeypatch.setattr(media.requests, "get", lambda *a, **k: Response())
        assert media.download_cover("https://x/cover") is None

    def test_download_cover_rejects_invalid(self, monkeypatch):
        class Response:
            headers = {"Content-Type": "text/plain"}

            def raise_for_status(self):
                pass

            @property
            def content(self):
                return b"not an image but long enough " + b"x" * 100

        monkeypatch.setattr(media.requests, "get", lambda *a, **k: Response())
        assert media.download_cover("https://x/cover") is None

    def test_download_cover_empty_url(self):
        assert media.download_cover("") is None


class TestTags:
    def test_mp3_tags(self, tmp_path):
        path = tmp_path / "song.mp3"
        path.write_bytes(b"")
        ok = media.write_tags(
            str(path),
            {"title": "晴天", "artist": "周杰伦", "album": "叶惠美", "year": 2003},
            cover=(b"\xff\xd8\xff" + b"x" * 100, "image/jpeg"),
            lyrics="[00:00]故事的小黄花",
        )
        assert ok is True

        from mutagen.id3 import ID3

        tags = ID3(str(path))
        assert str(tags["TIT2"]) == "晴天"
        assert str(tags["TPE1"]) == "周杰伦"
        assert str(tags["TALB"]) == "叶惠美"
        assert str(tags["TDRC"]) == "2003"
        lyrics_tags = tags.getall("USLT")
        assert len(lyrics_tags) == 1
        assert lyrics_tags[0].text == "[00:00]故事的小黄花"
        assert tags.getall("APIC")

    def test_unsupported_extension(self, tmp_path):
        path = tmp_path / "song.ogg"
        path.write_bytes(b"")
        assert media.write_tags(str(path), {"title": "x"}) is False

    def test_invalid_meta_does_not_raise(self, tmp_path):
        path = tmp_path / "song.mp3"
        path.write_bytes(b"")
        # 非字典元数据被拒绝，且不抛异常（保持旧行为）
        assert media.write_tags(str(path), None) is False  # type: ignore[arg-type]

    def test_save_lrc(self, tmp_path):
        audio = tmp_path / "song.mp3"
        audio.write_bytes(b"")
        lrc = media.save_lrc_file(str(audio), "[00:00]x")
        assert lrc == str(tmp_path / "song.lrc")
        assert open(lrc, encoding="utf-8").read() == "[00:00]x"
        assert media.save_lrc_file(str(audio), "") is None


def _make_wav(path) -> bool:
    """用 ffmpeg 生成 0.2 秒正弦波 WAV；不可用返回 False。"""
    if not media.ffmpeg_available():
        return False
    result = subprocess.run(
        [
            media.FFMPEG_BIN, "-y", "-nostdin", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=0.2",
            "-c:a", "pcm_s16le", str(path),
        ],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0 and path.exists()


@pytest.mark.skipif(not media.ffmpeg_available(), reason="需要 ffmpeg")
def test_transcode_wav_to_mp3(tmp_path):
    wav = tmp_path / "song.wav"
    assert _make_wav(wav)
    dst = media.transcode(str(wav), "mp3", 128)
    assert dst is not None
    assert os.path.basename(dst) == "song.mp3"
    assert os.path.getsize(dst) > 0


@pytest.mark.skipif(not media.ffmpeg_available(), reason="需要 ffmpeg")
def test_transcode_flac_tags(tmp_path):
    wav = tmp_path / "song.wav"
    assert _make_wav(wav)
    dst = media.transcode(str(wav), "flac")
    assert dst is not None
    assert media.write_tags(dst, {"title": "晴天", "artist": "周杰伦",
                                  "album": "叶惠美", "year": "2003"})

    from mutagen.flac import FLAC

    audio = FLAC(dst)
    assert audio["title"] == ["晴天"]
    assert audio["artist"] == ["周杰伦"]
    assert audio["album"] == ["叶惠美"]
    assert audio["date"] == ["2003"]


class TestPostProcess:
    def _task(self, path, meta=None):
        return SimpleNamespace(
            filepath=str(path),
            title="晴天",
            artist="周杰伦",
            meta=meta or {},
            display_name="周杰伦 - 晴天",
            remark="",
        )

    def test_save_lrc_only(self, tmp_path):
        audio = tmp_path / "song.mp3"
        audio.write_bytes(b"")
        task = self._task(audio)
        options = media.PostOptions(
            write_tags=False, save_lrc=True, embed_lyrics=False,
            whisper_fallback=False,
        )
        result = media.post_process(
            task, options, lyrics_fetcher=lambda meta: "[00:01]hi"
        )
        assert result["lrc_saved"] is True
        assert (tmp_path / "song.lrc").exists()
        assert task.remark == ""

    def test_write_tags_and_lyrics(self, tmp_path):
        audio = tmp_path / "song.mp3"
        audio.write_bytes(b"")
        task = self._task(audio, {"title": "晴天", "artist": "周杰伦"})
        options = media.PostOptions(
            write_tags=True, embed_cover=False, save_lrc=False,
            embed_lyrics=True, whisper_fallback=False,
        )
        result = media.post_process(
            task, options, lyrics_fetcher=lambda meta: "[00:01]hi"
        )
        assert result["tagged"] is True
        assert result["lyrics_embedded"] is True
        assert result["lrc_saved"] is False

        from mutagen.id3 import ID3

        lyrics_tags = ID3(str(audio)).getall("USLT")
        assert len(lyrics_tags) == 1
        assert lyrics_tags[0].text == "[00:01]hi"

    def test_missing_lyrics(self, tmp_path):
        audio = tmp_path / "song.mp3"
        audio.write_bytes(b"")
        task = self._task(audio)
        options = media.PostOptions(
            write_tags=False, save_lrc=True, whisper_fallback=False,
        )
        result = media.post_process(task, options, lyrics_fetcher=None)
        assert result["lrc_saved"] is False
        assert not (tmp_path / "song.lrc").exists()

    def test_conversion_updates_task_path(self, tmp_path, monkeypatch):
        source = tmp_path / "song.wav"
        source.write_bytes(b"source")
        destination = tmp_path / "song.mp3"
        destination.write_bytes(b"converted")
        task = self._task(source)
        options = media.PostOptions(
            convert="mp3", write_tags=False, save_lrc=False,
            whisper_fallback=False,
        )
        monkeypatch.setattr(media, "ffmpeg_available", lambda: True)
        monkeypatch.setattr(media, "transcode", lambda *a, **k: str(destination))
        result = media.post_process(task, options)
        assert result["converted"] is True
        assert task.filepath == str(destination)
        assert not source.exists()
        assert destination.exists()

    def test_convert_skipped_without_ffmpeg(self, tmp_path, monkeypatch):
        source = tmp_path / "song.wav"
        source.write_bytes(b"source")
        task = self._task(source)
        options = media.PostOptions(
            convert="mp3", write_tags=False, save_lrc=False,
            whisper_fallback=False,
        )
        monkeypatch.setattr(media, "ffmpeg_available", lambda: False)
        result = media.post_process(task, options)
        assert result["converted"] is False
        assert task.filepath == str(source)
        assert source.exists()


if __name__ == "__main__":
    raise SystemExit("请使用 pytest 运行该测试文件")
