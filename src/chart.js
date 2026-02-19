const VENUE_COLORS = {
  binance: "#f0b90b",
  okx: "#1677ff",
  bybit: "#ff6b35",
};

const DEFAULT_COLOR = "#0e7490";

function getColor(venue) {
  return VENUE_COLORS[venue?.toLowerCase()] ?? DEFAULT_COLOR;
}

function drawSparkline(canvas, points, valueKey, opts = {}) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.offsetWidth || 300;
  const h = canvas.offsetHeight || 80;
  canvas.width = w * dpr;
  canvas.height = h * dpr;

  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);

  const values = points.map((p) => Number(p[valueKey])).filter((v) => Number.isFinite(v));
  if (values.length < 2) {
    ctx.fillStyle = "#94a3b8";
    ctx.font = "11px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("数据不足", w / 2, h / 2);
    return;
  }

  const padX = 4;
  const padTop = 8;
  const padBot = 18;
  const chartW = w - padX * 2;
  const chartH = h - padTop - padBot;

  let minV = Math.min(...values);
  let maxV = Math.max(...values);
  const range = maxV - minV || Math.abs(minV) * 0.01 || 1;
  minV -= range * 0.05;
  maxV += range * 0.05;
  const totalRange = maxV - minV;

  const xOf = (i) => padX + (i / (values.length - 1)) * chartW;
  const yOf = (v) => padTop + (1 - (v - minV) / totalRange) * chartH;

  const color = opts.color || DEFAULT_COLOR;

  const grad = ctx.createLinearGradient(0, padTop, 0, padTop + chartH);
  grad.addColorStop(0, color + "40");
  grad.addColorStop(1, color + "00");

  ctx.beginPath();
  ctx.moveTo(xOf(0), yOf(values[0]));
  for (let i = 1; i < values.length; i++) {
    ctx.lineTo(xOf(i), yOf(values[i]));
  }
  ctx.lineTo(xOf(values.length - 1), padTop + chartH);
  ctx.lineTo(xOf(0), padTop + chartH);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  ctx.beginPath();
  ctx.moveTo(xOf(0), yOf(values[0]));
  for (let i = 1; i < values.length; i++) {
    ctx.lineTo(xOf(i), yOf(values[i]));
  }
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.lineJoin = "round";
  ctx.stroke();

  const lastX = xOf(values.length - 1);
  const lastY = yOf(values[values.length - 1]);
  ctx.beginPath();
  ctx.arc(lastX, lastY, 3, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();

  const fmt = opts.format || ((v) => v.toFixed(2));
  ctx.fillStyle = "#64748b";
  ctx.font = "10px sans-serif";
  ctx.textAlign = "left";
  ctx.fillText(fmt(minV + range * 0.05), padX, h - 4);
  ctx.textAlign = "right";
  ctx.fillText(fmt(maxV - range * 0.05), w - padX, h - 4);
}

export function renderTrendCharts(history) {
  const byVenue = history?.by_venue || {};
  const venues = Object.keys(byVenue);

  const container = document.getElementById("trend-charts");
  if (!container) return;

  container.innerHTML = "";

  if (venues.length === 0) {
    container.innerHTML = '<p class="muted">暂无趋势数据</p>';
    return;
  }

  const metrics = [
    { key: "last_price", label: "价格", format: (v) => v.toFixed(6) },
    { key: "spread_bps", label: "价差 (bps)", format: (v) => v.toFixed(2) },
    { key: "depth_1pct_total_usdt", label: "1% 深度 (USDT)", format: (v) => "$" + (v >= 1000 ? (v / 1000).toFixed(1) + "k" : v.toFixed(0)) },
  ];

  metrics.forEach(({ key, label, format }) => {
    const row = document.createElement("div");
    row.className = "chart-row";

    const rowLabel = document.createElement("p");
    rowLabel.className = "chart-row-label";
    rowLabel.textContent = label;
    row.appendChild(rowLabel);

    const group = document.createElement("div");
    group.className = "chart-group";

    venues.forEach((venue) => {
      const points = byVenue[venue] || [];
      const color = getColor(venue);

      const card = document.createElement("div");
      card.className = "chart-card";

      const header = document.createElement("div");
      header.className = "chart-card-header";

      const dot = document.createElement("span");
      dot.className = "chart-dot";
      dot.style.background = color;

      const name = document.createElement("span");
      name.className = "chart-venue-name";
      name.textContent = venue.toUpperCase();

      const latest = points.length > 0 ? points[points.length - 1] : null;
      const val = latest ? Number(latest[key]) : null;

      const valEl = document.createElement("span");
      valEl.className = "chart-latest-val";
      valEl.textContent = Number.isFinite(val) ? format(val) : "-";

      header.appendChild(dot);
      header.appendChild(name);
      header.appendChild(valEl);

      const canvas = document.createElement("canvas");
      canvas.className = "sparkline-canvas";

      card.appendChild(header);
      card.appendChild(canvas);
      group.appendChild(card);

      requestAnimationFrame(() => {
        drawSparkline(canvas, points, key, { color, format });
      });
    });

    row.appendChild(group);
    container.appendChild(row);
  });
}
