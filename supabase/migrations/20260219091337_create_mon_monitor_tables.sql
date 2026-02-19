/*
  # MON Monitor Tables

  ## Summary
  Python バックエンド (SQLite) を廃止し、Supabase に移行するためのテーブル群。

  ## New Tables

  1. **metrics_snapshot**
     - 各取引所の最新スナップショット (価格、出来高、スプレッド、深度、スリッページ、ファンディング、OI、ボラティリティ)
     - venue, ts_utc でユニーク

  2. **baselines**
     - 各取引所のベースライン統計 (直近 14 日の中央値)
     - venue でユニーク、upsert 運用

  3. **alerts**
     - アラートレコード (種別、重大度、しきい値、現在値)
     - 重複排除ウィンドウ対応

  4. **runtime_state**
     - コレクターの稼働状態・タイムスタンプ・設定値を KV 形式で保存

  ## Security
  - RLS 有効 (全テーブル)
  - anon ロールに SELECT を許可 (読み取り専用ダッシュボード用)
  - service_role のみ INSERT/UPDATE/DELETE を許可
*/

CREATE TABLE IF NOT EXISTS metrics_snapshot (
  id            bigserial PRIMARY KEY,
  venue         text        NOT NULL,
  symbol        text        NOT NULL DEFAULT '',
  ts_utc        timestamptz NOT NULL DEFAULT now(),
  last_price    numeric,
  pct_change_1h numeric,
  quote_volume_24h numeric,
  spread_bps    numeric,
  depth_1pct_bid_usdt numeric,
  depth_1pct_ask_usdt numeric,
  depth_1pct_total_usdt numeric,
  slip_bps_n1   numeric,
  slip_bps_n2   numeric,
  funding_rate  numeric,
  open_interest_usd numeric,
  rvol_24h      numeric,
  error_type    text,
  error_msg     text,
  raw_json      jsonb
);

CREATE INDEX IF NOT EXISTS idx_metrics_snapshot_venue_ts ON metrics_snapshot (venue, ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_metrics_snapshot_ts ON metrics_snapshot (ts_utc DESC);

ALTER TABLE metrics_snapshot ENABLE ROW LEVEL SECURITY;

CREATE POLICY "anon can read metrics_snapshot"
  ON metrics_snapshot FOR SELECT
  TO anon
  USING (true);

CREATE POLICY "service role can insert metrics_snapshot"
  ON metrics_snapshot FOR INSERT
  TO service_role
  WITH CHECK (true);

CREATE POLICY "service role can update metrics_snapshot"
  ON metrics_snapshot FOR UPDATE
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "service role can delete metrics_snapshot"
  ON metrics_snapshot FOR DELETE
  TO service_role
  USING (true);

CREATE TABLE IF NOT EXISTS baselines (
  id            bigserial PRIMARY KEY,
  venue         text        NOT NULL UNIQUE,
  updated_at    timestamptz NOT NULL DEFAULT now(),
  sample_count  int         NOT NULL DEFAULT 0,
  median_spread_bps  numeric,
  median_depth_total numeric,
  median_slip_n1     numeric,
  median_slip_n2     numeric,
  mean_volume_24h    numeric
);

ALTER TABLE baselines ENABLE ROW LEVEL SECURITY;

CREATE POLICY "anon can read baselines"
  ON baselines FOR SELECT
  TO anon
  USING (true);

CREATE POLICY "service role can insert baselines"
  ON baselines FOR INSERT
  TO service_role
  WITH CHECK (true);

CREATE POLICY "service role can update baselines"
  ON baselines FOR UPDATE
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "service role can delete baselines"
  ON baselines FOR DELETE
  TO service_role
  USING (true);

CREATE TABLE IF NOT EXISTS alerts (
  id            bigserial PRIMARY KEY,
  ts_utc        timestamptz NOT NULL DEFAULT now(),
  venue         text        NOT NULL,
  alert_type    text        NOT NULL,
  severity      text        NOT NULL DEFAULT 'warn',
  message       text        NOT NULL DEFAULT '',
  threshold_val numeric,
  current_val   numeric,
  extra_json    jsonb
);

CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts (ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_venue ON alerts (venue, ts_utc DESC);

ALTER TABLE alerts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "anon can read alerts"
  ON alerts FOR SELECT
  TO anon
  USING (true);

CREATE POLICY "service role can insert alerts"
  ON alerts FOR INSERT
  TO service_role
  WITH CHECK (true);

CREATE POLICY "service role can update alerts"
  ON alerts FOR UPDATE
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "service role can delete alerts"
  ON alerts FOR DELETE
  TO service_role
  USING (true);

CREATE TABLE IF NOT EXISTS runtime_state (
  key           text PRIMARY KEY,
  value         text NOT NULL DEFAULT '',
  updated_at    timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE runtime_state ENABLE ROW LEVEL SECURITY;

CREATE POLICY "anon can read runtime_state"
  ON runtime_state FOR SELECT
  TO anon
  USING (true);

CREATE POLICY "service role can insert runtime_state"
  ON runtime_state FOR INSERT
  TO service_role
  WITH CHECK (true);

CREATE POLICY "service role can update runtime_state"
  ON runtime_state FOR UPDATE
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "service role can delete runtime_state"
  ON runtime_state FOR DELETE
  TO service_role
  USING (true);
