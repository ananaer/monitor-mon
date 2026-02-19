import json
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mon_monitor.storage import SCHEMA_SQL
from web.server import MonitorRepository


def _make_temp_db() -> Path:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_path = Path(path)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)

    # 旧的成功记录（不应被当前态回填）
    conn.execute(
        """
        INSERT INTO metrics_snapshot (
            ts_utc, venue, symbol, missing_market, last_price, spread_bps
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("2026-02-17T13:51:59+00:00", "okx", "MON-USDT-SWAP", 0, 0.0221, 4.5),
    )

    # 最新失败记录（应作为当前态）
    conn.execute(
        """
        INSERT INTO metrics_snapshot (
            ts_utc, venue, symbol, missing_market, errors
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            "2026-02-17T14:10:00+00:00",
            "okx",
            "MON-USDT-SWAP",
            1,
            json.dumps(["OKX symbol 验证失败: network_error:ConnectionError"]),
        ),
    )

    conn.commit()
    conn.close()
    return db_path


def test_overview_no_fallback_on_missing_market():
    db_path = _make_temp_db()
    try:
        repo = MonitorRepository(db_path=db_path)
        overview = repo.get_overview()
        okx = next(v for v in overview["venues"] if v["venue"] == "okx")

        assert okx["status"] == "down"
        assert okx["last_price"] is None
        assert okx["last_success_ts_utc"] == "2026-02-17T13:51:59+00:00"
    finally:
        os.unlink(db_path)


def test_overview_exposes_error_reason():
    db_path = _make_temp_db()
    try:
        repo = MonitorRepository(db_path=db_path)
        overview = repo.get_overview()
        okx = next(v for v in overview["venues"] if v["venue"] == "okx")
        assert okx["error_reason"] == "OKX symbol 验证失败: network_error:ConnectionError"
    finally:
        os.unlink(db_path)


def test_overview_exposes_collector_runtime_status():
    db_path = _make_temp_db()
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO runtime_state (state_key, state_value) VALUES (?, ?)",
            ("collector.daemon_status", "running"),
        )
        conn.execute(
            "INSERT INTO runtime_state (state_key, state_value) VALUES (?, ?)",
            ("collector.last_cycle_status", "ok"),
        )
        conn.execute(
            "INSERT INTO runtime_state (state_key, state_value) VALUES (?, ?)",
            ("collector.schedule_seconds", "60"),
        )
        conn.execute(
            "INSERT INTO runtime_state (state_key, state_value) VALUES (?, ?)",
            ("collector.last_success_utc", "2026-02-17T14:10:00+00:00"),
        )
        conn.commit()
        conn.close()

        repo = MonitorRepository(db_path=db_path)
        overview = repo.get_overview()
        collector = overview["collector"]

        assert collector["daemon_status"] == "running"
        assert collector["cycle_status"] == "ok"
        assert collector["schedule_seconds"] == 60
        assert collector["last_success_utc"] == "2026-02-17T14:10:00+00:00"
    finally:
        os.unlink(db_path)


def test_overview_marks_stale_when_snapshot_too_old():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_path = Path(path)
    try:
        conn = sqlite3.connect(str(db_path))
        conn.executescript(SCHEMA_SQL)
        old_ts = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
        conn.execute(
            """
            INSERT INTO metrics_snapshot (
                ts_utc, venue, symbol, missing_market, last_price, spread_bps
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (old_ts, "binance", "MONUSDT", 0, 0.02, 4.5),
        )
        conn.execute(
            "INSERT INTO runtime_state (state_key, state_value) VALUES (?, ?)",
            ("collector.schedule_seconds", "60"),
        )
        conn.commit()
        conn.close()

        repo = MonitorRepository(db_path=db_path)
        overview = repo.get_overview()
        binance = next(v for v in overview["venues"] if v["venue"] == "binance")
        assert binance["status"] == "stale"
        assert binance["is_stale"] is True
        assert binance["snapshot_age_seconds"] >= 300
    finally:
        os.unlink(db_path)


def test_overview_extracts_error_code_when_machine_prefix_present():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_path = Path(path)
    try:
        conn = sqlite3.connect(str(db_path))
        conn.executescript(SCHEMA_SQL)
        conn.execute(
            """
            INSERT INTO metrics_snapshot (
                ts_utc, venue, symbol, missing_market, errors
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                "2026-02-19T00:00:00+00:00",
                "bybit",
                "MONUSDT",
                1,
                json.dumps(["network_error: bybit ticker request failed"]),
            ),
        )
        conn.commit()
        conn.close()

        repo = MonitorRepository(db_path=db_path)
        overview = repo.get_overview()
        bybit = next(v for v in overview["venues"] if v["venue"] == "bybit")
        assert bybit["error_code"] == "network_error"
        assert bybit["error_reason"] == "bybit ticker request failed"
    finally:
        os.unlink(db_path)
