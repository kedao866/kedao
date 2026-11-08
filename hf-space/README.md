---
title: kedao API
emoji: 🎬
colorFrom: yellow
colorTo: red
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: Video extraction API for the kedao web app
---

# kedao API

kedao 网页版的后端：用 yt-dlp + ffmpeg 解析并下载视频，供
[kedao866.github.io/kedao](https://kedao866.github.io/kedao/) 调用。

- `GET /api/health` 健康检查
- `GET /api/config` 支持的清晰度与限制
- `POST /api/probe` 解析链接
- `POST /api/download` 创建下载任务
- `GET /api/jobs/<id>` 查询进度
- `POST /api/jobs/<id>/cancel` 取消任务
- `GET /api/jobs/<id>/file` 下载文件

文件保存在 `/tmp/kedao`，60 分钟后自动清理；Space 休眠或重启后任务会丢失。
单文件上限 300MB，时长上限 90 分钟，每个 IP 10 分钟内最多 20 次解析、5 次下载。

仅供个人学习与备份自己有权保存的内容，请遵守各平台条款。
