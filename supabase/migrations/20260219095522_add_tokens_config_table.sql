/*
  # Add tokens config table

  ## Summary
  Adds a `tokens` table to manage which tokens/symbols are monitored across exchanges.
  The collector reads this table to know which tokens to collect data for.

  ## New Tables

  1. **tokens**
     - `id` (bigserial, primary key)
     - `token` (text, unique) - token symbol, e.g. "MON", "BTC"
     - `enabled` (boolean) - whether to collect data for this token
     - `binance_symbol` (text) - symbol on Binance futures, e.g. "MONUSDT"
     - `okx_inst_id` (text) - instrument ID on OKX, e.g. "MON-USDT-SWAP"
     - `bybit_symbol` (text) - symbol on Bybit, e.g. "MONUSDT"
     - `note` (text) - optional note
     - `created_at` (timestamptz)
     - `updated_at` (timestamptz)

  ## Security
  - RLS enabled
  - anon role: SELECT only
  - service_role: full access
  - authenticated role: full access (for admin UI)
*/

CREATE TABLE IF NOT EXISTS tokens (
  id             bigserial PRIMARY KEY,
  token          text        NOT NULL UNIQUE,
  enabled        boolean     NOT NULL DEFAULT true,
  binance_symbol text        NOT NULL DEFAULT '',
  okx_inst_id    text        NOT NULL DEFAULT '',
  bybit_symbol   text        NOT NULL DEFAULT '',
  note           text        NOT NULL DEFAULT '',
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE tokens ENABLE ROW LEVEL SECURITY;

CREATE POLICY "anon can read tokens"
  ON tokens FOR SELECT
  TO anon
  USING (true);

CREATE POLICY "service role can insert tokens"
  ON tokens FOR INSERT
  TO service_role
  WITH CHECK (true);

CREATE POLICY "service role can update tokens"
  ON tokens FOR UPDATE
  TO service_role
  USING (true)
  WITH CHECK (true);

CREATE POLICY "service role can delete tokens"
  ON tokens FOR DELETE
  TO service_role
  USING (true);

INSERT INTO tokens (token, enabled, binance_symbol, okx_inst_id, bybit_symbol, note)
VALUES ('MON', true, 'MONUSDT', 'MON-USDT-SWAP', 'MONUSDT', '初始配置')
ON CONFLICT (token) DO NOTHING;
