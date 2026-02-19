import { fetchOverview, fetchHistory, fetchAlerts, triggerCollect } from "./api.js";
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
const MIN_REFRESH_INTERVAL_MS = 5000;
const MAX_REFRESH_INTERVAL_MS = 60000;

let loading = false;
let refreshIntervalMs = DEFAULT_REFRESH_INTERVAL_MS;
let nextAutoRefreshAt = Date.now() + DEFAULT_REFRESH_INTERVAL_MS;

async function collectAndLoad(source = "auto") {
  if (loading) return;
  loading = true;
  setLoadingState(true);
  setRefreshStatus("采集中...", "status-loading");

  try {
    await triggerCollect();

    setRefreshStatus("读取数据中...", "status-loading");

    const [overview, history, alerts] = await Promise.all([
      fetchOverview(),
      fetchHistory(120),
      fetchAlerts(50),
    ]);

    renderOverview(overview);
    renderTrendSummary(history);
    renderAlerts(alerts);
    setError("");

    nextAutoRefreshAt = Date.now() + refreshIntervalMs;
    updateRefreshHint(nextAutoRefreshAt, refreshIntervalMs);

    const at = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    const label = source === "manual" ? "手动采集完成" : "自动采集完成";
    setRefreshStatus(`${label} ${at}`, "status-success");
  } catch (err) {
    setError(err?.message || String(err));
    setRefreshStatus("采集失败", "status-error");
    nextAutoRefreshAt = Date.now() + refreshIntervalMs;
  } finally {
    loading = false;
    setLoadingState(false);
  }
}

function init() {
  const els = getEls();

  els.refreshBtn.addEventListener("click", () => collectAndLoad("manual"));

  if (els.collectBtn) {
    els.collectBtn.addEventListener("click", () => collectAndLoad("manual"));
  }

  nextAutoRefreshAt = Date.now() + refreshIntervalMs;
  updateRefreshHint(nextAutoRefreshAt, refreshIntervalMs);
  setRefreshStatus("启动中...", "status-loading");
  collectAndLoad("init");

  setInterval(() => {
    updateRefreshHint(nextAutoRefreshAt, refreshIntervalMs);
    if (!loading && Date.now() >= nextAutoRefreshAt) {
      collectAndLoad("auto");
    }
  }, 1000);
}

init();
