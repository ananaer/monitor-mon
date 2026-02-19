"""
异常检测与告警模块。

基线计算：
- 使用最近 baseline_days 天的历史数据
- 计算各指标的滚动中位数（median）作为基线
- 样本数 < MIN_BASELINE_SAMPLES 时标记 warming_up，禁止 warn 类告警

告警规则：
1. 深度收缩 (depth_shrink): depth_1pct_total < median * depth_drop_mult, 连续 3 次
2. 价差扩张 (spread_widen): spread_bps > median * spread_mult, 连续 3 次
3. 冲击成本上升 (impact_cost_up): slip_bps_n2 > median * slip_mult, 连续 3 次
4. 流动性不足 (insufficient_liquidity): 立即触发（缺口超阈值）
5. 量价异常 (volume_spike): volume_24h > mean_7d * volume_spike_mult（可选）

连续确认：规则 1-3 需连续 3 次采样触发才发出告警
去重：同一 dedupe_key 在 dedupe_window_seconds 内只输出一次
"""

import logging
import statistics
from datetime import datetime, timezone
from typing import Optional

from mon_monitor.config import MonitorConfig
from mon_monitor.models import Alert, BaselineValues, VenueSnapshot
from mon_monitor.storage import Storage

logger = logging.getLogger(__name__)

CONSECUTIVE_THRESHOLD = 3
# 至少需要这么多样本才认为基线有效，否则 warming_up
MIN_BASELINE_SAMPLES = 20


def _median(values: list[float]) -> Optional[float]:
    """计算中位数，空列表返回 None。"""
    filtered = [v for v in values if v is not None]
    if not filtered:
        return None
    return statistics.median(filtered)


def _mean(values: list[float]) -> Optional[float]:
    """计算均值，空列表返回 None。"""
    filtered = [v for v in values if v is not None]
    if not filtered:
        return None
    return statistics.mean(filtered)


def compute_baselines(
    storage: Storage,
    venue: str,
    symbol: str,
    baseline_days: int,
) -> BaselineValues:
    """
    从历史数据计算基线值。
    样本不足时标记 warming_up=True。
    """
    rows = storage.get_baseline_data(venue, baseline_days)
    baseline = BaselineValues(
        venue=venue,
        symbol=symbol,
        ts_utc=datetime.now(timezone.utc).isoformat(),
        sample_count=len(rows),
    )

    if not rows:
        logger.info("%s: 无历史数据，基线 warming_up", venue)
        return baseline

    if len(rows) < MIN_BASELINE_SAMPLES:
        logger.info(
            "%s: 样本 %d < %d，基线 warming_up",
            venue, len(rows), MIN_BASELINE_SAMPLES,
        )
    else:
        baseline.warming_up = False

    # depth_1pct_total = bid + ask
    depth_totals = []
    for r in rows:
        bid = r.get("depth_1pct_usdt_bid")
        ask = r.get("depth_1pct_usdt_ask")
        if bid is not None and ask is not None:
            depth_totals.append(bid + ask)
    baseline.depth_1pct_total_median = _median(depth_totals)

    # spread_bps
    spreads = [r.get("spread_bps") for r in rows]
    baseline.spread_bps_median = _median(spreads)

    # slip_bps_n2 = max(buy, sell)
    slip_n2_values = []
    for r in rows:
        buy = r.get("slip_bps_buy_n2")
        sell = r.get("slip_bps_sell_n2")
        vals = [v for v in (buy, sell) if v is not None]
        if vals:
            slip_n2_values.append(max(vals))
    baseline.slip_bps_n2_median = _median(slip_n2_values)

    # volume_24h mean (7 天)
    volumes = storage.get_recent_volume_data(venue, 7)
    baseline.volume_24h_mean_7d = _mean(volumes)

    return baseline


def _check_with_consecutive(
    storage: Storage,
    counter_key: str,
    condition_met: bool,
    ts_utc: str,
) -> bool:
    """
    连续确认逻辑。
    条件满足时递增计数器，不满足时重置。
    返回 True 表示连续达到阈值，应触发告警。
    """
    if condition_met:
        current = storage.get_consecutive_count(counter_key)
        new_count = current + 1
        storage.update_consecutive_count(counter_key, new_count, ts_utc)
        if new_count >= CONSECUTIVE_THRESHOLD:
            storage.reset_consecutive_count(counter_key)
            return True
        return False
    else:
        storage.reset_consecutive_count(counter_key)
        return False


def _get_depth_total(snapshot: VenueSnapshot) -> Optional[float]:
    """获取 1% 深度总和。"""
    if not snapshot.orderbook:
        return None
    bid = snapshot.orderbook.depth_1pct_usdt_bid
    ask = snapshot.orderbook.depth_1pct_usdt_ask
    if bid is not None and ask is not None:
        return bid + ask
    return None


def check_depth_shrink(
    snapshot: VenueSnapshot,
    baseline: BaselineValues,
    config: MonitorConfig,
    storage: Storage,
) -> Optional[Alert]:
    """
    检测深度收缩。
    触发条件: depth_1pct_total < median * depth_drop_mult
    需要连续 3 次采样确认。warming_up 时不触发。
    """
    if baseline.warming_up:
        return None
    if not snapshot.orderbook:
        return None
    if baseline.depth_1pct_total_median is None:
        return None

    current = _get_depth_total(snapshot)
    if current is None:
        return None

    threshold = baseline.depth_1pct_total_median * config.thresholds.depth_drop_mult
    condition = current < threshold
    counter_key = f"depth_shrink:{snapshot.venue}:{snapshot.symbol}"

    if _check_with_consecutive(storage, counter_key, condition, snapshot.ts_utc):
        return Alert(
            alert_type="depth_shrink",
            venue=snapshot.venue,
            symbol=snapshot.symbol,
            severity="warn",
            message=(
                f"深度收缩: 1%深度 ${current:,.0f} "
                f"< 基线 ${baseline.depth_1pct_total_median:,.0f} "
                f"x {config.thresholds.depth_drop_mult} "
                f"= ${threshold:,.0f} "
                f"[样本{baseline.sample_count}条]"
            ),
            threshold_value=threshold,
            current_value=current,
            baseline_value=baseline.depth_1pct_total_median,
            ts_utc=snapshot.ts_utc,
            dedupe_key=f"depth_shrink:{snapshot.venue}:{snapshot.symbol}",
        )
    return None


def check_spread_widen(
    snapshot: VenueSnapshot,
    baseline: BaselineValues,
    config: MonitorConfig,
    storage: Storage,
) -> Optional[Alert]:
    """
    检测价差扩张。warming_up 时不触发。
    """
    if baseline.warming_up:
        return None
    if not snapshot.orderbook:
        return None
    if baseline.spread_bps_median is None:
        return None

    current = snapshot.orderbook.spread_bps
    if current is None:
        return None

    threshold = baseline.spread_bps_median * config.thresholds.spread_mult
    condition = current > threshold
    counter_key = f"spread_widen:{snapshot.venue}:{snapshot.symbol}"

    if _check_with_consecutive(storage, counter_key, condition, snapshot.ts_utc):
        return Alert(
            alert_type="spread_widen",
            venue=snapshot.venue,
            symbol=snapshot.symbol,
            severity="warn",
            message=(
                f"价差扩张: {current:.1f}bp "
                f"> 基线 {baseline.spread_bps_median:.1f}bp "
                f"x {config.thresholds.spread_mult} "
                f"= {threshold:.1f}bp "
                f"[样本{baseline.sample_count}条]"
            ),
            threshold_value=threshold,
            current_value=current,
            baseline_value=baseline.spread_bps_median,
            ts_utc=snapshot.ts_utc,
            dedupe_key=f"spread_widen:{snapshot.venue}:{snapshot.symbol}",
        )
    return None


def check_impact_cost_up(
    snapshot: VenueSnapshot,
    baseline: BaselineValues,
    config: MonitorConfig,
    storage: Storage,
) -> Optional[Alert]:
    """
    检测冲击成本上升。warming_up 时不触发。
    """
    if baseline.warming_up:
        return None
    if not snapshot.orderbook:
        return None
    if baseline.slip_bps_n2_median is None:
        return None

    ob = snapshot.orderbook
    slip_values = []
    if ob.impact_buy_n2 and ob.impact_buy_n2.slip_bps is not None:
        slip_values.append(ob.impact_buy_n2.slip_bps)
    if ob.impact_sell_n2 and ob.impact_sell_n2.slip_bps is not None:
        slip_values.append(ob.impact_sell_n2.slip_bps)

    if not slip_values:
        return None

    current = max(slip_values)
    threshold = baseline.slip_bps_n2_median * config.thresholds.slip_mult
    condition = current > threshold
    counter_key = f"impact_cost_up:{snapshot.venue}:{snapshot.symbol}"

    if _check_with_consecutive(storage, counter_key, condition, snapshot.ts_utc):
        depth_total = _get_depth_total(snapshot)
        depth_str = f"${depth_total:,.0f}" if depth_total else "-"
        return Alert(
            alert_type="impact_cost_up",
            venue=snapshot.venue,
            symbol=snapshot.symbol,
            severity="warn",
            message=(
                f"冲击成本上升: slip_n2 {current:.1f}bp "
                f"> 基线 {baseline.slip_bps_n2_median:.1f}bp "
                f"x {config.thresholds.slip_mult} "
                f"= {threshold:.1f}bp "
                f"| depth1%={depth_str} "
                f"[样本{baseline.sample_count}条]"
            ),
            threshold_value=threshold,
            current_value=current,
            baseline_value=baseline.slip_bps_n2_median,
            ts_utc=snapshot.ts_utc,
            dedupe_key=f"impact_cost_up:{snapshot.venue}:{snapshot.symbol}",
        )
    return None


def check_insufficient_liquidity(
    snapshot: VenueSnapshot,
    config: MonitorConfig,
) -> Optional[Alert]:
    """
    检测流动性不足。
    触发条件: insufficient_liquidity=True 且缺口超过阈值百分比
    立即触发（无需连续确认，不受 warming_up 影响）。
    告警消息包含 filled_notional 和 depth_1pct_total。
    """
    if not snapshot.orderbook:
        return None

    ob = snapshot.orderbook
    depth_total = _get_depth_total(snapshot)
    depth_str = f"${depth_total:,.0f}" if depth_total else "-"

    for label, impact in [
        ("buy_n2", ob.impact_buy_n2),
        ("sell_n2", ob.impact_sell_n2),
        ("buy_n1", ob.impact_buy_n1),
        ("sell_n1", ob.impact_sell_n1),
    ]:
        if impact and impact.insufficient_liquidity:
            gap_pct = (
                impact.shortfall / impact.target_notional * 100
                if impact.target_notional > 0
                else 0
            )
            if gap_pct > config.thresholds.insufficient_liq_gap_pct:
                return Alert(
                    alert_type="insufficient_liquidity",
                    venue=snapshot.venue,
                    symbol=snapshot.symbol,
                    severity="critical",
                    message=(
                        f"流动性不足 ({label}): "
                        f"目标 ${impact.target_notional:,.0f}, "
                        f"成交 ${impact.filled_notional:,.0f}, "
                        f"缺口 ${impact.shortfall:,.0f} ({gap_pct:.0f}%) "
                        f"| depth1%={depth_str}"
                    ),
                    threshold_value=impact.target_notional * (1 - config.thresholds.insufficient_liq_gap_pct / 100),
                    current_value=impact.filled_notional,
                    baseline_value=None,
                    ts_utc=snapshot.ts_utc,
                    dedupe_key=(
                        f"insufficient_liquidity:{snapshot.venue}:{snapshot.symbol}"
                    ),
                )
    return None


def check_volume_spike(
    snapshot: VenueSnapshot,
    baseline: BaselineValues,
    config: MonitorConfig,
) -> Optional[Alert]:
    """
    检测量价异常（可选）。warming_up 时不触发。
    """
    if baseline.warming_up:
        return None
    if not snapshot.ticker:
        return None
    if baseline.volume_24h_mean_7d is None:
        return None

    volume = snapshot.ticker.quote_volume_24h
    if volume is None:
        return None

    threshold = baseline.volume_24h_mean_7d * config.thresholds.volume_spike_mult
    if volume <= threshold:
        return None

    direction = "放量"
    pct = snapshot.ticker.pct_change_24h
    if pct is not None:
        if pct > 0:
            direction = "放量上行"
        elif pct < 0:
            direction = "放量下行"

    return Alert(
        alert_type="volume_spike",
        venue=snapshot.venue,
        symbol=snapshot.symbol,
        severity="info",
        message=(
            f"量价异常 ({direction}): 24h量 ${volume:,.0f} "
            f"> 7d均值 ${baseline.volume_24h_mean_7d:,.0f} "
            f"x {config.thresholds.volume_spike_mult} "
            f"= ${threshold:,.0f} "
            f"[样本{baseline.sample_count}条]"
        ),
        threshold_value=threshold,
        current_value=volume,
        baseline_value=baseline.volume_24h_mean_7d,
        ts_utc=snapshot.ts_utc,
        dedupe_key=f"volume_spike:{snapshot.venue}:{snapshot.symbol}",
    )


def run_all_checks(
    snapshot: VenueSnapshot,
    baseline: BaselineValues,
    config: MonitorConfig,
    storage: Storage,
) -> list[Alert]:
    """
    对单个 venue 执行所有告警检查。
    返回新产生的告警列表（已去重）。
    warming_up 时只有 insufficient_liquidity 可触发。
    """
    if snapshot.missing_market:
        return []

    alerts = []
    checks = [
        check_depth_shrink(snapshot, baseline, config, storage),
        check_spread_widen(snapshot, baseline, config, storage),
        check_impact_cost_up(snapshot, baseline, config, storage),
        check_insufficient_liquidity(snapshot, config),
        check_volume_spike(snapshot, baseline, config),
    ]

    for alert in checks:
        if alert is None:
            continue
        if storage.check_dedupe(alert.dedupe_key, config.dedupe_window_seconds):
            logger.info("告警去重: %s", alert.dedupe_key)
            continue
        alerts.append(alert)

    return alerts
