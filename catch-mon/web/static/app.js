const DEFAULT_REFRESH_INTERVAL_MS = 15000;
const MIN_REFRESH_INTERVAL_MS = 5000;
const MAX_REFRESH_INTERVAL_MS = 30000;

const els = {
  tokenName: document.getElementById("token-name"),
  dbPath: document.getElementById("db-path"),
  updatedAt: document.getElementById("updated-at"),
  collectorStatusText: document.getElementById("collector-status-text"),
  collectorStatusExtra: document.getElementById("collector-status-extra"),
  collectorError: document.getElementById("collector-error"),
  refreshBtn: document.getElementById("refresh-btn"),
  refreshHint: document.getElementById("refresh-hint"),
  refreshStatus: document.getElementById("refresh-status"),
  errorBox: document.getElementById("error-box"),
  kpiVenueCount: document.getElementById("kpi-venue-count"),
  kpiOnlineCount: document.getElementById("kpi-online-count"),
  kpiAlerts24h: document.getElementById("kpi-alerts-24h"),
  kpiCritical24h: document.getElementById("kpi-critical-24h"),
  kpiAvgSpread: document.getElementById("kpi-avg-spread"),
  kpiTotalDepth: document.getElementById("kpi-total-depth"),
  venueTbody: document.getElementById("venue-tbody"),
  trendSummary: document.getElementById("trend-summary"),
  alertCount: document.getElementById("alert-count"),
  alertEmpty: document.getElementById("alert-empty"),
  alertList: document.getElementById("alert-list"),
};

let loading = false;
let refreshIntervalMs = DEFAULT_REFRESH_INTERVAL_MS;
let nextAutoRefreshAt = Date.now() + DEFAULT_REFRESH_INTERVAL_MS;
let latestOverview = null;

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return Number(value).toLocaleString("zh-CN", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits > 0 ? Math.min(digits, 2) : 0,
  });
}

function formatSignedPercent(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${Number(value).toFixed(2)}%`;
}

function formatTime(ts) {
  if (!ts) return "-";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleString("zh-CN", { hour12: false });
}

function secondsFromNow(ts) {
  if (!ts) return null;
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return null;
  return Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
}

function getSignClass(value) {
  if (value === null || value === undefined) return "";
  if (value > 0) return "up";
  if (value < 0) return "down";
  return "";
}

function getRatioClass(value) {
  if (value === null || value === undefined) return "ratio-neutral";
  if (value >= 1) return "ratio-good";
  if (value >= 0.7) return "ratio-mid";
  return "ratio-bad";
}

function escapeHtml(raw) {
  return String(raw ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function fetchJson(url, timeoutMs = 10000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(url, {
      cache: "no-store",
      signal: controller.signal,
    });
    if (!resp.ok) {
      throw new Error(`请求失败 ${resp.status}: ${url}`);
    }
    return await resp.json();
  } finally {
    clearTimeout(timer);
  }
}

function setLoadingState(isLoading) {
  loading = isLoading;
  els.refreshBtn.disabled = isLoading;
  els.refreshBtn.textContent = isLoading ? "刷新中..." : "立即刷新";
}

function setRefreshStatus(text, cls) {
  els.refreshStatus.textContent = `状态：${text}`;
  els.refreshStatus.classList.remove(
    "status-running",
    "status-loading",
    "status-success",
    "status-error"
  );
  els.refreshStatus.classList.add(cls || "status-running");
}

function updateRefreshHint() {
  const remainMs = Math.max(0, nextAutoRefreshAt - Date.now());
  const remainSec = Math.ceil(remainMs / 1000);
  const intervalSec = Math.ceil(refreshIntervalMs / 1000);
  els.refreshHint.textContent = `自动刷新倒计时：${remainSec}s（周期 ${intervalSec}s）`;
}

function setError(message) {
  if (!message) {
    els.errorBox.classList.add("hidden");
    els.errorBox.textContent = "";
    return;
  }
  els.errorBox.textContent = message;
  els.errorBox.classList.remove("hidden");
}

function renderCollectorStatus(collector) {
  if (!collector) {
    els.collectorStatusText.textContent = "未知";
    els.collectorStatusText.className = "collector-stopped";
    els.collectorStatusExtra.textContent = "";
    els.collectorError.classList.add("hidden");
    els.collectorError.textContent = "";
    return;
  }

  const status = collector.service_status || "unknown";
  let label = "未知";
  let cls = "collector-stopped";
  if (status === "running") {
    label = "运行中";
    cls = "collector-ok";
  } else if (status === "degraded") {
    label = "异常恢复中";
    cls = "collector-degraded";
  } else if (status === "stale") {
    label = "数据陈旧";
    cls = "collector-stale";
  } else if (status === "stopped") {
    label = "已停止";
    cls = "collector-stopped";
  }

  const age = collector.last_success_age_seconds;
  const schedule = collector.schedule_seconds;
  const cycleSeq = collector.cycle_seq;
  const cycleDuration = collector.last_cycle_duration_ms;
  let extra = "";
  if (typeof age === "number") {
    extra = `（上次成功 ${age}s 前）`;
  }
  if (typeof schedule === "number") {
    extra += `${extra ? " " : ""}[周期 ${schedule}s]`;
    const target = Math.floor((schedule * 1000) / 2);
    refreshIntervalMs = Math.max(MIN_REFRESH_INTERVAL_MS, Math.min(MAX_REFRESH_INTERVAL_MS, target));
  }
  if (typeof cycleSeq === "number") {
    extra += `${extra ? " " : ""}[轮次 #${cycleSeq}]`;
  }
  if (typeof cycleDuration === "number") {
    extra += `${extra ? " " : ""}[耗时 ${cycleDuration}ms]`;
  }

  els.collectorStatusText.textContent = label;
  els.collectorStatusText.className = cls;
  els.collectorStatusExtra.textContent = extra;

  if (collector.last_error) {
    els.collectorError.textContent = `采集错误: ${collector.last_error}`;
    els.collectorError.classList.remove("hidden");
  } else {
    els.collectorError.textContent = "";
    els.collectorError.classList.add("hidden");
  }
}

function renderKpis(overview) {
  const venues = overview.venues || [];
  const stats = overview.stats || {};

  const online = venues.filter((v) => v.status === "ok").length;
  const spreadValues = venues
    .map((v) => v.spread_bps)
    .filter((v) => typeof v === "number");
  const avgSpread =
    spreadValues.length > 0
      ? spreadValues.reduce((a, b) => a + b, 0) / spreadValues.length
      : null;
  const totalDepth = venues.reduce(
    (acc, v) => acc + (Number(v.depth_1pct_total_usdt) || 0),
    0
  );

  els.kpiVenueCount.textContent = String(stats.venue_count ?? venues.length ?? 0);
  els.kpiOnlineCount.textContent = String(online);
  els.kpiAlerts24h.textContent = String(stats.alerts_24h ?? 0);
  els.kpiCritical24h.textContent = String(stats.critical_alerts_24h ?? 0);
  els.kpiAvgSpread.textContent = formatNumber(avgSpread, 2);
  els.kpiTotalDepth.textContent = `$${formatNumber(totalDepth, 0)}`;
}

function renderVenueTable(overview) {
  const venues = overview.venues || [];
  const rowsHtml = venues
    .map((venue) => {
      const ratio = venue?.ratios?.depth_vs_baseline;
      return `
      <tr>
        <td>
          <strong>${escapeHtml((venue.venue || "-").toUpperCase())}</strong>
          <p class="tiny">${escapeHtml(venue.symbol || "-")}</p>
        </td>
        <td>
          <span class="status-tag status-${escapeHtml(venue.status || "down")}">
            ${escapeHtml(venue.status || "down")}
          </span>
          <p
            class="tiny js-status-hint"
            data-status="${escapeHtml(venue.status || "")}"
            data-success-ts="${escapeHtml(venue.last_success_ts_utc || venue.snapshot_ts_utc || "")}"
            data-lag="${escapeHtml(venue.data_lag_seconds)}"
            data-age="${escapeHtml(venue.snapshot_age_seconds)}"
          ></p>
          ${
            venue.error_reason && venue.status !== "ok"
              ? `<p class="tiny">${escapeHtml(venue.error_reason)}</p>`
              : ""
          }
        </td>
        <td>${escapeHtml(formatNumber(venue.last_price, 6))}</td>
        <td class="${escapeHtml(getSignClass(venue.pct_change_1h))}">
          ${escapeHtml(formatSignedPercent(venue.pct_change_1h))}
        </td>
        <td>$${escapeHtml(formatNumber(venue.quote_volume_24h, 0))}</td>
        <td>${escapeHtml(formatNumber(venue.spread_bps, 2))}</td>
        <td>$${escapeHtml(formatNumber(venue.depth_1pct_total_usdt, 0))}</td>
        <td>${escapeHtml(formatNumber(venue.slip_bps_n2, 2))}</td>
        <td>
          <span class="${escapeHtml(getRatioClass(ratio))}">
            ${escapeHtml(ratio === null || ratio === undefined ? "-" : `${Number(ratio).toFixed(2)}x`)}
          </span>
        </td>
      </tr>
    `;
    })
    .join("");

  els.venueTbody.innerHTML = rowsHtml || '<tr><td colspan="9">暂无数据</td></tr>';
  refreshStatusHintTexts();
}

function buildStatusHintText(status, successTs, lagRaw, snapshotAgeRaw) {
  const successAge = secondsFromNow(successTs);
  const snapshotAge = Number(snapshotAgeRaw);
  if (status === "ok") {
    if (successAge === null) return "状态正常";
    if (successAge <= 2) return "刚刚更新";
    return `${successAge}s 前更新`;
  }
  if (status === "stale") {
    if (Number.isFinite(snapshotAge) && snapshotAge >= 0) {
      return `数据 ${snapshotAge}s 未更新`;
    }
    return "数据陈旧";
  }
  const lag = Number(lagRaw);
  if (Number.isFinite(lag) && lag >= 0) return `距最近成功 ${lag}s`;
  if (successAge !== null) return `上次成功 ${successAge}s 前`;
  return "暂无成功样本";
}

function refreshStatusHintTexts() {
  const nodes = document.querySelectorAll(".js-status-hint");
  nodes.forEach((node) => {
    const status = node.getAttribute("data-status") || "";
    const successTs = node.getAttribute("data-success-ts") || "";
    const lagRaw = node.getAttribute("data-lag");
    const snapshotAgeRaw = node.getAttribute("data-age");
    node.textContent = buildStatusHintText(status, successTs, lagRaw, snapshotAgeRaw);
  });
}

function renderAlerts(alerts) {
  const items = alerts?.items || [];
  els.alertCount.textContent = `最近 ${items.length} 条`;
  if (items.length === 0) {
    els.alertEmpty.classList.remove("hidden");
    els.alertList.classList.add("hidden");
    els.alertList.innerHTML = "";
    return;
  }

  els.alertEmpty.classList.add("hidden");
  els.alertList.classList.remove("hidden");
  els.alertList.innerHTML = items
    .map(
      (alert) => `
      <li class="alert-item">
        <div>
          <span class="severity-tag sev-${escapeHtml(alert.severity || "info")}">
            ${escapeHtml(alert.severity || "info")}
          </span>
          <strong>${escapeHtml(alert.alert_type || "-")}</strong>
          <span class="muted">${escapeHtml((alert.venue || "-").toUpperCase())}</span>
        </div>
        <p>${escapeHtml(alert.message || "-")}</p>
        <p class="tiny">${escapeHtml(formatTime(alert.ts_utc))}</p>
      </li>
    `
    )
    .join("");
}

function renderTrendSummary(history) {
  const byVenue = history?.by_venue || {};
  const venues = Object.keys(byVenue);
  if (venues.length === 0) {
    els.trendSummary.textContent = "暂无趋势数据";
    return;
  }
  const lines = venues.map((venue) => {
    const points = byVenue[venue] || [];
    const latest = points.length > 0 ? points[points.length - 1] : null;
    return `${venue.toUpperCase()}  价格: ${formatNumber(latest?.last_price, 6)}  价差: ${formatNumber(latest?.spread_bps, 2)} bps  深度: $${formatNumber(latest?.depth_1pct_total_usdt, 0)}`;
  });
  els.trendSummary.textContent = lines.join("\n");
}

function renderOverview(overview) {
  latestOverview = overview;
  els.tokenName.textContent = overview.token_hint || "TOKEN";
  els.dbPath.textContent = overview.db_path || "-";
  els.updatedAt.textContent = formatTime(overview.updated_at_utc);
  renderCollectorStatus(overview.collector);
  renderKpis(overview);
  renderVenueTable(overview);
}

async function loadAll(source = "auto") {
  if (loading) {
    if (source === "manual") {
      setRefreshStatus("已有刷新进行中", "status-loading");
    }
    return;
  }
  setLoadingState(true);
  setRefreshStatus("刷新中", "status-loading");
  try {
    const [overview, history, alerts] = await Promise.all([
      fetchJson("/api/overview"),
      fetchJson("/api/history?limit=120"),
      fetchJson("/api/alerts?limit=50"),
    ]);
    renderOverview(overview);
    renderTrendSummary(history);
    renderAlerts(alerts);
    setError("");
    nextAutoRefreshAt = Date.now() + refreshIntervalMs;
    updateRefreshHint();
    const now = new Date();
    const at = now.toLocaleTimeString("zh-CN", { hour12: false });
    if (source === "manual") {
      setRefreshStatus(`手动刷新成功 ${at}`, "status-success");
    } else if (source === "auto") {
      setRefreshStatus(`自动刷新成功 ${at}`, "status-success");
    } else {
      setRefreshStatus("运行中", "status-running");
    }
  } catch (err) {
    setError(err?.message || String(err));
    setRefreshStatus("刷新失败", "status-error");
  } finally {
    setLoadingState(false);
  }
}

function init() {
  els.refreshBtn.addEventListener("click", () => loadAll("manual"));
  nextAutoRefreshAt = Date.now() + refreshIntervalMs;
  updateRefreshHint();
  setRefreshStatus("运行中", "status-running");
  loadAll("init");
  setInterval(() => {
    updateRefreshHint();
    refreshStatusHintTexts();
    if (!loading && Date.now() >= nextAutoRefreshAt) {
      loadAll("auto");
    }
  }, 1000);
}

init();
