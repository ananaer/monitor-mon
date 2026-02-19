import { defineConfig } from "vite";

const now = new Date().toISOString();

const mockOverview = {
  token_hint: "MON",
  db_path: "catch-mon/data/monitor.db",
  updated_at_utc: now,
  collector: {
    service_status: "running",
    last_success_age_seconds: 5,
    schedule_seconds: 30,
    cycle_seq: 42,
    last_cycle_duration_ms: 1240,
    last_error: null,
  },
  stats: {
    venue_count: 4,
    alerts_24h: 2,
    critical_alerts_24h: 0,
  },
  venues: [
    {
      venue: "binance",
      symbol: "MON/USDT",
      status: "ok",
      last_price: 0.04812,
      pct_change_1h: 1.23,
      quote_volume_24h: 3820000,
      spread_bps: 2.1,
      depth_1pct_total_usdt: 520000,
      slip_bps_n2: 3.4,
      last_success_ts_utc: now,
      snapshot_ts_utc: now,
      data_lag_seconds: 2,
      snapshot_age_seconds: 2,
      error_reason: null,
      ratios: { depth_vs_baseline: 1.12 },
    },
    {
      venue: "okx",
      symbol: "MON/USDT",
      status: "ok",
      last_price: 0.04809,
      pct_change_1h: 0.87,
      quote_volume_24h: 1540000,
      spread_bps: 3.8,
      depth_1pct_total_usdt: 210000,
      slip_bps_n2: 5.1,
      last_success_ts_utc: now,
      snapshot_ts_utc: now,
      data_lag_seconds: 3,
      snapshot_age_seconds: 3,
      error_reason: null,
      ratios: { depth_vs_baseline: 0.88 },
    },
    {
      venue: "bybit",
      symbol: "MON/USDT",
      status: "stale",
      last_price: 0.04805,
      pct_change_1h: -0.44,
      quote_volume_24h: 890000,
      spread_bps: 5.2,
      depth_1pct_total_usdt: 98000,
      slip_bps_n2: 7.8,
      last_success_ts_utc: null,
      snapshot_ts_utc: now,
      data_lag_seconds: 120,
      snapshot_age_seconds: 120,
      error_reason: "连接超时",
      ratios: { depth_vs_baseline: 0.62 },
    },
    {
      venue: "kucoin",
      symbol: "MON/USDT",
      status: "down",
      last_price: null,
      pct_change_1h: null,
      quote_volume_24h: null,
      spread_bps: null,
      depth_1pct_total_usdt: null,
      slip_bps_n2: null,
      last_success_ts_utc: null,
      snapshot_ts_utc: null,
      data_lag_seconds: null,
      snapshot_age_seconds: null,
      error_reason: "API 不可用",
      ratios: { depth_vs_baseline: null },
    },
  ],
};

const mockHistory = {
  by_venue: {
    binance: Array.from({ length: 10 }, (_, i) => ({
      ts_utc: new Date(Date.now() - (10 - i) * 30000).toISOString(),
      last_price: 0.0481 + Math.random() * 0.0005,
      spread_bps: 2.0 + Math.random(),
      depth_1pct_total_usdt: 500000 + Math.random() * 50000,
    })),
    okx: Array.from({ length: 10 }, (_, i) => ({
      ts_utc: new Date(Date.now() - (10 - i) * 30000).toISOString(),
      last_price: 0.0480 + Math.random() * 0.0005,
      spread_bps: 3.5 + Math.random(),
      depth_1pct_total_usdt: 200000 + Math.random() * 20000,
    })),
  },
};

const mockAlerts = {
  items: [
    {
      severity: "warn",
      alert_type: "spread_high",
      venue: "bybit",
      message: "价差超过阈值: 5.2 bps (限制: 4.0 bps)",
      ts_utc: new Date(Date.now() - 600000).toISOString(),
    },
    {
      severity: "info",
      alert_type: "venue_stale",
      venue: "bybit",
      message: "数据已陈旧 120 秒",
      ts_utc: new Date(Date.now() - 1200000).toISOString(),
    },
  ],
};

export default defineConfig({
  root: ".",
  plugins: [
    {
      name: "mock-api",
      configureServer(server) {
        server.middlewares.use("/api/overview", (req, res) => {
          res.setHeader("Content-Type", "application/json");
          res.end(JSON.stringify({ ...mockOverview, updated_at_utc: new Date().toISOString() }));
        });
        server.middlewares.use("/api/history", (req, res) => {
          res.setHeader("Content-Type", "application/json");
          res.end(JSON.stringify(mockHistory));
        });
        server.middlewares.use("/api/alerts", (req, res) => {
          res.setHeader("Content-Type", "application/json");
          res.end(JSON.stringify(mockAlerts));
        });
        server.middlewares.use("/api/runtime", (req, res) => {
          res.setHeader("Content-Type", "application/json");
          res.end(JSON.stringify({ status: "ok" }));
        });
      },
    },
  ],
});
