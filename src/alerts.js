import { formatTime, escapeHtml } from "./format.js";

const PAGE_SIZE = 50;

const els = {
  refreshBtn: document.getElementById("refresh-btn"),
  refreshStatus: document.getElementById("refresh-status"),
  statsRow: document.getElementById("stats-row"),
  filterBar: document.getElementById("filter-bar"),
  statTotal: document.getElementById("stat-total"),
  statCritical: document.getElementById("stat-critical"),
  statWarn: document.getElementById("stat-warn"),
  statVenues: document.getElementById("stat-venues"),
  severityPills: document.getElementById("severity-pills"),
  venueSelect: document.getElementById("venue-select"),
  resultCount: document.getElementById("result-count"),
  emptyState: document.getElementById("empty-state"),
  errorState: document.getElementById("error-state"),
  alertList: document.getElementById("alert-list"),
  loadMoreWrap: document.getElementById("load-more-wrap"),
  loadMoreBtn: document.getElementById("load-more-btn"),
  fiGrid: document.getElementById("fi-grid"),
  fiBadge: document.getElementById("fi-badge"),
  fiMeta: document.getElementById("fi-meta"),
};

let allAlerts = [];
let filteredAlerts = [];
let displayedCount = 0;
let activeSeverity = "all";
let activeVenue = "all";
let isLoading = false;

function setStatus(text, cls) {
  els.refreshStatus.textContent = text;
  els.refreshStatus.className = `refresh-status ${cls}`;
}

function setLoading(v) {
  isLoading = v;
  els.refreshBtn.disabled = v;
  els.refreshBtn.textContent = v ? "加载中..." : "刷新";
}

function formatAlertType(type) {
  const map = {
    depth_shrink: "深度萎缩",
    spread_widen: "价差扩大",
  };
  return map[type] || type;
}

function buildThresholdText(alert) {
  if (alert.threshold_val == null && alert.current_val == null) return "";
  const parts = [];
  if (alert.current_val != null) parts.push(`当前值: ${Number(alert.current_val).toPrecision(4)}`);
  if (alert.threshold_val != null) parts.push(`阈值: ${Number(alert.threshold_val).toPrecision(4)}`);
  return parts.join(" · ");
}

function renderList() {
  const slice = filteredAlerts.slice(0, displayedCount);

  if (filteredAlerts.length === 0) {
    els.emptyState.classList.remove("hidden");
    els.resultCount.classList.add("hidden");
    els.alertList.innerHTML = "";
    els.loadMoreWrap.style.display = "none";
    return;
  }

  els.emptyState.classList.add("hidden");
  els.resultCount.classList.remove("hidden");
  els.resultCount.textContent = `显示 ${slice.length} / ${filteredAlerts.length} 条`;

  els.alertList.innerHTML = slice.map((alert) => {
    const thresholdText = buildThresholdText(alert);
    return `
    <li class="alert-item-full">
      <div class="alert-left">
        <span class="severity-tag sev-${escapeHtml(alert.severity || "info")}">${escapeHtml((alert.severity || "info").toUpperCase())}</span>
      </div>
      <div class="alert-center">
        <p class="alert-type-name">${escapeHtml(formatAlertType(alert.alert_type || "-"))}</p>
        <p class="alert-message">${escapeHtml(alert.message || "-")}</p>
        <div class="alert-meta-row">
          <span class="alert-venue-badge">${escapeHtml((alert.venue || "-").toUpperCase())}</span>
          ${thresholdText ? `<span class="tiny">${escapeHtml(thresholdText)}</span>` : ""}
        </div>
      </div>
      <div class="alert-right">
        <p class="alert-time">${escapeHtml(formatTime(alert.ts_utc))}</p>
      </div>
    </li>`;
  }).join("");

  els.loadMoreWrap.style.display = displayedCount < filteredAlerts.length ? "block" : "none";
  els.loadMoreBtn.disabled = false;
}

function applyFilters() {
  filteredAlerts = allAlerts.filter((a) => {
    if (activeSeverity !== "all" && a.severity !== activeSeverity) return false;
    if (activeVenue !== "all" && a.venue !== activeVenue) return false;
    return true;
  });
  displayedCount = PAGE_SIZE;
  renderList();
}

function updateStats() {
  const critical = allAlerts.filter((a) => a.severity === "critical").length;
  const warn = allAlerts.filter((a) => a.severity === "warn").length;
  const venues = new Set(allAlerts.map((a) => a.venue)).size;
  els.statTotal.textContent = String(allAlerts.length);
  els.statCritical.textContent = String(critical);
  els.statWarn.textContent = String(warn);
  els.statVenues.textContent = String(venues);
  els.statsRow.style.display = "flex";
}

function populateVenueSelect() {
  const venues = [...new Set(allAlerts.map((a) => a.venue).filter(Boolean))].sort();
  const current = els.venueSelect.value;
  els.venueSelect.innerHTML = `<option value="all">全部</option>` +
    venues.map((v) => `<option value="${escapeHtml(v)}">${escapeHtml(v.toUpperCase())}</option>`).join("");
  if (venues.includes(current)) els.venueSelect.value = current;
}

async function loadAlerts() {
  if (isLoading) return;
  setLoading(true);
  setStatus("加载中...", "status-loading");
  els.errorState.classList.add("hidden");

  try {
    const url = `${import.meta.env.VITE_SUPABASE_URL}/functions/v1/api-alerts?limit=200`;
    const res = await fetch(url, {
      headers: {
        Authorization: `Bearer ${import.meta.env.VITE_SUPABASE_ANON_KEY}`,
        "Content-Type": "application/json",
      },
      cache: "no-store",
    });
    if (!res.ok) throw new Error(`请求失败 ${res.status}`);
    const data = await res.json();
    allAlerts = data.items || [];

    updateStats();
    populateVenueSelect();
    els.filterBar.style.display = "flex";
    applyFilters();

    const at = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    setStatus(`已更新 ${at}`, "status-success");
  } catch (err) {
    els.errorState.textContent = `加载失败: ${err.message}`;
    els.errorState.classList.remove("hidden");
    setStatus("加载失败", "status-error");
  } finally {
    setLoading(false);
  }
}

function initEvents() {
  els.refreshBtn.addEventListener("click", loadAlerts);

  els.severityPills.addEventListener("click", (e) => {
    const pill = e.target.closest(".filter-pill");
    if (!pill) return;
    activeSeverity = pill.dataset.sev;
    els.severityPills.querySelectorAll(".filter-pill").forEach((p) => p.classList.remove("active"));
    pill.classList.add("active");
    applyFilters();
  });

  els.venueSelect.addEventListener("change", () => {
    activeVenue = els.venueSelect.value;
    applyFilters();
  });

  els.loadMoreBtn.addEventListener("click", () => {
    displayedCount += PAGE_SIZE;
    renderList();
  });
}

async function loadFundingIntervals() {
  try {
    const url = `${import.meta.env.VITE_SUPABASE_URL}/functions/v1/api-funding-interval`;
    const res = await fetch(url, {
      headers: {
        Authorization: `Bearer ${import.meta.env.VITE_SUPABASE_ANON_KEY}`,
        "Content-Type": "application/json",
      },
      cache: "no-store",
    });
    if (!res.ok) throw new Error(`请求失败 ${res.status}`);
    const data = await res.json();
    const items = data.items || [];

    if (items.length === 0) {
      els.fiGrid.innerHTML = `<span class="fi-empty">当前无合约使用 1 小时结算周期</span>`;
      return;
    }

    els.fiBadge.textContent = `${items.length} 个合约 · 1h 周期`;
    els.fiBadge.style.display = "";
    const at = data.fetched_at ? new Date(data.fetched_at).toLocaleTimeString("zh-CN", { hour12: false }) : "";
    if (at) els.fiMeta.textContent = `更新于 ${at}，共 ${data.total} 个合约`;

    els.fiGrid.innerHTML = items
      .sort((a, b) => String(a.symbol).localeCompare(String(b.symbol)))
      .map((item) => `<span class="fi-chip">${escapeHtml(String(item.symbol))}</span>`)
      .join("");
  } catch (err) {
    els.fiGrid.innerHTML = `<span class="fi-empty">加载失败: ${escapeHtml(err.message)}</span>`;
  }
}

initEvents();
loadAlerts();
loadFundingIntervals();
