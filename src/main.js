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
const MAX_REFRESH_INTERVAL_MS = 30000;

let loading = false;
let refreshIntervalMs = DEFAULT_REFRESH_INTERVAL_MS;
let nextAutoRefreshAt = Date.now() + DEFAULT_REFRESH_INTERVAL_MS;

async function loadAll(source = "auto") {
  if (loading) return;
  loading = true;
  setLoadingState(true);
  setRefreshStatus("刷新中", "status-loading");
  try {
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
    setRefreshStatus(source === "manual" ? `手动刷新成功 ${at}` : `自动刷新成功 ${at}`, "status-success");

    const schedule = overview?.collector?.schedule_seconds;
    if (typeof schedule === "number") {
      const target = Math.floor((schedule * 1000) / 2);
      refreshIntervalMs = Math.max(MIN_REFRESH_INTERVAL_MS, Math.min(MAX_REFRESH_INTERVAL_MS, target));
    }
  } catch (err) {
    setError(err?.message || String(err));
    setRefreshStatus("刷新失败", "status-error");
  } finally {
    loading = false;
    setLoadingState(false);
  }
}

async function runCollect() {
  const els = getEls();
  if (!els.collectBtn) return;
  els.collectBtn.disabled = true;
  els.collectBtn.textContent = "采集中...";
  try {
    await triggerCollect();
    await loadAll("manual");
  } catch (err) {
    setError(err?.message || String(err));
  } finally {
    els.collectBtn.disabled = false;
    els.collectBtn.textContent = "立即采集";
  }
}

function init() {
  const els = getEls();
  els.refreshBtn.addEventListener("click", () => loadAll("manual"));
  if (els.collectBtn) {
    els.collectBtn.addEventListener("click", runCollect);
  }

  nextAutoRefreshAt = Date.now() + refreshIntervalMs;
  updateRefreshHint(nextAutoRefreshAt, refreshIntervalMs);
  setRefreshStatus("运行中", "status-running");
  loadAll("init");

  setInterval(() => {
    updateRefreshHint(nextAutoRefreshAt, refreshIntervalMs);
    if (!loading && Date.now() >= nextAutoRefreshAt) {
      loadAll("auto");
    }
  }, 1000);
}

init();
