import { computeSignals } from "./signal.js";
import { escapeHtml } from "./format.js";

const SIGNAL_CONFIG = {
  trend: { label: "顺势延续", icon: "&#8593;", bg: "#f0fdf4", border: "#86efac", badge: "#15803d", badgeBg: "#dcfce7" },
  squeeze: { label: "挤仓突破", icon: "&#9888;", bg: "#fffbeb", border: "#fde68a", badge: "#b45309", badgeBg: "#fef3c7" },
  reversal: { label: "清算释放", icon: "&#8635;", bg: "#f0f9ff", border: "#7dd3fc", badge: "#0369a1", badgeBg: "#e0f2fe" },
  filter: { label: "过滤", icon: "&#8856;", bg: "#fff1f2", border: "#fda4af", badge: "#be123c", badgeBg: "#ffe4e6" },
  wait: { label: "观望", icon: "&#8211;", bg: "#f8fafc", border: "#e2e8f0", badge: "#64748b", badgeBg: "#f1f5f9" },
};

const DIR_LABEL = { long: "做多", short: "做空", flat: "横盘" };

function confidenceBar(pct) {
  if (!pct) return "";
  const w = Math.min(100, Math.max(0, pct));
  const color = w >= 70 ? "#15803d" : w >= 40 ? "#d97706" : "#94a3b8";
  return `
    <div class="sig-conf-row">
      <span class="sig-conf-label">信号强度</span>
      <div class="sig-conf-track">
        <div class="sig-conf-fill" style="width:${w}%;background:${escapeHtml(color)}"></div>
      </div>
      <span class="sig-conf-val">${w}%</span>
    </div>`;
}

function componentRow(icon, label, detail, ok) {
  const dot = ok ? "#15803d" : "#94a3b8";
  return `
    <div class="sig-comp-row">
      <span class="sig-comp-dot" style="background:${escapeHtml(dot)}"></span>
      <span class="sig-comp-label">${escapeHtml(label)}</span>
      <span class="sig-comp-detail">${escapeHtml(detail || "-")}</span>
    </div>`;
}

function renderSignalCard(item) {
  const cfg = SIGNAL_CONFIG[item.signal.type] || SIGNAL_CONFIG.wait;
  const { price, oi, exec } = item.components;
  const dir = item.signal.direction ? DIR_LABEL[item.signal.direction] || "" : "";

  const dirTag = dir
    ? `<span class="sig-dir-tag sig-dir-${escapeHtml(item.signal.direction)}">${escapeHtml(dir)}</span>`
    : "";

  const components = price && oi && exec
    ? `<div class="sig-components">
        ${componentRow("&#128200;", "价格结构", price.detail, price.score >= 0.5)}
        ${componentRow("&#128196;", "衍生品拥挤度", oi.detail, oi.score >= 0.5 && !oi.crowded)}
        ${componentRow("&#9654;", "执行质量", exec.detail, !exec.degraded)}
      </div>`
    : "";

  return `
    <div class="signal-card" style="background:${escapeHtml(cfg.bg)};border-color:${escapeHtml(cfg.border)}">
      <div class="sig-header">
        <div class="sig-venue-row">
          <span class="sig-venue">${escapeHtml(item.venue.toUpperCase())}</span>
          ${dirTag}
        </div>
        <span class="sig-badge" style="color:${escapeHtml(cfg.badge)};background:${escapeHtml(cfg.badgeBg)}">
          ${cfg.icon}&nbsp;${escapeHtml(item.signal.label)}
        </span>
      </div>
      <p class="sig-description">${escapeHtml(item.signal.description)}</p>
      ${item.signal.confidence ? confidenceBar(item.signal.confidence) : ""}
      ${components}
    </div>`;
}

export function renderSignals(history, overviewVenues) {
  const container = document.getElementById("signals-container");
  if (!container) return;

  const results = computeSignals(history, overviewVenues);
  if (results.length === 0) {
    container.innerHTML = '<p class="muted">暂无信号数据</p>';
    return;
  }

  container.innerHTML = `<div class="signals-grid">${results.map(renderSignalCard).join("")}</div>`;
}
