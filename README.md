# kedao · 把视频轻轻取下来

在线视频提取工具。粘贴 B站 / YouTube / 小红书 / 抖音等链接，解析标题和清晰度，直接保存到手机或电脑。附带一个免安装的 Windows 桌面版。

- 在线版：GitHub Pages（页面）+ Render 或 Hugging Face Space（解析与下载后端）
- 桌面版：单文件 `kedao.exe`，绿色免安装，通过 GitHub Release 分发

## 在线地址

- 页面：https://kedao866.github.io/kedao/
- 代码：https://github.com/kedao866/kedao
- Windows 版：https://github.com/kedao866/kedao/releases/latest

页面部署在 GitHub Pages；视频解析与下载由 Render 后端
`https://kedao-866-api.onrender.com` 提供。如果服务名被占用，Render 会生成另一个
地址，届时打开 `https://kedao866.github.io/kedao/?api=https://你的后端地址`
即可保存新地址，也可以在页脚“连接设置”里修改。

## 为什么不是纯 GitHub Pages

GitHub Pages 只能托管静态文件，不能运行 yt-dlp、ffmpeg，也不能代理视频流。因此拆成两部分：

```
浏览器（GitHub Pages 静态页）
        │  POST /api/probe、/api/download，轮询 /api/jobs/:id
        ▼
Render Docker 服务（Flask + yt-dlp + ffmpeg + Deno）
        │
        ▼
视频站点 ──► 临时目录 ──► /api/jobs/:id/file 下载
```

后端同时会托管一份前端，所以即使不配置 GitHub Pages，直接打开 Render 地址也能用。

## 目录结构

```
kedao-web/
├─ frontend/              静态页面（PWA，可直接放 GitHub Pages）
│  ├─ index.html
│  ├─ styles.css
│  ├─ app.js
│  ├─ config.js           ← 部署后需要填写后端地址和仓库地址
│  ├─ manifest.webmanifest
│  ├─ sw.js
│  └─ assets/
├─ backend/
│  ├─ server.py           Flask API、任务队列、限流、静态托管
│  ├─ engine_web.py       yt-dlp 封装
│  ├─ requirements.txt
│  └─ Dockerfile
├─ hf-space/              Hugging Face Space 上传包（Dockerfile + backend/frontend 副本）
├─ render.yaml            Render Blueprint（免费 Docker 服务）
└─ .github/workflows/pages.yml
```

## 本地运行

需要 Python 3.11+、ffmpeg，YouTube 建议再装 Deno 或 Node。

```bash
cd backend
pip install -r requirements.txt
python server.py
```

打开 http://127.0.0.1:8000 。Flask 会同时提供页面和 API，前端会自动识别同源后端。

Windows 上如果没有 ffmpeg，把 `ffmpeg.exe` 放到 `backend/bin/`，或设置环境变量 `FFMPEG_PATH`。

## 部署到 GitHub + Render

### 1. 建仓库并推送

在 GitHub 新建空仓库（建议公开，名为 `kedao`），然后：

```bash
cd kedao-web
git init
git add .
git commit -m "kedao online video extractor"
git branch -M main
git remote add origin https://github.com/<你的用户名>/kedao.git
git push -u origin main
```

### 2. 部署后端（Render，免费）

1. 打开 https://render.com 用 GitHub 登录。
2. New → Blueprint，选择 `kedao` 仓库，Render 会读取 `render.yaml`。
3. 确认服务名与区域（默认新加坡），点击 Apply，等待首次构建（约 3–8 分钟）。
4. 构建完成后打开服务地址，访问 `/api/health` 应返回 `"ok": true`。
5. 复制服务地址，例如 `https://kedao-api-xxxx.onrender.com`。

免费实例 15 分钟无请求会休眠，下一次访问需要约 30–60 秒唤醒；页面已经有相应提示。

### 2b. 部署后端（Hugging Face Space，免费、无需信用卡）

Hugging Face 的免费 Docker Space 提供 2 vCPU / 16GB 内存，适合这个后端。项目里已经准备好独立上传包 `hf-space/`（Dockerfile、README、backend、frontend）。

1. 注册并登录 https://huggingface.co 。
2. 打开 https://huggingface.co/new-space ：
   - Space name 填 `kedao-api`
   - SDK 选 **Docker** → **Blank**
   - Hardware 选 **CPU basic · FREE**
   - 可见性选 **Public**
3. 进入 Space 的 **Files** 页，把 `hf-space/` 里的 `Dockerfile`、`README.md`、`backend/`、`frontend/` 上传（拖拽文件夹即可），提交后自动构建，约 3–8 分钟。
4. 构建完成后，Space 页面上的 **App** 就是后端地址，形如：

   ```
   https://<你的HF用户名>-kedao-api.hf.space
   ```

   访问 `https://<你的HF用户名>-kedao-api.hf.space/api/health`，应返回 `"ok": true`。
5. 打开 `https://kedao866.github.io/kedao/?api=https://<你的HF用户名>-kedao-api.hf.space`，页面会记住这个地址。

Space 空闲约 48 小时后休眠，首次访问需要唤醒；免费磁盘是临时的，重启后任务文件会清空。

更新后端代码时，先在本机运行 `hf-space/sync.sh` 同步 `backend/`、`frontend/`，再把改动上传到 Space 并点 **Factory rebuild**。

### 3. 发布前端（GitHub Pages）

1. 编辑 `frontend/config.js`：

   ```js
   window.KEDAO_CONFIG = {
     apiBase: "",
     defaultApi: "https://kedao-api-xxxx.onrender.com",
     desktopUrl: "https://github.com/<你的用户名>/kedao/releases/latest",
     repoUrl: "https://github.com/<你的用户名>/kedao",
   };
   ```

   `apiBase` 留空即可；页面会先尝试同源后端，失败后使用 `defaultApi`。也支持在页脚“连接设置”里临时改地址。

2. 仓库 Settings → Pages → Source 选择 **GitHub Actions**（工作流也会尝试自动开启）。
3. 推送后打开 Actions 里的 “Deploy kedao frontend to GitHub Pages”，完成后访问：

   ```
   https://<你的用户名>.github.io/kedao/
   ```

4. 手机浏览器打开该地址，可“添加到主屏幕”，作为 PWA 使用。

### 4. 发布 Windows 桌面版（可选）

在仓库 Releases → Draft a new release，上传 `kedao.exe`，标签例如 `v1.1.0`。页面上的“下载 Windows 版”按钮会指向 `/releases/latest`。

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `PORT` | `10000` | 服务端口 |
| `WORK_DIR` | `backend/work` | 临时下载目录，云端建议 `/tmp/kedao` |
| `ALLOWED_ORIGINS` | `*` | CORS 白名单，逗号分隔；生产可填 Pages 域名 |
| `TRUST_PROXY` | 空 | 反向代理后设为 `1`，用真实客户端 IP 限流 |
| `MAX_FILESIZE_MB` | `300` | 单文件大小上限 |
| `MAX_DURATION_MIN` | `90` | 视频时长上限（分钟） |
| `MAX_ACTIVE_DOWNLOADS` | `2` | 同时下载任务数 |
| `JOB_TTL_MIN` | `60` | 完成后文件保留时间（分钟） |
| `PROBE_LIMIT` | `20` | 每 IP 在窗口内解析次数 |
| `DOWNLOAD_LIMIT` | `5` | 每 IP 在窗口内下载次数 |
| `RATE_WINDOW_MIN` | `10` | 限流窗口（分钟） |
| `FFMPEG_PATH` | 自动查找 | ffmpeg 可执行文件路径 |

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查、ffmpeg / JS 运行时状态 |
| GET | `/api/config` | 可用清晰度与限制 |
| POST | `/api/probe` | `{"url": "..."}`，返回标题、作者、封面、时长、清晰度 |
| POST | `/api/download` | `{"url","quality","title"}`，创建任务，返回 `job_id` |
| GET | `/api/jobs/<id>` | 任务进度：`queued/running/done/error/cancelled` |
| POST | `/api/jobs/<id>/cancel` | 取消任务 |
| GET | `/api/jobs/<id>/file` | 下载成品文件（完成后 60 分钟内有效） |

## 限制与安全

- 云端无法读取你本机浏览器的 Cookie，因此需要登录、会员或人机验证的内容会失败；这类内容请用桌面版。
- 单文件 ≤ 300MB、时长 ≤ 90 分钟，超出会给出中文提示。
- 后端会拒绝内网 / 回环地址（SSRF 防护），按 IP 限流，限制并发和请求体大小。
- 文件只临时保存在服务器，任务过期后自动删除；Render 重启也会清空。
- 小红书图文笔记、直播、付费内容不支持。
- 免费后端资源有限，适合个人使用；请勿公开大规模分发或用于商业下载。

## 使用须知

本工具仅用于下载你有权保存的内容（自己的作品、已获授权或允许离线保存的素材）。请遵守各平台的服务条款与当地版权法规，不要用于侵权、搬运或牟利。

## 第三方组件

- [yt-dlp](https://github.com/yt-dlp/yt-dlp)（Unlicense）
- [Flask](https://flask.palletsprojects.com/)（BSD-3-Clause）
- [ffmpeg](https://ffmpeg.org/)（LGPL/GPL，由系统包提供）
- [Deno](https://deno.com/)（MIT）
