"""Server-side yt-dlp wrapper for the kedao web app."""
from __future__ import annotations

import os
import re
import shutil
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yt_dlp
from yt_dlp.utils import DownloadCancelled

APP_VERSION = "1.2.0"

QUALITIES = {
    "best": "bv*+ba/b",
    "1080": "bv*[height<=1080]+ba/b[height<=1080]/b",
    "720": "bv*[height<=720]+ba/b[height<=720]/b",
    "480": "bv*[height<=480]+ba/b[height<=480]/b",
    "audio": "ba/b",
}

_XHS_SHARE_HOSTS = {"xhslink.cn", "xhslink.com"}
_XHS_NOTE_PATH = re.compile(r"^/(?:explore|discovery/item)/[\da-f]+")
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


MAX_FILESIZE = _env_int("MAX_FILESIZE_MB", 300) * 1024 * 1024
MAX_DURATION = _env_int("MAX_DURATION_MIN", 90) * 60


def ffmpeg_path() -> Path | None:
    explicit = os.environ.get("FFMPEG_PATH", "").strip()
    if explicit:
        candidate = Path(explicit)
        if candidate.exists():
            return candidate
    found = shutil.which("ffmpeg")
    if found:
        return Path(found)
    local = Path(__file__).resolve().parent / "bin" / "ffmpeg.exe"
    return local if local.exists() else None


def _js_runtimes() -> dict | None:
    runtimes: dict[str, dict] = {}
    for name, executable in (("deno", "deno"), ("node", "node"), ("bun", "bun"), ("quickjs", "qjs")):
        found = shutil.which(executable)
        if found:
            runtimes[name] = {"path": found}
    return runtimes or None


def _cookie_file() -> Path | None:
    value = os.environ.get("YTDLP_COOKIES_FILE", "").strip()
    if value:
        candidate = Path(value)
        if candidate.exists():
            return candidate
    return None


def format_duration(seconds: float | None) -> str:
    if not seconds:
        return ""
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def friendly_error(exc: BaseException) -> str:
    raw = str(exc).strip()
    low = raw.lower()
    if isinstance(exc, DownloadCancelled):
        return "已取消"
    if "sign in to confirm" in low or "not a bot" in low:
        return "该站点要求登录或人机验证。云端服务器无法读取你的浏览器 Cookie，请换用其他链接，或在电脑版中提取。"
    if "requested format is not available" in low:
        return "所选清晰度不可用，请改用 720P 或“最佳”。"
    if "max-filesize" in low or "larger than max" in low:
        return f"文件超过 {MAX_FILESIZE // (1024 * 1024)}MB 限制，请选择更低清晰度或仅音频。"
    if "分钟限制" in raw or ("duration" in low and "limit" in low):
        return f"视频超过 {MAX_DURATION // 60} 分钟限制。"
    if "小红书分享链接已失效" in raw:
        return raw
    if "no video formats found" in low or "there is no video" in low:
        return "这个页面里没有找到视频，可能是图文笔记或需要登录。"
    if "unsupported url" in low:
        return "这个链接暂不支持，请确认是视频页面链接。"
    if "is not a valid url" in low:
        return "链接格式不正确。"
    if "video unavailable" in low or "has been removed" in low:
        return "视频不可用或已被删除。"
    if "private video" in low or "members-only" in low:
        return "该视频为私享或会员内容，需要登录后才能获取。"
    if "ffmpeg" in low and ("not found" in low or "not installed" in low):
        return "服务器缺少 ffmpeg，暂时无法合并音视频。"
    if "unable to download" in low or "urlopen error" in low or "timed out" in low:
        return "网络连接失败，请稍后重试。"
    if "http error 403" in low:
        return "服务器拒绝访问（403），可能需要登录或更换网络。"
    if "http error 404" in low:
        return "视频不存在（404）。"
    if "http error 429" in low or "too many requests" in low:
        return "请求过于频繁，请稍后再试。"
    if "geo" in low and "block" in low:
        return "该视频在当前服务器所在地区不可用。"
    if "cookie" in low and ("could not" in low or "failed" in low):
        return "该视频需要登录 Cookie，云端暂时无法读取。请改用电脑版提取。"
    if len(raw) > 240:
        raw = raw[:240] + "…"
    return f"解析失败：{raw}" if raw else "解析失败，请稍后重试。"


def _xiaohongshu_note_url(url: str) -> str:
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return ""
    host = (parts.hostname or "").lower()
    if not (host == "xiaohongshu.com" or host.endswith(".xiaohongshu.com")):
        return ""
    if _XHS_NOTE_PATH.match(parts.path):
        return urllib.parse.urlunsplit(("https", parts.netloc, parts.path, parts.query, ""))
    target = (urllib.parse.parse_qs(parts.query).get("redirectPath") or [""])[0]
    if not target:
        return ""
    try:
        target_parts = urllib.parse.urlsplit(target)
    except ValueError:
        return ""
    target_host = (target_parts.hostname or "").lower()
    if not (target_host == "xiaohongshu.com" or target_host.endswith(".xiaohongshu.com")):
        return ""
    if not _XHS_NOTE_PATH.match(target_parts.path):
        return ""
    return urllib.parse.urlunsplit(
        ("https", target_parts.netloc, target_parts.path, target_parts.query, "")
    )


@dataclass
class VideoInfo:
    url: str
    title: str
    uploader: str = ""
    duration: float | None = None
    thumbnail: str = ""
    max_height: int | None = None
    webpage_url: str = ""
    is_playlist: bool = False
    heights: list[int] = field(default_factory=list)
    site: str = ""


@dataclass
class DownloadResult:
    ok: bool
    title: str = ""
    filepath: str = ""
    message: str = ""
    cancelled: bool = False


EventCallback = Callable[[dict], None]


class _YdlLogger:
    def __init__(self, callback: EventCallback | None):
        self.callback = callback
        self._last: str | None = None

    def debug(self, msg: str) -> None:
        if msg.startswith("[debug]"):
            return
        self.info(msg)

    def info(self, msg: str) -> None:
        if not self.callback or not msg or msg == self._last:
            return
        self._last = msg
        self.callback({"type": "log", "text": msg})

    def warning(self, msg: str) -> None:
        self.info(msg)

    def error(self, msg: str) -> None:
        self.info(msg)


class Engine:
    def __init__(
        self,
        on_event: EventCallback | None = None,
        cancel_event: threading.Event | None = None,
    ):
        self.on_event = on_event
        self.cancel_event = cancel_event or threading.Event()

    def _emit(self, event: dict) -> None:
        if self.on_event:
            try:
                self.on_event(event)
            except Exception:  # noqa: BLE001 - callbacks must not break downloads
                pass

    def _common_opts(self) -> dict:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": True,
            "playlist_items": "1",
            "retries": 5,
            "fragment_retries": 5,
            "extractor_retries": 3,
            "socket_timeout": 30,
            "trim_file_name": 120,
            "logger": _YdlLogger(self.on_event),
            "js_runtimes": _js_runtimes(),
            "remote_components": ["ejs:github"],
            "http_headers": {
                "User-Agent": _BROWSER_UA,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
            "max_filesize": MAX_FILESIZE,
        }
        opts = {k: v for k, v in opts.items() if v is not None}
        cookies = _cookie_file()
        if cookies:
            opts["cookiefile"] = str(cookies)
        ffmpeg = ffmpeg_path()
        if ffmpeg:
            opts["ffmpeg_location"] = str(ffmpeg.parent)
        return opts

    def _normalize_url(self, url: str) -> str:
        try:
            host = (urllib.parse.urlsplit(url).hostname or "").lower()
        except ValueError:
            return url
        if host not in _XHS_SHARE_HOSTS:
            return url
        try:
            request = urllib.request.Request(url, headers={"User-Agent": _BROWSER_UA})
            with urllib.request.urlopen(request, timeout=15) as response:
                final_url = response.geturl()
        except (OSError, ValueError):
            return url
        note_url = _xiaohongshu_note_url(final_url)
        if not note_url:
            raise RuntimeError(
                "小红书分享链接已失效或需要登录，请在小红书 App 里重新复制分享链接"
            )
        return note_url

    def probe(self, url: str) -> VideoInfo:
        url = self._normalize_url(url)
        opts = self._common_opts()
        opts.update({"skip_download": True, "socket_timeout": 15, "retries": 2, "extractor_retries": 1})
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info:
            raise RuntimeError("没有解析到视频信息")
        playlist = bool(info.get("entries"))
        if playlist:
            entries = [e for e in info.get("entries") or [] if e]
            if not entries:
                raise RuntimeError("播放列表为空")
            info = entries[0]
        heights = sorted(
            {
                int(f["height"])
                for f in info.get("formats") or []
                if f.get("height") and f.get("vcodec") not in (None, "none")
            },
            reverse=True,
        )
        max_height = max(heights) if heights else info.get("height")
        thumbnail = info.get("thumbnail") or ""
        if not thumbnail:
            thumbs = info.get("thumbnails") or []
            if thumbs:
                thumbnail = thumbs[-1].get("url") or ""
        if thumbnail.startswith("http://"):
            # GitHub Pages 走 HTTPS，http 图床会被浏览器按混合内容拦截
            thumbnail = "https://" + thumbnail[len("http://") :]
        return VideoInfo(
            url=url,
            title=info.get("title") or "未命名视频",
            uploader=info.get("uploader") or info.get("channel") or "",
            duration=info.get("duration"),
            thumbnail=thumbnail,
            max_height=max_height,
            webpage_url=info.get("webpage_url") or url,
            is_playlist=playlist,
            heights=heights[:8],
            site=(info.get("extractor_key") or info.get("extractor") or ""),
        )

    def download(self, url: str, quality_key: str, output_dir: str, title_hint: str = "") -> DownloadResult:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        selector = QUALITIES.get(quality_key, QUALITIES["720"])
        state: dict = {"filepath": "", "title": title_hint, "stream_kind": None}
        last_emit = 0.0

        def progress_hook(data: dict) -> None:
            nonlocal last_emit
            if self.cancel_event.is_set():
                raise DownloadCancelled("cancelled")
            status = data.get("status")
            if status == "downloading":
                info = data.get("info_dict") or {}
                if info.get("title"):
                    state["title"] = info["title"]
                is_audio = (
                    info.get("acodec") not in (None, "none")
                    and info.get("vcodec") in (None, "none")
                )
                kind = "audio" if is_audio else "video"
                if kind != state["stream_kind"]:
                    state["stream_kind"] = kind
                    if kind == "audio":
                        self._emit({"type": "stage", "text": "正在下载音频…"})
                total = data.get("total_bytes") or data.get("total_bytes_estimate")
                downloaded = data.get("downloaded_bytes") or 0
                percent = (downloaded / total * 100) if total else None
                current = time.time()
                if current - last_emit < 0.15 and percent not in (None, 100):
                    return
                last_emit = current
                self._emit(
                    {
                        "type": "progress",
                        "percent": percent,
                        "downloaded": downloaded,
                        "total": total,
                        "speed": data.get("speed"),
                        "eta": data.get("eta"),
                    }
                )
            elif status == "finished":
                state["filepath"] = data.get("filename") or state["filepath"]
                self._emit({"type": "progress", "percent": 100.0, "speed": None, "eta": 0})

        def postprocessor_hook(data: dict) -> None:
            if self.cancel_event.is_set():
                raise DownloadCancelled("cancelled")
            status = data.get("status")
            name = data.get("postprocessor", "")
            if status == "started":
                labels = {
                    "Merger": "正在合并音视频…",
                    "FFmpegExtractAudio": "正在提取音频…",
                    "FFmpegVideoRemuxer": "正在转换封装…",
                    "MoveFiles": "正在整理文件…",
                }
                self._emit({"type": "stage", "text": labels.get(name, "正在处理…")})
            elif status == "finished":
                info = data.get("info_dict") or {}
                fp = info.get("filepath") or info.get("_filename")
                if fp:
                    state["filepath"] = fp

        def duration_filter(info: dict, *, incomplete=False):
            duration = info.get("duration")
            if duration and duration > MAX_DURATION:
                return f"视频超过 {MAX_DURATION // 60} 分钟限制"
            return None

        opts = self._common_opts()
        opts.update(
            {
                "format": selector,
                "paths": {"home": str(out_dir)},
                "outtmpl": {"default": "%(title).100B [%(id)s].%(ext)s"},
                "progress_hooks": [progress_hook],
                "postprocessor_hooks": [postprocessor_hook],
                "continuedl": True,
                "overwrites": False,
                "concurrent_fragment_downloads": 4,
                "match_filter": duration_filter,
            }
        )
        if quality_key == "audio":
            opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ]

        try:
            url = self._normalize_url(url)
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info and info.get("title"):
                    state["title"] = info["title"]
                if not state["filepath"] and info:
                    try:
                        state["filepath"] = str(ydl.prepare_filename(info))
                    except Exception:  # noqa: BLE001
                        pass
            filepath = self._resolve_final_path(state["filepath"], quality_key, out_dir)
            return DownloadResult(ok=True, title=state["title"], filepath=filepath, message="下载完成")
        except DownloadCancelled:
            return DownloadResult(ok=False, title=state["title"], message="已取消", cancelled=True)
        except Exception as exc:  # noqa: BLE001 - surfaced as friendly text
            return DownloadResult(ok=False, title=state["title"], message=friendly_error(exc))

    @staticmethod
    def _resolve_final_path(filepath: str, quality_key: str, out_dir: Path) -> str:
        if filepath and Path(filepath).exists():
            return filepath
        if filepath:
            base = Path(filepath)
            if quality_key == "audio":
                for ext in (".mp3", ".m4a", ".opus"):
                    candidate = base.with_suffix(ext)
                    if candidate.exists():
                        return str(candidate)
            for ext in (".mp4", ".mkv", ".webm"):
                candidate = base.with_suffix(ext)
                if candidate.exists():
                    return str(candidate)
        try:
            newest = max(out_dir.glob("*"), key=os.path.getmtime)
            return str(newest)
        except (ValueError, OSError):
            return ""
