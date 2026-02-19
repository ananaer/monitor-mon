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

const LOGIC_DOCS = {
  price: [
    { cond: "创历史新高（lookback 96 点）", out: "score=1 · 方向做多" },
    { cond: "创历史新低（lookback 96 点）", out: "score=1 · 方向做空" },
    { cond: "斜率 > +0.5%（最近 12 点前后半段均值比）", out: "score=0.5 · 方向做多" },
    { cond: "斜率 < -0.5%", out: "score=0.5 · 方向做空" },
    { cond: "以上均不满足", out: "score=0 · 观望" },
  ],
  oi: [
    { cond: "OI 斜率 > +0.5% 且资金费率未到极端", out: "score=1 · 增仓不拥挤" },
    { cond: "OI 斜率 > +0.5% 且资金费率极端", out: "score=0.5 · 增仓但拥挤" },
    { cond: "OI 斜率 < -0.5%", out: "score=0 · 去杠杆（触发清算释放条件）" },
    { cond: "以上均不满足", out: "score=0.3 · 横盘" },
    { cond: "费率极端判定", out: "百分位 ≥85% 或 ≤15%，或绝对值 ≥0.03%（双条件取并集）" },
  ],
  exec: [
    { cond: "价差 > 基线（前段均值）× 1.5", out: "恶化 · 触发过滤" },
    { cond: "1% 深度 < 基线 × 0.7", out: "恶化 · 触发过滤" },
    { cond: "冲击成本 N2 > 基线 × 1.5", out: "恶化 · 触发过滤" },
    { cond: "以上均正常", out: "执行质量良好" },
    { cond: "基线定义", out: "同字段最近 96 点中去除末尾 6 点的均值" },
  ],
  classify: [
    { cond: "执行质量恶化（任意一项）", out: "→ 过滤，不交易" },
    { cond: "OI 去杠杆 且 价格 score ≥ 0.5", out: "→ 清算释放（价格有方向时取反，flat 时依据费率方向）" },
    { cond: "OI 拥挤 且 价格 score ≥ 0.5", out: "→ 挤仓突破（同向，小仓快出）" },
    { cond: "价格 score ≥ 0.5 且 OI score ≥ 0.8 且 执行质量正常", out: "→ 顺势延续" },
    { cond: "其余", out: "→ 观望" },
  ],
};

function logicTable(rows) {
  return `<table class="logic-table">
    <thead><tr><th>条件</th><th>结果</th></tr></thead>
    <tbody>${rows.map((r) => `<tr><td>${escapeHtml(r.cond)}</td><td>${escapeHtml(r.out)}</td></tr>`).join("")}</tbody>
  </table>`;
}

function logicPanel() {
  return `<div class="logic-panel" id="logic-panel">
    <div class="logic-section">
      <p class="logic-title">A · 价格结构（Price Breakout）</p>
      ${logicTable(LOGIC_DOCS.price)}
    </div>
    <div class="logic-section">
      <p class="logic-title">B · 衍生品拥挤度（OI + Funding Rate）</p>
      ${logicTable(LOGIC_DOCS.oi)}
    </div>
    <div class="logic-section">
      <p class="logic-title">C · 执行质量（Execution Quality）</p>
      ${logicTable(LOGIC_DOCS.exec)}
    </div>
    <div class="logic-section">
      <p class="logic-title">D · 信号分类（Signal Classifier）</p>
      ${logicTable(LOGIC_DOCS.classify)}
    </div>
  </div>`;
}

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

function scoreChip(score) {
  const s = Number(score);
  if (!Number.isFinite(s)) return "";
  const color = s >= 0.8 ? "#15803d" : s >= 0.5 ? "#d97706" : "#94a3b8";
  const bg = s >= 0.8 ? "#dcfce7" : s >= 0.5 ? "#fef3c7" : "#f1f5f9";
  return `<span class="sig-score-chip" style="color:${color};background:${bg}">${s.toFixed(1)}</span>`;
}

function componentRow(label, detail, ok, score) {
  const dot = ok ? "#15803d" : "#94a3b8";
  return `
    <div class="sig-comp-row">
      <span class="sig-comp-dot" style="background:${escapeHtml(dot)}"></span>
      <span class="sig-comp-label">${escapeHtml(label)}</span>
      ${scoreChip(score)}
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
        ${componentRow("A 价格结构", price.detail, price.score >= 0.5, price.score)}
        ${componentRow("B 拥挤度", oi.detail, oi.score >= 0.5 && !oi.crowded, oi.score)}
        ${componentRow("C 执行质量", exec.detail, !exec.degraded, exec.degraded ? 0 : 1)}
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

let _logicOpen = false;

export function renderSignals(history, overviewVenues) {
  const container = document.getElementById("signals-container");
  if (!container) return;

  const results = computeSignals(history, overviewVenues);
  if (results.length === 0) {
    container.innerHTML = '<p class="muted">暂无信号数据</p>';
    return;
  }

  const toggleId = "sig-logic-toggle";
  const panelId = "sig-logic-body";

  const bodyClass = _logicOpen ? "logic-body" : "logic-body hidden";
  const arrowChar = _logicOpen ? "&#9662;" : "&#9656;";

  container.innerHTML = `
    <div class="signals-grid">${results.map(renderSignalCard).join("")}</div>
    <div class="logic-disclosure">
      <button class="logic-toggle" id="${toggleId}" aria-expanded="${_logicOpen}">
        计算逻辑 &nbsp;<span class="logic-toggle-arrow" id="sig-logic-arrow">${arrowChar}</span>
      </button>
      <div class="${bodyClass}" id="${panelId}">
        ${logicPanel()}
      </div>
    </div>`;

  document.getElementById(toggleId)?.addEventListener("click", () => {
    const body = document.getElementById(panelId);
    const arrow = document.getElementById("sig-logic-arrow");
    if (!body) return;
    _logicOpen = !_logicOpen;
    body.classList.toggle("hidden", !_logicOpen);
    if (arrow) arrow.innerHTML = _logicOpen ? "&#9662;" : "&#9656;";
    document.getElementById(toggleId)?.setAttribute("aria-expanded", String(_logicOpen));
  });
}
