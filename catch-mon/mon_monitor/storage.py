"""
SQLite 存储模块。
管理 metrics_snapshot、baselines、alerts、alert_counters 四张表。
支持 CSV 和 JSONL 导出。
"""

import csv
import io
import json
import logging
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mon_monitor.models import Alert, BaselineValues, VenueSnapshot

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS metrics_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    venue TEXT NOT NULL,
    symbol TEXT NOT NULL,
    missing_market INTEGER NOT NULL DEFAULT 0,
    last_price REAL,
    quote_volume_24h REAL,
    pct_change_1h REAL,
    pct_change_24h REAL,
    best_bid REAL,
    best_ask REAL,
    mid REAL,
    spread_bps REAL,
    depth_1pct_usdt_bid REAL,
    depth_1pct_usdt_ask REAL,
    depth_2pct_usdt_bid REAL,
    depth_2pct_usdt_ask REAL,
    slip_bps_buy_n1 REAL,
    slip_bps_sell_n1 REAL,
    slip_bps_buy_n2 REAL,
    slip_bps_sell_n2 REAL,
    avg_fill_buy_n1 REAL,
    avg_fill_sell_n1 REAL,
    avg_fill_buy_n2 REAL,
    avg_fill_sell_n2 REAL,
    insufficient_liq_n1 INTEGER DEFAULT 0,
    insufficient_liq_n2 INTEGER DEFAULT 0,
    funding_rate REAL,
    funding_time TEXT,
    oi_value_usdt REAL,
    oi_amount_contracts REAL,
    realized_vol_24h REAL,
    atr_like_24h REAL,
    raw_json TEXT,
    errors TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_snapshot_venue_ts
    ON metrics_snapshot(venue, ts_utc);

CREATE TABLE IF NOT EXISTS baselines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    venue TEXT NOT NULL,
    symbol TEXT NOT NULL,
    depth_1pct_total_median REAL,
    spread_bps_median REAL,
    slip_bps_n2_median REAL,
    volume_24h_mean_7d REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_baselines_venue_ts
    ON baselines(venue, ts_utc);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    venue TEXT NOT NULL,
    symbol TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    message TEXT,
    threshold_value REAL,
    current_value REAL,
    baseline_value REAL,
    dedupe_key TEXT NOT NULL,
    payload_json TEXT,
    snapshot_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_alerts_dedupe
    ON alerts(dedupe_key, ts_utc);

CREATE TABLE IF NOT EXISTS alert_counters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    counter_key TEXT NOT NULL UNIQUE,
    consecutive_count INTEGER NOT NULL DEFAULT 0,
    last_ts_utc TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS runtime_state (
    state_key TEXT PRIMARY KEY,
    state_value TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class Storage:
    """SQLite 存储管理。"""

    def __init__(self, db_path: str = "data/mon_monitor.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        """初始化数据库表结构。"""
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    def close(self):
        """关闭数据库连接。"""
        if self.conn:
            self.conn.close()

    def save_snapshot(self, snapshot: VenueSnapshot) -> int:
        """
        保存采样快照到数据库。
        返回插入记录的 id。
        """
        ob = snapshot.orderbook
        tk = snapshot.ticker
        fd = snapshot.funding
        oi = snapshot.open_interest
        ov = snapshot.ohlcv

        # 冲击成本字段
        slip_buy_n1 = None
        slip_sell_n1 = None
        slip_buy_n2 = None
        slip_sell_n2 = None
        avg_fill_buy_n1 = None
        avg_fill_sell_n1 = None
        avg_fill_buy_n2 = None
        avg_fill_sell_n2 = None
        insuf_n1 = 0
        insuf_n2 = 0

        if ob:
            if ob.impact_buy_n1:
                slip_buy_n1 = ob.impact_buy_n1.slip_bps
                avg_fill_buy_n1 = ob.impact_buy_n1.avg_fill_price
            if ob.impact_sell_n1:
                slip_sell_n1 = ob.impact_sell_n1.slip_bps
                avg_fill_sell_n1 = ob.impact_sell_n1.avg_fill_price
            if ob.impact_buy_n2:
                slip_buy_n2 = ob.impact_buy_n2.slip_bps
                avg_fill_buy_n2 = ob.impact_buy_n2.avg_fill_price
            if ob.impact_sell_n2:
                slip_sell_n2 = ob.impact_sell_n2.slip_bps
                avg_fill_sell_n2 = ob.impact_sell_n2.avg_fill_price
            if ob.impact_buy_n1 and ob.impact_buy_n1.insufficient_liquidity:
                insuf_n1 = 1
            if ob.impact_sell_n1 and ob.impact_sell_n1.insufficient_liquidity:
                insuf_n1 = 1
            if ob.impact_buy_n2 and ob.impact_buy_n2.insufficient_liquidity:
                insuf_n2 = 1
            if ob.impact_sell_n2 and ob.impact_sell_n2.insufficient_liquidity:
                insuf_n2 = 1

        # 序列化 raw_json（移除大体积的 orderbook_raw 和 ohlcv_candles）
        raw_for_storage = {}
        for k, v in snapshot.raw_json.items():
            if k not in ("orderbook_raw", "ohlcv_candles"):
                raw_for_storage[k] = v
        # 保留 orderbook levels raw 用于审计
        if ob and ob.orderbook_levels_raw:
            raw_for_storage["orderbook_levels_raw"] = ob.orderbook_levels_raw

        cursor = self.conn.execute(
            """
            INSERT INTO metrics_snapshot (
                ts_utc, venue, symbol, missing_market,
                last_price, quote_volume_24h, pct_change_1h, pct_change_24h,
                best_bid, best_ask, mid, spread_bps,
                depth_1pct_usdt_bid, depth_1pct_usdt_ask,
                depth_2pct_usdt_bid, depth_2pct_usdt_ask,
                slip_bps_buy_n1, slip_bps_sell_n1,
                slip_bps_buy_n2, slip_bps_sell_n2,
                avg_fill_buy_n1, avg_fill_sell_n1,
                avg_fill_buy_n2, avg_fill_sell_n2,
                insufficient_liq_n1, insufficient_liq_n2,
                funding_rate, funding_time,
                oi_value_usdt, oi_amount_contracts,
                realized_vol_24h, atr_like_24h,
                raw_json, errors
            ) VALUES (
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?
            )
            """,
            (
                snapshot.ts_utc,
                snapshot.venue,
                snapshot.symbol,
                1 if snapshot.missing_market else 0,
                tk.last_price if tk else None,
                tk.quote_volume_24h if tk else None,
                tk.pct_change_1h if tk else None,
                tk.pct_change_24h if tk else None,
                ob.best_bid if ob else None,
                ob.best_ask if ob else None,
                ob.mid if ob else None,
                ob.spread_bps if ob else None,
                ob.depth_1pct_usdt_bid if ob else None,
                ob.depth_1pct_usdt_ask if ob else None,
                ob.depth_2pct_usdt_bid if ob else None,
                ob.depth_2pct_usdt_ask if ob else None,
                slip_buy_n1,
                slip_sell_n1,
                slip_buy_n2,
                slip_sell_n2,
                avg_fill_buy_n1,
                avg_fill_sell_n1,
                avg_fill_buy_n2,
                avg_fill_sell_n2,
                insuf_n1,
                insuf_n2,
                fd.funding_rate if fd else None,
                fd.funding_time if fd else None,
                oi.open_interest_value_usdt if oi else None,
                oi.open_interest_amount_contracts if oi else None,
                ov.realized_vol_24h if ov else None,
                ov.atr_like_24h if ov else None,
                json.dumps(raw_for_storage, default=str),
                json.dumps(snapshot.errors) if snapshot.errors else None,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_baseline_data(
        self,
        venue: str,
        days: int = 14,
    ) -> list[dict]:
        """
        获取最近 N 天的 metrics_snapshot 数据，用于计算基线。
        """
        cursor = self.conn.execute(
            """
            SELECT * FROM metrics_snapshot
            WHERE venue = ?
              AND missing_market = 0
              AND ts_utc >= datetime('now', ?)
            ORDER BY ts_utc ASC
            """,
            (venue, f"-{days} days"),
        )
        return [dict(row) for row in cursor.fetchall()]

    def save_baseline(self, baseline: BaselineValues) -> int:
        """保存基线数据。"""
        cursor = self.conn.execute(
            """
            INSERT INTO baselines (
                ts_utc, venue, symbol,
                depth_1pct_total_median, spread_bps_median,
                slip_bps_n2_median, volume_24h_mean_7d
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                baseline.ts_utc,
                baseline.venue,
                baseline.symbol,
                baseline.depth_1pct_total_median,
                baseline.spread_bps_median,
                baseline.slip_bps_n2_median,
                baseline.volume_24h_mean_7d,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid

    def save_alert(self, alert: Alert, snapshot_id: Optional[int] = None) -> int:
        """保存告警记录。"""
        payload = asdict(alert)
        cursor = self.conn.execute(
            """
            INSERT INTO alerts (
                ts_utc, alert_type, venue, symbol, severity,
                message, threshold_value, current_value, baseline_value,
                dedupe_key, payload_json, snapshot_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert.ts_utc,
                alert.alert_type,
                alert.venue,
                alert.symbol,
                alert.severity,
                alert.message,
                alert.threshold_value,
                alert.current_value,
                alert.baseline_value,
                alert.dedupe_key,
                json.dumps(payload, default=str),
                snapshot_id,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid

    def check_dedupe(self, dedupe_key: str, window_seconds: int) -> bool:
        """
        检查同一 dedupe_key 在窗口时间内是否已有告警。
        返回 True 表示应该去重（跳过）。
        使用 created_at（插入时自动生成）而非 ts_utc（采样时间戳）来判断时效。
        """
        cursor = self.conn.execute(
            """
            SELECT COUNT(*) as cnt FROM alerts
            WHERE dedupe_key = ?
              AND created_at >= datetime('now', ?)
            """,
            (dedupe_key, f"-{window_seconds} seconds"),
        )
        row = cursor.fetchone()
        return row["cnt"] > 0

    def get_consecutive_count(self, counter_key: str) -> int:
        """获取连续触发计数。"""
        cursor = self.conn.execute(
            "SELECT consecutive_count FROM alert_counters WHERE counter_key = ?",
            (counter_key,),
        )
        row = cursor.fetchone()
        return row["consecutive_count"] if row else 0

    def update_consecutive_count(
        self,
        counter_key: str,
        count: int,
        ts_utc: str,
    ):
        """更新或插入连续触发计数。"""
        self.conn.execute(
            """
            INSERT INTO alert_counters (counter_key, consecutive_count, last_ts_utc, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(counter_key) DO UPDATE SET
                consecutive_count = excluded.consecutive_count,
                last_ts_utc = excluded.last_ts_utc,
                updated_at = datetime('now')
            """,
            (counter_key, count, ts_utc),
        )
        self.conn.commit()

    def reset_consecutive_count(self, counter_key: str):
        """重置连续触发计数。"""
        self.update_consecutive_count(
            counter_key,
            0,
            datetime.now(timezone.utc).isoformat(),
        )

    def get_recent_volume_data(
        self,
        venue: str,
        days: int = 7,
    ) -> list[float]:
        """获取最近 N 天的 24h 成交量数据。"""
        cursor = self.conn.execute(
            """
            SELECT quote_volume_24h FROM metrics_snapshot
            WHERE venue = ?
              AND missing_market = 0
              AND quote_volume_24h IS NOT NULL
              AND ts_utc >= datetime('now', ?)
            ORDER BY ts_utc ASC
            """,
            (venue, f"-{days} days"),
        )
        return [row["quote_volume_24h"] for row in cursor.fetchall()]

    def export_csv(self, table: str, output_path: str):
        """导出指定表为 CSV 文件。"""
        cursor = self.conn.execute(f"SELECT * FROM {table}")
        rows = cursor.fetchall()
        if not rows:
            logger.info("表 %s 无数据，跳过导出", table)
            return

        columns = [desc[0] for desc in cursor.description]
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            for row in rows:
                writer.writerow(list(row))
        logger.info("已导出 %s 到 %s（%d 行）", table, output_path, len(rows))

    def export_jsonl(self, table: str, output_path: str):
        """导出指定表为 JSONL 文件。"""
        cursor = self.conn.execute(f"SELECT * FROM {table}")
        rows = cursor.fetchall()
        if not rows:
            logger.info("表 %s 无数据，跳过导出", table)
            return

        columns = [desc[0] for desc in cursor.description]
        with open(output_path, "w", encoding="utf-8") as f:
            for row in rows:
                record = dict(zip(columns, list(row)))
                f.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
        logger.info("已导出 %s 到 %s（%d 行）", table, output_path, len(rows))

    def set_runtime_state(self, state_key: str, state_value: Optional[str]) -> None:
        """写入运行时状态（upsert）。"""
        self.conn.execute(
            """
            INSERT INTO runtime_state (state_key, state_value, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(state_key) DO UPDATE SET
                state_value = excluded.state_value,
                updated_at = datetime('now')
            """,
            (state_key, state_value),
        )
        self.conn.commit()

    def set_runtime_states(self, states: dict[str, Optional[str]]) -> None:
        """批量写入运行时状态。"""
        for key, value in states.items():
            self.conn.execute(
                """
                INSERT INTO runtime_state (state_key, state_value, updated_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(state_key) DO UPDATE SET
                    state_value = excluded.state_value,
                    updated_at = datetime('now')
                """,
                (key, value),
            )
        self.conn.commit()

    def get_runtime_states(self) -> dict[str, str]:
        """读取全部运行时状态。"""
        cursor = self.conn.execute("SELECT state_key, state_value FROM runtime_state")
        return {row["state_key"]: row["state_value"] for row in cursor.fetchall()}
