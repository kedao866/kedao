"""kedao web backend: Flask API around the yt-dlp engine."""
from __future__ import annotations

import ipaddress
import logging
import os
import socket
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, abort, jsonify, request, send_file, send_from_directory

import engine_web

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = (BASE_DIR.parent / "frontend").resolve()
WORK_DIR = Path(os.environ.get("WORK_DIR", BASE_DIR / "work")).resolve()
WORK_DIR.mkdir(parents=True, exist_ok=True)

MAX_ACTIVE_DOWNLOADS = engine_web._env_int("MAX_ACTIVE_DOWNLOADS", 2)
JOB_TTL = engine_web._env_int("JOB_TTL_MIN", 60) * 60
PROBE_LIMIT = engine_web._env_int("PROBE_LIMIT", 20)
DOWNLOAD_LIMIT = engine_web._env_int("DOWNLOAD_LIMIT", 5)
RATE_WINDOW = engine_web._env_int("RATE_WINDOW_MIN", 10) * 60

SITE_NAMES = {
    "BiliBili": "哔哩哔哩",
    "Youtube": "YouTube",
    "XiaoHongShu": "小红书",
    "Douyin": "抖音",
    "TikTok": "TikTok",
    "Twitter": "X",
    "Instagram": "Instagram",
    "Vimeo": "Vimeo",
    "Niconico": "niconico",
    "Weibo": "微博",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024

# Render 等反向代理后需要信任最右侧的 X-Forwarded-For，否则限流可被伪造头绕过
if os.environ.get("TRUST_PROXY", "").lower() in ("1", "true", "yes"):
    from werkzeug.middleware.proxy_fix import ProxyFix

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

_jobs: dict[str, "Job"] = {}
_jobs_lock = threading.Lock()
_download_slots = threading.BoundedSemaphore(MAX_ACTIVE_DOWNLOADS)
_rate_lock = threading.Lock()
_rate_buckets: dict[str, deque] = defaultdict(deque)


@dataclass
class Job:
    id: str
    url: str
    quality: str
    title: str = ""
    status: str = "queued"
    stage: str = "排队中…"
    percent: float | None = None
    speed: float | None = None
    eta: float | None = None
    downloaded: int | None = None
    total: int | None = None
    error: str = ""
    filepath: str = ""
    filename: str = ""
    filesize: int = 0
    created: float = field(default_factory=time.time)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self) -> dict:
        with self.lock:
            data = {
                "id": self.id,
                "status": self.status,
                "stage": self.stage,
                "percent": round(self.percent, 1) if self.percent is not None else None,
                "speed": self.speed,
                "eta": self.eta,
                "downloaded": self.downloaded,
                "total": self.total,
                "title": self.title,
                "filename": self.filename,
                "filesize": self.filesize,
                "error": self.error,
                "quality": self.quality,
            }
            if self.status == "done" and self.filepath:
                data["download_url"] = f"/api/jobs/{self.id}/file"
            return data


def _client_ip() -> str:
    return request.remote_addr or "unknown"


def _rate_ok(bucket: str, limit: int) -> bool:
    now = time.time()
    key = f"{bucket}:{_client_ip()}"
    with _rate_lock:
        queue = _rate_buckets[key]
        while queue and now - queue[0] > RATE_WINDOW:
            queue.popleft()
        if len(queue) >= limit:
            return False
        queue.append(now)
        return True


def _public_url(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        raise ValueError("请先粘贴视频链接")
    if len(value) > 2048:
        raise ValueError("链接太长")
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("链接格式不正确，需要 http/https 地址")
    if parts.username or parts.password:
        raise ValueError("链接不能包含账号信息")
    host = parts.hostname.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(
        (".local", ".internal", ".localhost")
    ):
        raise ValueError("该链接指向内网地址，已拒绝")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("链接域名无法解析") from exc
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if not address.is_global:
            raise ValueError("该链接指向内网地址，已拒绝")
    return value


def _job_worker(job: Job) -> None:
    with _download_slots:
        if job.cancel_event.is_set():
            with job.lock:
                job.status = "cancelled"
                job.stage = "已取消"
            return
        with job.lock:
            job.status = "running"
            job.stage = "开始解析…"

        def on_event(event: dict) -> None:
            with job.lock:
                if event.get("type") == "progress":
                    if event.get("percent") is not None:
                        job.percent = float(event["percent"])
                    job.downloaded = event.get("downloaded")
                    job.total = event.get("total")
                    job.speed = event.get("speed")
                    job.eta = event.get("eta")
                    job.stage = "正在下载…"
                elif event.get("type") == "stage" and event.get("text"):
                    job.stage = event["text"]

        engine = engine_web.Engine(on_event=on_event, cancel_event=job.cancel_event)
        job_dir = WORK_DIR / job.id
        job_dir.mkdir(parents=True, exist_ok=True)
        result = engine.download(job.url, job.quality, str(job_dir), job.title)

        with job.lock:
            job.title = result.title or job.title
            if result.ok and result.filepath:
                path = Path(result.filepath).resolve()
                try:
                    inside = path.is_relative_to(job_dir.resolve())
                except ValueError:
                    inside = False
                if inside and path.is_file():
                    job.filepath = str(path)
                    job.filename = path.name
                    job.filesize = path.stat().st_size
                    job.status = "done"
                    job.percent = 100
                    job.stage = "下载完成"
                else:
                    job.status = "error"
                    job.error = "下载完成但找不到文件，请重试。"
                    job.stage = "处理失败"
            elif result.cancelled:
                job.status = "cancelled"
                job.stage = "已取消"
            else:
                job.status = "error"
                job.error = result.message or "下载失败"
                job.stage = "下载失败"


def _cleanup_loop() -> None:
    while True:
        time.sleep(300)
        cutoff = time.time() - JOB_TTL
        with _jobs_lock:
            stale = [job for job in _jobs.values() if job.created < cutoff]
            for job in stale:
                _jobs.pop(job.id, None)
        for job in stale:
            folder = WORK_DIR / job.id
            try:
                for child in folder.glob("*"):
                    child.unlink(missing_ok=True)
                folder.rmdir()
            except OSError:
                pass


@app.after_request
def _headers(response):
    allowed = os.environ.get("ALLOWED_ORIGINS", "*").strip()
    origin = request.headers.get("Origin", "")
    if allowed == "*":
        response.headers["Access-Control-Allow-Origin"] = "*"
    elif origin and origin in {item.strip() for item in allowed.split(",")}:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Expose-Headers"] = "Content-Disposition,Content-Length"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.get("/api/health")
def health():
    ffmpeg = engine_web.ffmpeg_path()
    return jsonify(
        {
            "ok": True,
            "version": engine_web.APP_VERSION,
            "ffmpeg": str(ffmpeg) if ffmpeg else None,
            "js_runtime": engine_web._js_runtimes(),
            "max_filesize_mb": engine_web.MAX_FILESIZE // (1024 * 1024),
            "max_duration_min": engine_web.MAX_DURATION // 60,
        }
    )


@app.get("/api/config")
def config():
    return jsonify(
        {
            "version": engine_web.APP_VERSION,
            "qualities": [
                {"key": "1080", "label": "1080P"},
                {"key": "720", "label": "720P"},
                {"key": "480", "label": "480P"},
                {"key": "audio", "label": "仅音频 MP3"},
            ],
            "max_filesize_mb": engine_web.MAX_FILESIZE // (1024 * 1024),
            "max_duration_min": engine_web.MAX_DURATION // 60,
        }
    )


@app.post("/api/probe")
def probe():
    if not _rate_ok("probe", PROBE_LIMIT):
        return jsonify({"error": "请求过于频繁，请稍后再试。"}), 429
    payload = request.get_json(silent=True) or {}
    try:
        url = _public_url(str(payload.get("url", "")))
        info = engine_web.Engine().probe(url)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001 - user-facing message
        app.logger.warning("probe failed: %s", exc)
        return jsonify({"error": engine_web.friendly_error(exc)}), 400

    heights = info.heights or ([int(info.max_height)] if info.max_height else [])
    options = [{"key": "720", "label": "720P"}, {"key": "480", "label": "480P"}]
    if info.max_height and int(info.max_height) >= 1080:
        options.insert(0, {"key": "1080", "label": "1080P"})
    options.append({"key": "audio", "label": "仅音频 MP3"})

    return jsonify(
        {
            "url": info.url,
            "title": info.title,
            "uploader": info.uploader,
            "duration": info.duration,
            "duration_text": engine_web.format_duration(info.duration),
            "thumbnail": info.thumbnail,
            "max_height": info.max_height,
            "heights": heights,
            "site": info.site,
            "site_name": SITE_NAMES.get(info.site, info.site or "视频"),
            "webpage_url": info.webpage_url,
            "is_playlist": info.is_playlist,
            "qualities": options,
        }
    )


@app.post("/api/download")
def download():
    if not _rate_ok("download", DOWNLOAD_LIMIT):
        return jsonify({"error": "下载请求过于频繁，请稍后再试。"}), 429
    payload = request.get_json(silent=True) or {}
    try:
        url = _public_url(str(payload.get("url", "")))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    quality = str(payload.get("quality", "720"))
    if quality not in engine_web.QUALITIES:
        return jsonify({"error": "清晰度参数不正确"}), 400
    job = Job(id=uuid.uuid4().hex[:12], url=url, quality=quality)
    with _jobs_lock:
        _jobs[job.id] = job
    threading.Thread(target=_job_worker, args=(job,), daemon=True).start()
    return jsonify({"job": job.snapshot()}), 202


@app.get("/api/jobs/<job_id>")
def job_status(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "任务不存在或已过期"}), 404
    return jsonify(job.snapshot())


@app.post("/api/jobs/<job_id>/cancel")
def cancel_job(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "任务不存在或已过期"}), 404
    job.cancel_event.set()
    with job.lock:
        if job.status in ("queued", "running"):
            job.stage = "正在取消…"
    return jsonify(job.snapshot())


@app.get("/api/jobs/<job_id>/file")
def download_file(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        abort(404)
    with job.lock:
        if job.status != "done" or not job.filepath:
            abort(409)
        path = Path(job.filepath)
        filename = job.filename or path.name
    if not path.is_file():
        abort(404)
    return send_file(
        path,
        as_attachment=True,
        download_name=filename,
        conditional=True,
        max_age=0,
    )


@app.errorhandler(413)
def too_large(_exc):
    return jsonify({"error": "请求体太大"}), 413


@app.get("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.get("/<path:path>")
def static_page(path: str):
    if path.startswith("api/"):
        abort(404)
    candidate = (FRONTEND_DIR / path).resolve()
    try:
        inside = candidate.is_relative_to(FRONTEND_DIR)
    except ValueError:
        inside = False
    if inside and candidate.is_file():
        return send_from_directory(FRONTEND_DIR, path)
    return send_from_directory(FRONTEND_DIR, "index.html")


threading.Thread(target=_cleanup_loop, daemon=True).start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
