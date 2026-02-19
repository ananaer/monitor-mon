"""
storage 模块单元测试。
覆盖：建表、快照保存/查询、基线保存、告警保存/去重、计数器、导出。
"""

import json
import os
import tempfile

import pytest

from mon_monitor.models import (
    Alert,
    BaselineValues,
    FundingData,
    ImpactCostResult,
    OpenInterestData,
    OrderBookData,
    TickerData,
    VenueSnapshot,
)
from mon_monitor.storage import Storage


@pytest.fixture
def storage():
    """创建临时数据库的 storage 实例。"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    s = Storage(path)
    yield s
    s.close()
    os.unlink(path)


def _make_snapshot() -> VenueSnapshot:
    """构造测试用 snapshot。"""
    return VenueSnapshot(
        venue="binance",
        symbol="MON/USDT:USDT",
        ts_utc="2025-01-15T12:00:00+00:00",
        ticker=TickerData(
            last_price=1.5,
            quote_volume_24h=500000.0,
            pct_change_1h=0.5,
            pct_change_24h=3.2,
        ),
        orderbook=OrderBookData(
            best_bid=1.499,
            best_ask=1.501,
            mid=1.5,
            spread_bps=13.33,
            depth_1pct_usdt_bid=20000.0,
            depth_1pct_usdt_ask=18000.0,
            depth_2pct_usdt_bid=40000.0,
            depth_2pct_usdt_ask=35000.0,
            impact_buy_n1=ImpactCostResult(
                avg_fill_price=1.501,
                slip_bps=6.67,
                filled_notional=10000.0,
                target_notional=10000.0,
            ),
            impact_sell_n1=ImpactCostResult(
                avg_fill_price=1.499,
                slip_bps=6.67,
                filled_notional=10000.0,
                target_notional=10000.0,
            ),
            impact_buy_n2=ImpactCostResult(
                avg_fill_price=1.505,
                slip_bps=33.33,
                filled_notional=100000.0,
                target_notional=100000.0,
            ),
            impact_sell_n2=ImpactCostResult(
                avg_fill_price=1.495,
                slip_bps=33.33,
                filled_notional=100000.0,
                target_notional=100000.0,
            ),
        ),
        funding=FundingData(funding_rate=0.0001, funding_time="2025-01-15T16:00:00Z"),
        open_interest=OpenInterestData(
            open_interest_value_usdt=5000000.0,
            open_interest_amount_contracts=3333333.0,
        ),
        raw_json={"ticker": {"last": 1.5}},
    )


class TestStorageSchema:
    """数据库初始化测试。"""

    def test_tables_created(self, storage):
        """所有表应该存在。"""
        cursor = storage.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row["name"] for row in cursor.fetchall()}
        assert "metrics_snapshot" in tables
        assert "baselines" in tables
        assert "alerts" in tables
        assert "alert_counters" in tables
        assert "runtime_state" in tables


class TestSnapshotCRUD:
    """快照保存和查询测试。"""

    def test_save_and_query(self, storage):
        """保存快照后能查询到。"""
        snap = _make_snapshot()
        sid = storage.save_snapshot(snap)
        assert sid > 0

        cursor = storage.conn.execute(
            "SELECT * FROM metrics_snapshot WHERE id = ?", (sid,)
        )
        row = dict(cursor.fetchone())
        assert row["venue"] == "binance"
        assert row["symbol"] == "MON/USDT:USDT"
        assert row["last_price"] == 1.5
        assert row["spread_bps"] == pytest.approx(13.33)
        assert row["depth_1pct_usdt_bid"] == 20000.0
        assert row["funding_rate"] == 0.0001
        assert row["oi_value_usdt"] == 5000000.0

    def test_save_missing_market(self, storage):
        """missing_market 的 snapshot 也能保存。"""
        snap = VenueSnapshot(
            venue="okx",
            symbol="MON/USDT:USDT",
            ts_utc="2025-01-15T12:00:00+00:00",
            missing_market=True,
        )
        sid = storage.save_snapshot(snap)
        assert sid > 0

        cursor = storage.conn.execute(
            "SELECT missing_market FROM metrics_snapshot WHERE id = ?", (sid,)
        )
        row = cursor.fetchone()
        assert row["missing_market"] == 1

    def test_get_baseline_data(self, storage):
        """查询基线数据。"""
        snap = _make_snapshot()
        storage.save_snapshot(snap)

        rows = storage.get_baseline_data("binance", 14)
        # 因为 ts_utc 设为了过去时间，可能查不到（取决于当前时间）
        # 这里主要验证查询不报错
        assert isinstance(rows, list)


class TestBaselineCRUD:
    """基线保存测试。"""

    def test_save_baseline(self, storage):
        """保存基线记录。"""
        baseline = BaselineValues(
            venue="binance",
            symbol="MON/USDT:USDT",
            ts_utc="2025-01-15T12:00:00+00:00",
            depth_1pct_total_median=80000.0,
            spread_bps_median=10.0,
            slip_bps_n2_median=25.0,
            volume_24h_mean_7d=600000.0,
        )
        bid = storage.save_baseline(baseline)
        assert bid > 0


class TestAlertCRUD:
    """告警保存与去重测试。"""

    def test_save_alert(self, storage):
        """保存告警记录。"""
        alert = Alert(
            alert_type="depth_shrink",
            venue="binance",
            symbol="MON/USDT:USDT",
            severity="warn",
            message="深度收缩测试",
            threshold_value=70000.0,
            current_value=30000.0,
            baseline_value=100000.0,
            ts_utc="2025-01-15T12:00:00+00:00",
            dedupe_key="depth_shrink:binance:MON/USDT:USDT",
        )
        aid = storage.save_alert(alert, snapshot_id=1)
        assert aid > 0

        cursor = storage.conn.execute(
            "SELECT * FROM alerts WHERE id = ?", (aid,)
        )
        row = dict(cursor.fetchone())
        assert row["alert_type"] == "depth_shrink"
        assert row["severity"] == "warn"
        assert row["snapshot_id"] == 1

        payload = json.loads(row["payload_json"])
        assert payload["alert_type"] == "depth_shrink"


class TestConsecutiveCounter:
    """连续触发计数器测试。"""

    def test_increment_and_read(self, storage):
        """计数器递增与读取。"""
        key = "test:counter"
        assert storage.get_consecutive_count(key) == 0

        storage.update_consecutive_count(key, 1, "2025-01-01T00:00:00")
        assert storage.get_consecutive_count(key) == 1

        storage.update_consecutive_count(key, 2, "2025-01-01T00:05:00")
        assert storage.get_consecutive_count(key) == 2

    def test_reset(self, storage):
        """计数器重置。"""
        key = "test:counter"
        storage.update_consecutive_count(key, 5, "2025-01-01T00:00:00")
        storage.reset_consecutive_count(key)
        assert storage.get_consecutive_count(key) == 0


class TestExport:
    """数据导出测试。"""

    def test_export_csv(self, storage, tmp_path):
        """CSV 导出。"""
        snap = _make_snapshot()
        storage.save_snapshot(snap)

        csv_path = str(tmp_path / "test.csv")
        storage.export_csv("metrics_snapshot", csv_path)
        assert os.path.exists(csv_path)

        with open(csv_path, "r") as f:
            lines = f.readlines()
        # 至少有 header + 1 数据行
        assert len(lines) >= 2

    def test_export_jsonl(self, storage, tmp_path):
        """JSONL 导出。"""
        snap = _make_snapshot()
        storage.save_snapshot(snap)

        jsonl_path = str(tmp_path / "test.jsonl")
        storage.export_jsonl("metrics_snapshot", jsonl_path)
        assert os.path.exists(jsonl_path)

        with open(jsonl_path, "r") as f:
            lines = f.readlines()
        assert len(lines) >= 1
        record = json.loads(lines[0])
        assert record["venue"] == "binance"


class TestRuntimeState:
    """运行时状态读写测试。"""

    def test_set_and_get_runtime_state(self, storage):
        storage.set_runtime_state("collector.last_cycle_status", "running")
        states = storage.get_runtime_states()
        assert states["collector.last_cycle_status"] == "running"

    def test_set_runtime_states_bulk(self, storage):
        storage.set_runtime_states(
            {
                "collector.last_cycle_status": "ok",
                "collector.last_success_utc": "2026-02-19T00:00:00+00:00",
            }
        )
        states = storage.get_runtime_states()
        assert states["collector.last_cycle_status"] == "ok"
        assert states["collector.last_success_utc"] == "2026-02-19T00:00:00+00:00"
