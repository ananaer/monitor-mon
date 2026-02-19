import {
  getEls,
  setLoadingState,
  setRefreshStatus,
  setError,
  renderOverview,
  renderTrendSummary,
  renderAlerts,
  updateRefreshHint,
} from "./render.js";

const DEFAULT_REFRESH_INTERVAL_MS = 15000;

let loading = false;
let refreshIntervalMs = DEFAULT_REFRESH_INTERVAL_MS;
let nextAutoRefreshAt = Date.now() + DEFAULT_REFRESH_INTERVAL_MS;
let worker = null;

function createWorker() {
  const workerUrl = new URL("./collector.worker.js", import.meta.url);
  worker = new Worker(workerUrl, { type: "module" });

  worker.onmessage = (e) => {
    const msg = e.data;

    if (msg.type === "status") {
      if (msg.status === "collecting") {
        setRefreshStatus("采集中...", "status-loading");
      } else if (msg.status === "fetching") {
        setRefreshStatus("读取数据中...", "status-loading");
      }
      return;
    }

    if (msg.type === "data") {
      renderOverview(msg.overview);
      renderTrendSummary(msg.history);
      renderAlerts(msg.alerts);
      setError("");

      nextAutoRefreshAt = Date.now() + refreshIntervalMs;
      updateRefreshHint(nextAutoRefreshAt, refreshIntervalMs);

      const at = new Date().toLocaleTimeString("zh-CN", { hour12: false });
      setRefreshStatus(`采集完成 ${at}`, "status-success");

      loading = false;
      setLoadingState(false);
      return;
    }

    if (msg.type === "error") {
      setError(msg.message);
      setRefreshStatus("采集失败", "status-error");

      nextAutoRefreshAt = Date.now() + refreshIntervalMs;
      updateRefreshHint(nextAutoRefreshAt, refreshIntervalMs);

      loading = false;
      setLoadingState(false);
      return;
    }
  };

  worker.onerror = (err) => {
    setError(err.message || "Worker 错误");
    setRefreshStatus("Worker 错误", "status-error");
    loading = false;
    setLoadingState(false);
  };
}

function triggerFetch() {
  if (loading) return;
  loading = true;
  setLoadingState(true);
  worker.postMessage({ type: "fetch" });
}

function triggerCollect() {
  if (loading) return;
  loading = true;
  setLoadingState(true);
  worker.postMessage({ type: "collect" });
}

function init() {
  const els = getEls();

  createWorker();

  els.refreshBtn.addEventListener("click", triggerFetch);

  if (els.collectBtn) {
    els.collectBtn.addEventListener("click", triggerCollect);
  }

  nextAutoRefreshAt = Date.now() + refreshIntervalMs;
  updateRefreshHint(nextAutoRefreshAt, refreshIntervalMs);
  setRefreshStatus("启动中...", "status-loading");

  loading = true;
  setLoadingState(true);
  worker.postMessage({
    type: "init",
    supabaseUrl: import.meta.env.VITE_SUPABASE_URL,
    anonKey: import.meta.env.VITE_SUPABASE_ANON_KEY,
  });

  setInterval(() => {
    updateRefreshHint(nextAutoRefreshAt, refreshIntervalMs);
    if (!loading && Date.now() >= nextAutoRefreshAt) {
      triggerCollect();
    }
  }, 1000);
}

init();
