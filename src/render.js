import {
  formatNumber,
  formatSignedPercent,
  formatTime,
  secondsFromNow,
  getSignClass,
  getRatioClass,
  escapeHtml,
} from "./format.js";

const els = {
  tokenName: document.getElementById("token-name"),
  dbPath: document.getElementById("db-path"),
  updatedAt: document.getElementById("updated-at"),
  collectorStatusText: document.getElementById("collector-status-text"),
  collectorStatusExtra: document.getElementById("collector-status-extra"),
  collectorError: document.getElementById("collector-error"),
  refreshBtn: document.getElementById("refresh-btn"),
  collectBtn: document.getElementById("collect-btn"),
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

export function getEls() {
  return els;
}

export function setLoadingState(isLoading) {
  els.refreshBtn.disabled = isLoading;
  els.refreshBtn.textContent = isLoading ? "刷新中..." : "立即刷新";
}

export function setRefreshStatus(text, cls) {
  els.refreshStatus.textContent = `状态：${text}`;
  els.refreshStatus.className = `refresh-status ${cls || "status-running"}`;
}

export function setError(message) {
  if (!message) {
    els.errorBox.classList.add("hidden");
    els.errorBox.textContent = "";
    return;
  }
  els.errorBox.textContent = message;
  els.errorBox.classList.remove("hidden");
}

export function renderCollectorStatus(collector) {
  if (!collector) {
    els.collectorStatusText.textContent = "未知";
    els.collectorStatusText.className = "collector-stopped";
    els.collectorStatusExtra.textContent = "";
    els.collectorError.classList.add("hidden");
    return;
  }

  const status = collector.service_status || "unknown";
  const labels = { running: "运行中", degraded: "异常恢复中", stale: "数据陈旧", stopped: "已停止" };
  const classes = { running: "collector-ok", degraded: "collector-degraded", stale: "collector-stale", stopped: "collector-stopped" };

  els.collectorStatusText.textContent = labels[status] ?? "未知";
  els.collectorStatusText.className = classes[status] ?? "collector-stopped";

  const age = collector.last_success_age_seconds;
  let extra = typeof age === "number" ? `（上次成功 ${age}s 前）` : "";
  els.collectorStatusExtra.textContent = extra;
  els.collectorError.classList.add("hidden");
}

export function renderKpis(overview) {
  const venues = overview.venues || [];
  const stats = overview.stats || {};
  const online = venues.filter((v) => v.status === "ok").length;
  const spreadValues = venues.map((v) => v.spread_bps).filter((v) => typeof v === "number");
  const avgSpread = spreadValues.length > 0 ? spreadValues.reduce((a, b) => a + b, 0) / spreadValues.length : null;
  const totalDepth = venues.reduce((acc, v) => acc + (Number(v.depth_1pct_total_usdt) || 0), 0);

  els.kpiVenueCount.textContent = String(stats.venue_count ?? venues.length ?? 0);
  els.kpiOnlineCount.textContent = String(online);
  els.kpiAlerts24h.textContent = String(stats.alerts_24h ?? 0);
  els.kpiCritical24h.textContent = String(stats.critical_alerts_24h ?? 0);
  els.kpiAvgSpread.textContent = formatNumber(avgSpread, 2);
  els.kpiTotalDepth.textContent = `$${formatNumber(totalDepth, 0)}`;
}

function buildStatusHintText(status, successTs, snapshotAgeRaw) {
  const successAge = secondsFromNow(successTs);
  const snapshotAge = Number(snapshotAgeRaw);
  if (status === "ok") {
    if (successAge === null) return "状态正常";
    if (successAge <= 2) return "刚刚更新";
    return `${successAge}s 前更新`;
  }
  if (status === "stale") {
    if (Number.isFinite(snapshotAge) && snapshotAge >= 0) return `数据 ${snapshotAge}s 未更新`;
    return "数据陈旧";
  }
  if (successAge !== null) return `上次成功 ${successAge}s 前`;
  return "暂无成功样本";
}

export function renderVenueTable(overview) {
  const venues = overview.venues || [];
  const rowsHtml = venues.map((venue) => {
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
        <p class="tiny">${escapeHtml(buildStatusHintText(venue.status, venue.last_success_ts_utc || venue.snapshot_ts_utc, venue.snapshot_age_seconds))}</p>
        ${venue.error_reason && venue.status !== "ok" ? `<p class="tiny">${escapeHtml(venue.error_reason)}</p>` : ""}
      </td>
      <td>${escapeHtml(formatNumber(venue.last_price, 6))}</td>
      <td class="${escapeHtml(getSignClass(venue.pct_change_1h))}">${escapeHtml(formatSignedPercent(venue.pct_change_1h))}</td>
      <td>$${escapeHtml(formatNumber(venue.quote_volume_24h, 0))}</td>
      <td>${escapeHtml(formatNumber(venue.spread_bps, 2))}</td>
      <td>$${escapeHtml(formatNumber(venue.depth_1pct_total_usdt, 0))}</td>
      <td>${escapeHtml(formatNumber(venue.slip_bps_n2, 2))}</td>
      <td>
        <span class="${escapeHtml(getRatioClass(ratio))}">
          ${escapeHtml(ratio === null || ratio === undefined ? "-" : `${Number(ratio).toFixed(2)}x`)}
        </span>
      </td>
    </tr>`;
  }).join("");

  els.venueTbody.innerHTML = rowsHtml || '<tr><td colspan="9">暂无数据</td></tr>';
}

export function renderAlerts(alerts) {
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
  els.alertList.innerHTML = items.map((alert) => `
    <li class="alert-item">
      <div>
        <span class="severity-tag sev-${escapeHtml(alert.severity || "info")}">${escapeHtml(alert.severity || "info")}</span>
        <strong>${escapeHtml(alert.alert_type || "-")}</strong>
        <span class="muted">${escapeHtml((alert.venue || "-").toUpperCase())}</span>
      </div>
      <p>${escapeHtml(alert.message || "-")}</p>
      <p class="tiny">${escapeHtml(formatTime(alert.ts_utc))}</p>
    </li>`).join("");
}

export function renderTrendSummary(history) {
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

export function renderOverview(overview) {
  els.tokenName.textContent = overview.token_hint || "TOKEN";
  els.dbPath.textContent = overview.db_path || "-";
  els.updatedAt.textContent = formatTime(overview.updated_at_utc);
  renderCollectorStatus(overview.collector);
  renderKpis(overview);
  renderVenueTable(overview);
}

export function updateRefreshHint(nextAutoRefreshAt, refreshIntervalMs) {
  const remainMs = Math.max(0, nextAutoRefreshAt - Date.now());
  const remainSec = Math.ceil(remainMs / 1000);
  const intervalSec = Math.ceil(refreshIntervalMs / 1000);
  els.refreshHint.textContent = `自动刷新倒计时：${remainSec}s（周期 ${intervalSec}s）`;
}
