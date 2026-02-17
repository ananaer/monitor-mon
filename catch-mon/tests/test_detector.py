"""
detector 模块单元测试。
覆盖：连续 3 次触发逻辑、告警去重逻辑、各告警类型检测。
"""

import os
import tempfile

import pytest

from mon_monitor.config import MonitorConfig, ThresholdsConfig, VenueConfig
from mon_monitor.detector import (
    CONSECUTIVE_THRESHOLD,
    check_depth_shrink,
    check_impact_cost_up,
    check_insufficient_liquidity,
    check_spread_widen,
    check_volume_spike,
    run_all_checks,
)
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


@pytest.fixture
def config():
    """测试配置。"""
    return MonitorConfig(
        token_symbol="MON",
        venues={
            "binance": VenueConfig(market="usdm_perp", symbol="MON/USDT:USDT"),
        },
        thresholds=ThresholdsConfig(
            depth_drop_mult=0.7,
            spread_mult=2.0,
            slip_mult=2.0,
            volume_spike_mult=2.0,
        ),
        dedupe_window_seconds=3600,
    )


def _make_snapshot(
    venue="binance",
    depth_bid=50000.0,
    depth_ask=50000.0,
    spread_bps=5.0,
    slip_buy_n2=10.0,
    slip_sell_n2=12.0,
    volume_24h=1000000.0,
    pct_change_24h=5.0,
    insuf_liq=False,
    shortfall=0.0,
    target_notional=100000.0,
) -> VenueSnapshot:
    """构造测试用 snapshot。"""
    impact_n2_buy = ImpactCostResult(
        avg_fill_price=100.0,
        slip_bps=slip_buy_n2,
        filled_notional=target_notional - shortfall if insuf_liq else target_notional,
        target_notional=target_notional,
        insufficient_liquidity=insuf_liq,
        shortfall=shortfall,
    )
    impact_n2_sell = ImpactCostResult(
        avg_fill_price=99.0,
        slip_bps=slip_sell_n2,
        filled_notional=target_notional,
        target_notional=target_notional,
    )

    return VenueSnapshot(
        venue=venue,
        symbol="MON/USDT:USDT",
        ts_utc="2025-01-01T00:00:00+00:00",
        ticker=TickerData(
            last_price=100.0,
            quote_volume_24h=volume_24h,
            pct_change_24h=pct_change_24h,
        ),
        orderbook=OrderBookData(
            best_bid=99.9,
            best_ask=100.1,
            mid=100.0,
            spread_bps=spread_bps,
            depth_1pct_usdt_bid=depth_bid,
            depth_1pct_usdt_ask=depth_ask,
            impact_buy_n2=impact_n2_buy,
            impact_sell_n2=impact_n2_sell,
        ),
        funding=FundingData(funding_rate=0.0001),
        open_interest=OpenInterestData(open_interest_value_usdt=5000000),
    )


def _make_baseline(
    depth_total=100000.0,
    spread_bps=5.0,
    slip_n2=10.0,
    volume_mean=500000.0,
) -> BaselineValues:
    """构造测试用 baseline。"""
    return BaselineValues(
        venue="binance",
        symbol="MON/USDT:USDT",
        ts_utc="2025-01-01T00:00:00+00:00",
        depth_1pct_total_median=depth_total,
        spread_bps_median=spread_bps,
        slip_bps_n2_median=slip_n2,
        volume_24h_mean_7d=volume_mean,
    )


class TestConsecutiveTrigger:
    """测试连续 3 次触发逻辑。"""

    def test_depth_shrink_needs_3_consecutive(self, storage, config):
        """深度收缩需要连续 3 次才触发。"""
        baseline = _make_baseline(depth_total=100000.0)
        # 当前深度远低于阈值：30000 < 100000 * 0.7 = 70000
        snap = _make_snapshot(depth_bid=15000.0, depth_ask=15000.0)

        # 第 1 次：不应触发
        alert = check_depth_shrink(snap, baseline, config, storage)
        assert alert is None

        # 第 2 次：不应触发
        alert = check_depth_shrink(snap, baseline, config, storage)
        assert alert is None

        # 第 3 次：应触发
        alert = check_depth_shrink(snap, baseline, config, storage)
        assert alert is not None
        assert alert.alert_type == "depth_shrink"
        assert alert.severity == "warn"

    def test_depth_reset_on_normal(self, storage, config):
        """条件不满足时重置计数器。"""
        baseline = _make_baseline(depth_total=100000.0)
        low_snap = _make_snapshot(depth_bid=15000.0, depth_ask=15000.0)
        normal_snap = _make_snapshot(depth_bid=50000.0, depth_ask=50000.0)

        # 2 次异常
        check_depth_shrink(low_snap, baseline, config, storage)
        check_depth_shrink(low_snap, baseline, config, storage)

        # 1 次正常，重置
        check_depth_shrink(normal_snap, baseline, config, storage)

        # 再 2 次异常，不应触发（因为重置了）
        alert = check_depth_shrink(low_snap, baseline, config, storage)
        assert alert is None
        alert = check_depth_shrink(low_snap, baseline, config, storage)
        assert alert is None

        # 第 3 次应触发
        alert = check_depth_shrink(low_snap, baseline, config, storage)
        assert alert is not None

    def test_spread_widen_3_consecutive(self, storage, config):
        """价差扩张需要连续 3 次。"""
        baseline = _make_baseline(spread_bps=5.0)
        # 当前 spread=15.0 > 5.0 * 2.0 = 10.0
        snap = _make_snapshot(spread_bps=15.0)

        alert = check_spread_widen(snap, baseline, config, storage)
        assert alert is None
        alert = check_spread_widen(snap, baseline, config, storage)
        assert alert is None
        alert = check_spread_widen(snap, baseline, config, storage)
        assert alert is not None
        assert alert.alert_type == "spread_widen"

    def test_impact_cost_3_consecutive(self, storage, config):
        """冲击成本上升需要连续 3 次。"""
        baseline = _make_baseline(slip_n2=10.0)
        # max(30, 12) = 30 > 10 * 2 = 20
        snap = _make_snapshot(slip_buy_n2=30.0, slip_sell_n2=12.0)

        alert = check_impact_cost_up(snap, baseline, config, storage)
        assert alert is None
        alert = check_impact_cost_up(snap, baseline, config, storage)
        assert alert is None
        alert = check_impact_cost_up(snap, baseline, config, storage)
        assert alert is not None
        assert alert.alert_type == "impact_cost_up"


class TestInsufficientLiquidity:
    """流动性不足告警测试。"""

    def test_immediate_trigger(self, config):
        """流动性不足立即触发，无需连续确认。"""
        # 缺口 30000 / 100000 = 30% > 20%
        snap = _make_snapshot(
            insuf_liq=True,
            shortfall=30000.0,
            target_notional=100000.0,
        )
        alert = check_insufficient_liquidity(snap, config)
        assert alert is not None
        assert alert.alert_type == "insufficient_liquidity"
        assert alert.severity == "critical"

    def test_small_gap_no_trigger(self, config):
        """缺口小于 20% 不触发。"""
        # 缺口 10000 / 100000 = 10% < 20%
        snap = _make_snapshot(
            insuf_liq=True,
            shortfall=10000.0,
            target_notional=100000.0,
        )
        alert = check_insufficient_liquidity(snap, config)
        assert alert is None

    def test_no_insufficient(self, config):
        """无流动性不足时不触发。"""
        snap = _make_snapshot(insuf_liq=False)
        alert = check_insufficient_liquidity(snap, config)
        assert alert is None


class TestVolumeSpikeOptional:
    """量价异常告警测试。"""

    def test_volume_spike_up(self, config):
        """放量上行。"""
        baseline = _make_baseline(volume_mean=500000.0)
        # 1200000 > 500000 * 2.0 = 1000000
        snap = _make_snapshot(volume_24h=1200000.0, pct_change_24h=5.0)
        alert = check_volume_spike(snap, baseline, config)
        assert alert is not None
        assert "放量上行" in alert.message

    def test_volume_spike_down(self, config):
        """放量下行。"""
        baseline = _make_baseline(volume_mean=500000.0)
        snap = _make_snapshot(volume_24h=1200000.0, pct_change_24h=-5.0)
        alert = check_volume_spike(snap, baseline, config)
        assert alert is not None
        assert "放量下行" in alert.message

    def test_normal_volume(self, config):
        """正常成交量不触发。"""
        baseline = _make_baseline(volume_mean=500000.0)
        snap = _make_snapshot(volume_24h=800000.0)
        alert = check_volume_spike(snap, baseline, config)
        assert alert is None


class TestDeduplication:
    """告警去重测试。"""

    def test_dedupe_blocks_duplicate(self, storage, config):
        """同一 dedupe_key 在窗口内被去重。"""
        alert = Alert(
            alert_type="depth_shrink",
            venue="binance",
            symbol="MON/USDT:USDT",
            severity="warn",
            message="test",
            ts_utc="2025-01-01T00:00:00+00:00",
            dedupe_key="depth_shrink:binance:MON/USDT:USDT",
        )
        storage.save_alert(alert)

        # 应该被去重
        is_dup = storage.check_dedupe(
            "depth_shrink:binance:MON/USDT:USDT", 3600
        )
        assert is_dup

    def test_different_key_not_deduped(self, storage, config):
        """不同 key 不去重。"""
        alert = Alert(
            alert_type="depth_shrink",
            venue="binance",
            symbol="MON/USDT:USDT",
            severity="warn",
            message="test",
            ts_utc="2025-01-01T00:00:00+00:00",
            dedupe_key="depth_shrink:binance:MON/USDT:USDT",
        )
        storage.save_alert(alert)

        is_dup = storage.check_dedupe(
            "spread_widen:binance:MON/USDT:USDT", 3600
        )
        assert not is_dup


class TestRunAllChecks:
    """run_all_checks 集成测试。"""

    def test_missing_market_returns_empty(self, storage, config):
        """missing_market 的 snapshot 不产生告警。"""
        snap = VenueSnapshot(
            venue="binance",
            symbol="MON/USDT:USDT",
            missing_market=True,
        )
        baseline = _make_baseline()
        alerts = run_all_checks(snap, baseline, config, storage)
        assert alerts == []

    def test_no_baseline_no_alert(self, storage, config):
        """无基线数据时不产生连续确认类告警。"""
        snap = _make_snapshot()
        baseline = BaselineValues(venue="binance", symbol="MON/USDT:USDT")
        alerts = run_all_checks(snap, baseline, config, storage)
        # 没有基线，连续确认类不会触发，volume_spike 也不会
        assert len(alerts) == 0
