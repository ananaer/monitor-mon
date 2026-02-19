const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL;
const ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY;
const API_BASE = `${SUPABASE_URL}/functions/v1/api-admin`;

const headers = {
  Authorization: `Bearer ${ANON_KEY}`,
  "Content-Type": "application/json",
};

async function apiFetch(path, opts = {}) {
  const res = await fetch(`${API_BASE}${path}`, { ...opts, headers: { ...headers, ...opts.headers } });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

let tokens = [];
let deleteTargetId = null;

const els = {
  error: document.getElementById("admin-error"),
  collectorStatus: document.getElementById("admin-collector-status"),
  lastCycle: document.getElementById("admin-last-cycle"),
  snapshotCount: document.getElementById("admin-snapshot-count"),
  alertCount: document.getElementById("admin-alert-count"),
  tokenTbody: document.getElementById("token-tbody"),
  tokenEmpty: document.getElementById("token-empty"),
  tokenTable: document.getElementById("token-table"),
  addBtn: document.getElementById("add-token-btn"),
  modal: document.getElementById("token-modal"),
  modalTitle: document.getElementById("modal-title"),
  modalClose: document.getElementById("modal-close"),
  modalCancel: document.getElementById("modal-cancel"),
  modalSubmit: document.getElementById("modal-submit"),
  form: document.getElementById("token-form"),
  formId: document.getElementById("form-id"),
  formToken: document.getElementById("form-token"),
  formEnabled: document.getElementById("form-enabled"),
  formBinance: document.getElementById("form-binance"),
  formOkx: document.getElementById("form-okx"),
  formBybit: document.getElementById("form-bybit"),
  formNote: document.getElementById("form-note"),
  formError: document.getElementById("form-error"),
  confirmModal: document.getElementById("confirm-modal"),
  confirmText: document.getElementById("confirm-text"),
  confirmCancel: document.getElementById("confirm-cancel"),
  confirmOk: document.getElementById("confirm-ok"),
};

function showError(msg) {
  if (!msg) { els.error.classList.add("hidden"); return; }
  els.error.textContent = msg;
  els.error.classList.remove("hidden");
}

function formatRelativeTime(isoStr) {
  if (!isoStr) return "-";
  const diff = Math.floor((Date.now() - new Date(isoStr).getTime()) / 1000);
  if (diff < 5) return "刚刚";
  if (diff < 60) return `${diff}s 前`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m 前`;
  return `${Math.floor(diff / 3600)}h 前`;
}

async function loadStatus() {
  try {
    const data = await apiFetch("/collector/status");
    const state = data.state || {};
    const status = state.service_status || "unknown";
    const labels = { running: "运行中", degraded: "异常", stopped: "已停止", unknown: "未知" };
    const classes = { running: "collector-ok", degraded: "collector-degraded", stopped: "collector-stopped", unknown: "collector-stopped" };
    els.collectorStatus.textContent = labels[status] ?? "未知";
    els.collectorStatus.className = `status-box-value ${classes[status] ?? "collector-stopped"}`;
    els.lastCycle.textContent = state.last_cycle_end_utc ? `上次: ${formatRelativeTime(state.last_cycle_end_utc)}` : "-";
    els.snapshotCount.textContent = String(data.total_snapshots ?? 0);
    els.alertCount.textContent = String(data.alerts_24h ?? 0);
  } catch (e) {
    els.collectorStatus.textContent = "获取失败";
  }
}

async function loadTokens() {
  try {
    const data = await apiFetch("/tokens");
    tokens = data.tokens || [];
    renderTokens();
    showError("");
  } catch (e) {
    showError(`加载币种失败: ${e.message}`);
  }
}

function renderTokens() {
  if (tokens.length === 0) {
    els.tokenEmpty.classList.remove("hidden");
    els.tokenTable.classList.add("hidden");
    return;
  }
  els.tokenEmpty.classList.add("hidden");
  els.tokenTable.classList.remove("hidden");

  els.tokenTbody.innerHTML = tokens.map((t) => `
    <tr>
      <td><strong>${escHtml(t.token)}</strong></td>
      <td>
        <label class="toggle toggle-sm">
          <input type="checkbox" class="toggle-enabled" data-id="${t.id}" ${t.enabled ? "checked" : ""} />
          <span class="toggle-slider"></span>
        </label>
        <span class="tiny ${t.enabled ? "collector-ok" : "muted"}">${t.enabled ? "采集中" : "已暂停"}</span>
      </td>
      <td><code>${escHtml(t.binance_symbol || "-")}</code></td>
      <td><code>${escHtml(t.okx_inst_id || "-")}</code></td>
      <td><code>${escHtml(t.bybit_symbol || "-")}</code></td>
      <td class="muted">${escHtml(t.note || "-")}</td>
      <td>
        <div class="action-btns">
          <button class="action-btn edit-btn" data-id="${t.id}">编辑</button>
          <button class="action-btn delete-btn" data-id="${t.id}" data-token="${escHtml(t.token)}">删除</button>
        </div>
      </td>
    </tr>
  `).join("");

  els.tokenTbody.querySelectorAll(".edit-btn").forEach((btn) => {
    btn.addEventListener("click", () => openEditModal(Number(btn.dataset.id)));
  });
  els.tokenTbody.querySelectorAll(".delete-btn").forEach((btn) => {
    btn.addEventListener("click", () => openConfirmDelete(Number(btn.dataset.id), btn.dataset.token));
  });
  els.tokenTbody.querySelectorAll(".toggle-enabled").forEach((chk) => {
    chk.addEventListener("change", () => toggleEnabled(Number(chk.dataset.id), chk.checked));
  });
}

function escHtml(str) {
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function openAddModal() {
  els.modalTitle.textContent = "添加币种";
  els.formId.value = "";
  els.form.reset();
  els.formEnabled.checked = true;
  els.formError.classList.add("hidden");
  els.modal.classList.remove("hidden");
  els.formToken.focus();
}

function openEditModal(id) {
  const token = tokens.find((t) => t.id === id);
  if (!token) return;
  els.modalTitle.textContent = `编辑 ${token.token}`;
  els.formId.value = String(id);
  els.formToken.value = token.token;
  els.formEnabled.checked = token.enabled;
  els.formBinance.value = token.binance_symbol || "";
  els.formOkx.value = token.okx_inst_id || "";
  els.formBybit.value = token.bybit_symbol || "";
  els.formNote.value = token.note || "";
  els.formError.classList.add("hidden");
  els.modal.classList.remove("hidden");
}

function closeModal() {
  els.modal.classList.add("hidden");
}

function openConfirmDelete(id, tokenName) {
  deleteTargetId = id;
  els.confirmText.textContent = `确定要删除币种 ${tokenName} 吗？删除后将停止采集，历史数据保留。`;
  els.confirmModal.classList.remove("hidden");
}

let confirmJustClosed = false;

function closeConfirm() {
  deleteTargetId = null;
  els.confirmModal.classList.add("hidden");
  confirmJustClosed = true;
  setTimeout(() => { confirmJustClosed = false; }, 100);
}

async function toggleEnabled(id, enabled) {
  try {
    await apiFetch(`/tokens/${id}`, {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    });
    const t = tokens.find((t) => t.id === id);
    if (t) t.enabled = enabled;
    renderTokens();
  } catch (e) {
    showError(`更新失败: ${e.message}`);
    renderTokens();
  }
}

async function handleFormSubmit(e) {
  e.preventDefault();
  const id = els.formId.value;
  const payload = {
    token: els.formToken.value.trim(),
    enabled: els.formEnabled.checked,
    binance_symbol: els.formBinance.value.trim(),
    okx_inst_id: els.formOkx.value.trim(),
    bybit_symbol: els.formBybit.value.trim(),
    note: els.formNote.value.trim(),
  };

  els.modalSubmit.disabled = true;
  els.modalSubmit.textContent = "保存中...";
  els.formError.classList.add("hidden");

  try {
    if (id) {
      await apiFetch(`/tokens/${id}`, { method: "PUT", body: JSON.stringify(payload) });
    } else {
      await apiFetch("/tokens", { method: "POST", body: JSON.stringify(payload) });
    }
    closeModal();
    await loadTokens();
  } catch (e) {
    els.formError.textContent = `保存失败: ${e.message}`;
    els.formError.classList.remove("hidden");
  } finally {
    els.modalSubmit.disabled = false;
    els.modalSubmit.textContent = "保存";
  }
}

async function handleConfirmDelete() {
  if (deleteTargetId === null) return;
  const id = deleteTargetId;
  els.confirmOk.disabled = true;
  els.confirmOk.textContent = "删除中...";
  try {
    await apiFetch(`/tokens/${id}`, { method: "DELETE" });
    closeConfirm();
    await loadTokens();
  } catch (e) {
    showError(`删除失败: ${e.message}`);
    closeConfirm();
  } finally {
    els.confirmOk.disabled = false;
    els.confirmOk.textContent = "删除";
  }
}

els.addBtn.addEventListener("click", openAddModal);
els.modalClose.addEventListener("click", closeModal);
els.modalCancel.addEventListener("click", closeModal);
els.modal.addEventListener("click", (e) => { if (!confirmJustClosed && e.target === els.modal) closeModal(); });
els.form.addEventListener("submit", handleFormSubmit);
els.confirmCancel.addEventListener("click", (e) => { e.stopPropagation(); closeConfirm(); });
els.confirmOk.addEventListener("click", (e) => { e.stopPropagation(); handleConfirmDelete(); });
els.confirmModal.addEventListener("click", (e) => { e.stopPropagation(); if (e.target === els.confirmModal) closeConfirm(); });

loadStatus();
loadTokens();
setInterval(loadStatus, 30000);
