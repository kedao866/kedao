(() => {
  "use strict";

  const CFG = window.KEDAO_CONFIG || {};
  const $ = (selector, root = document) => root.querySelector(selector);
  const state = {
    api: "",
    info: null,
    quality: "720",
    jobId: null,
    timer: null,
    offline: false,
    busy: false,
  };

  const els = {
    form: $("#probe-form"),
    url: $("#url"),
    paste: $("#paste-btn"),
    probe: $("#probe-btn"),
    status: $("#status"),
    offline: $("#offline-note"),
    offlineSettings: $("#offline-settings"),
    result: $("#result"),
    thumb: $("#thumb"),
    duration: $("#duration"),
    site: $("#site"),
    title: $("#title"),
    uploader: $("#uploader"),
    quality: $("#quality"),
    download: $("#download-btn"),
    cancel: $("#cancel-btn"),
    progress: $("#progress"),
    fill: $("#bar-fill"),
    stage: $("#stage"),
    pct: $("#pct"),
    saveRow: $("#save-row"),
    saveLink: $("#save-link"),
    fileNote: $("#file-note"),
    desktopHero: $("#desktop-hero"),
    desktopDownload: $("#desktop-download"),
    repoLink: $("#repo-link"),
    footerRepo: $("#footer-repo"),
    footerDesktop: $("#footer-desktop"),
    settings: $("#api-settings"),
    dialog: $("#api-dialog"),
    apiInput: $("#api-input"),
    apiForm: $("#api-form"),
    dialogHint: $("#dialog-hint"),
    year: $("#year"),
  };

  const cleanBase = (value) => (value || "").trim().replace(/\/+$/, "");
  const apiUrl = (path) => `${state.api}${path}`;

  function setStatus(text, kind = "") {
    els.status.textContent = text;
    els.status.className = `status ${kind}`.trim();
    els.status.hidden = !text;
  }

  function showOffline(show = true) {
    state.offline = show;
    els.offline.hidden = !show;
  }

  function extractUrl(text) {
    const match = String(text || "").match(/https?:\/\/[^\s<>"'）】]+/i);
    if (!match) return "";
    return match[0].replace(/[.,!?;:，。！？；：、）】》”’]+$/g, "");
  }

  function formatBytes(value) {
    if (!value && value !== 0) return "";
    let size = Number(value);
    const units = ["B", "KB", "MB", "GB"];
    for (const unit of units) {
      if (size < 1024 || unit === "GB") {
        return `${unit === "B" ? Math.round(size) : size.toFixed(1)} ${unit}`;
      }
      size /= 1024;
    }
    return "";
  }

  function formatSpeed(value) {
    return value ? `${formatBytes(value)}/s` : "";
  }

  function formatEta(value) {
    if (value === null || value === undefined) return "";
    const total = Math.max(0, Math.round(value));
    const minutes = Math.floor(total / 60);
    const seconds = total % 60;
    return minutes ? `${minutes}:${String(seconds).padStart(2, "0")}` : `${seconds}s`;
  }

  async function resolveApi() {
    if (CFG.apiBase) {
      state.api = cleanBase(CFG.apiBase);
      return;
    }
    const stored = localStorage.getItem("kedao_api");
    if (stored) {
      state.api = cleanBase(stored);
      return;
    }
    if (location.protocol !== "file:") {
      try {
        const response = await fetch("/api/health", {
          cache: "no-store",
          signal: AbortSignal.timeout(2500),
        });
        if (response.ok) {
          state.api = "";
          return;
        }
      } catch (error) {
        /* fall through to the configured backend */
      }
    }
    state.api = cleanBase(CFG.defaultApi);
  }

  async function checkHealth() {
    try {
      const response = await fetch(apiUrl("/api/health"), {
        cache: "no-store",
        signal: AbortSignal.timeout(6000),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!data.ok) throw new Error("not ok");
      showOffline(false);
      return true;
    } catch (error) {
      showOffline(true);
      return false;
    }
  }

  function setBusy(busy) {
    state.busy = busy;
    els.probe.disabled = busy;
    els.probe.style.opacity = busy ? ".6" : "";
    els.paste.disabled = busy;
    els.url.disabled = busy;
  }

  function resetJob() {
    clearTimeout(state.timer);
    state.timer = null;
    state.jobId = null;
    els.progress.hidden = true;
    els.saveRow.hidden = true;
    els.cancel.hidden = true;
    els.download.disabled = false;
    els.fill.style.width = "0%";
    els.pct.textContent = "0%";
    els.stage.textContent = "准备中…";
  }

  function renderQualities(data) {
    els.quality.replaceChildren();
    const options = data.qualities || [];
    const keys = options.map((item) => item.key);
    if (data.max_height && data.max_height < 720 && keys.includes("480")) {
      state.quality = "480";
    } else if (keys.includes("720")) {
      state.quality = "720";
    } else {
      state.quality = keys[0] || "720";
    }
    options.forEach((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "q-btn";
      button.setAttribute("role", "radio");
      button.setAttribute("aria-checked", String(item.key === state.quality));
      button.dataset.key = item.key;
      button.textContent = item.label;
      button.addEventListener("click", () => {
        state.quality = item.key;
        els.quality.querySelectorAll(".q-btn").forEach((node) => {
          node.setAttribute("aria-checked", String(node.dataset.key === item.key));
        });
      });
      els.quality.appendChild(button);
    });
  }

  function renderInfo(data) {
    state.info = data;
    els.title.textContent = data.title || "未命名视频";
    els.site.textContent = data.site_name || "视频";
    els.uploader.textContent = data.uploader ? `@ ${data.uploader}` : "作者未知";
    els.duration.textContent = data.duration_text || "";
    els.duration.hidden = !data.duration_text;
    if (data.thumbnail) {
      els.thumb.src = data.thumbnail;
      els.thumb.hidden = false;
    } else {
      els.thumb.removeAttribute("src");
      els.thumb.hidden = true;
    }
    renderQualities(data);
    els.result.hidden = false;
    resetJob();
    els.result.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async function probe() {
    if (state.busy) return;
    const raw = els.url.value.trim();
    const url = extractUrl(raw) || raw;
    if (!/^https?:\/\//i.test(url)) {
      setStatus("请粘贴有效的 http/https 视频链接。", "error");
      els.url.focus();
      return;
    }
    if (state.offline) {
      setStatus("在线解析服务未连接，请先看页脚的“连接设置”。", "error");
      showOffline(true);
      return;
    }
    setBusy(true);
    setStatus("正在解析，请稍候…");
    els.result.hidden = true;
    resetJob();
    try {
      const response = await fetch(apiUrl("/api/probe"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
        signal: AbortSignal.timeout(45000),
      });
      const data = await response.json().catch(() => ({ error: "服务返回异常" }));
      if (!response.ok) throw new Error(data.error || `解析失败（${response.status}）`);
      renderInfo(data);
      setStatus("解析完成，选择清晰度后下载。", "ok");
    } catch (error) {
      if (error.name === "TimeoutError" || error.name === "AbortError") {
        setStatus("解析超时。免费后端可能正在唤醒，请等半分钟再试一次。", "error");
      } else {
        setStatus(error.message || "解析失败，请稍后重试。", "error");
      }
    } finally {
      setBusy(false);
    }
  }

  function updateProgress(job) {
    if (job.percent !== null && job.percent !== undefined) {
      els.fill.style.width = `${Math.min(100, job.percent)}%`;
      els.pct.textContent = `${Math.round(job.percent)}%`;
    } else {
      els.fill.style.width = "4%";
      els.pct.textContent = "…";
    }
    const parts = [job.stage || "处理中…"];
    if (job.speed) parts.push(formatSpeed(job.speed));
    if (job.eta !== null && job.eta !== undefined) parts.push(`剩余 ${formatEta(job.eta)}`);
    els.stage.textContent = parts.join(" · ");
  }

  async function pollJob() {
    if (!state.jobId) return;
    try {
      const response = await fetch(apiUrl(`/api/jobs/${state.jobId}`), {
        cache: "no-store",
        signal: AbortSignal.timeout(15000),
      });
      const job = await response.json().catch(() => ({ error: "状态读取失败" }));
      if (!response.ok) throw new Error(job.error || "状态读取失败");
      els.progress.hidden = false;
      updateProgress(job);
      if (job.status === "done") {
        els.fill.style.width = "100%";
        els.pct.textContent = "100%";
        els.stage.textContent = "下载完成";
        els.saveRow.hidden = false;
        els.saveLink.href = apiUrl(job.download_url);
        els.saveLink.removeAttribute("download");
        els.fileNote.textContent = `${job.filename || "视频文件"}${
          job.filesize ? ` · ${formatBytes(job.filesize)}` : ""
        } · 服务器保留 60 分钟`;
        els.cancel.hidden = true;
        els.download.disabled = false;
        setStatus("下载完成，点击“保存文件”即可。", "ok");
        state.jobId = null;
        return;
      }
      if (job.status === "error" || job.status === "cancelled") {
        els.cancel.hidden = true;
        els.download.disabled = false;
        setStatus(job.error || (job.status === "cancelled" ? "已取消。" : "下载失败。"), "error");
        state.jobId = null;
        return;
      }
      state.timer = setTimeout(pollJob, 900);
    } catch (error) {
      els.cancel.hidden = true;
      els.download.disabled = false;
      setStatus(error.message || "任务状态读取失败，请重试。", "error");
      state.jobId = null;
    }
  }

  async function startDownload() {
    if (!state.info || state.busy) return;
    setBusy(true);
    resetJob();
    els.progress.hidden = false;
    els.cancel.hidden = false;
    els.download.disabled = true;
    els.stage.textContent = "提交任务…";
    els.fill.style.width = "2%";
    setStatus("正在开始下载…");
    try {
      const response = await fetch(apiUrl("/api/download"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: state.info.url, quality: state.quality }),
        signal: AbortSignal.timeout(20000),
      });
      const data = await response.json().catch(() => ({ error: "服务返回异常" }));
      if (!response.ok || !data.job) throw new Error(data.error || "无法创建下载任务");
      state.jobId = data.job.id;
      updateProgress(data.job);
      setStatus("任务已创建，正在下载…");
      pollJob();
    } catch (error) {
      els.cancel.hidden = true;
      els.download.disabled = false;
      setStatus(error.message || "无法开始下载。", "error");
    } finally {
      setBusy(false);
    }
  }

  async function cancelDownload() {
    if (!state.jobId) return;
    els.cancel.disabled = true;
    els.stage.textContent = "正在取消…";
    try {
      await fetch(apiUrl(`/api/jobs/${state.jobId}/cancel`), {
        method: "POST",
        signal: AbortSignal.timeout(10000),
      });
    } catch (error) {
      /* polling will surface the final state */
    } finally {
      els.cancel.disabled = false;
    }
  }

  async function pasteFromClipboard() {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        els.url.value = text.trim();
        els.url.focus();
        setStatus("已粘贴，点击“解析”。", "ok");
      } else {
        setStatus("剪贴板里没有文字。", "error");
      }
    } catch (error) {
      els.url.focus();
      setStatus("浏览器不允许读取剪贴板，请长按输入框手动粘贴。", "error");
    }
  }

  function initLinks() {
    const desktop = CFG.desktopUrl || "";
    const repo = CFG.repoUrl || "";
    const desktopReady = desktop && !desktop.includes("OWNER");
    const repoReady = repo && !repo.includes("OWNER");

    if (desktopReady) {
      els.desktopHero.href = desktop;
      els.desktopDownload.href = desktop;
    } else {
      [els.desktopHero, els.desktopDownload].forEach((link) => {
        link.setAttribute("aria-disabled", "true");
        link.style.opacity = ".65";
      });
      els.desktopDownload.addEventListener("click", (event) => {
        event.preventDefault();
        setStatus("Windows 桌面版下载将在 GitHub Release 发布后开放。", "error");
        document.querySelector("#app")?.scrollIntoView({ behavior: "smooth" });
      });
    }

    if (repoReady) {
      els.repoLink.href = repo;
      els.footerRepo.href = repo;
    } else {
      [els.repoLink, els.footerRepo].forEach((link) => {
        link.href = "#desktop";
        link.setAttribute("aria-disabled", "true");
      });
    }
    els.desktopHero.href = els.desktopHero.href || "#desktop";
    els.footerDesktop.href = "#desktop";
  }

  function initSettings() {
    els.settings.addEventListener("click", () => {
      els.apiInput.value = localStorage.getItem("kedao_api") || state.api || "";
      els.dialogHint.textContent = state.offline
        ? "当前未连接后端。"
        : "当前已连接。";
      els.dialog.showModal();
    });
    els.offlineSettings.addEventListener("click", () => els.settings.click());
    els.apiForm.addEventListener("submit", (event) => {
      if (event.submitter?.value !== "save") return;
      event.preventDefault();
      const value = cleanBase(els.apiInput.value);
      if (value && !/^https?:\/\//i.test(value)) {
        els.dialogHint.textContent = "地址需要以 http:// 或 https:// 开头。";
        return;
      }
      if (value) localStorage.setItem("kedao_api", value);
      else localStorage.removeItem("kedao_api");
      location.reload();
    });
  }

  els.thumb.addEventListener("error", () => {
    els.thumb.hidden = true;
    els.thumb.removeAttribute("src");
  });
  els.form.addEventListener("submit", (event) => {
    event.preventDefault();
    probe();
  });
  els.paste.addEventListener("click", pasteFromClipboard);
  els.download.addEventListener("click", startDownload);
  els.cancel.addEventListener("click", cancelDownload);
  els.url.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      probe();
    }
  });

  els.year.textContent = String(new Date().getFullYear());
  initLinks();
  initSettings();

  (async () => {
    await resolveApi();
    await checkHealth();
    if (state.offline) {
      setStatus("在线解析服务未连接，可先下载 Windows 桌面版。", "error");
    }
  })();

  if ("serviceWorker" in navigator && location.protocol === "https:") {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("./sw.js").catch(() => {});
    });
  }
})();
