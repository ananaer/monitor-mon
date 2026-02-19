/*
  # Add token column to metrics_snapshot

  ## Summary
  Adds a `token` column to metrics_snapshot so each snapshot is associated
  with a specific token (e.g. "MON", "BTC"). This supports multi-token collection.

  ## Changes
  - metrics_snapshot: add `token` text column (default 'MON' for existing rows)
  - Add index on (token, venue, ts_utc) for efficient per-token queries
*/

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'metrics_snapshot' AND column_name = 'token'
  ) THEN
    ALTER TABLE metrics_snapshot ADD COLUMN token text NOT NULL DEFAULT 'MON';
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_metrics_snapshot_token_venue_ts
  ON metrics_snapshot (token, venue, ts_utc DESC);
