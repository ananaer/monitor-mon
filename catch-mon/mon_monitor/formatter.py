"""
输出格式化模块。
生成 machine-readable JSON 和 human-readable stdout 摘要。
"""

import json
from dataclasses import asdict
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from mon_monitor.models import Alert, BaselineValues, MonitorOutput, VenueSnapshot


def _safe_value(val: Any, fmt: str = ".2f") -> str:
    """安全格式化数值，None 时返回 'missing'。"""
    if val is None:
        return "missing"
    if isinstance(val, float):
        return f"{val:{fmt}}"
    return str(val)


def _snapshot_to_dict(snapshot: VenueSnapshot) -> dict:
    """将 VenueSnapshot 转为可序列化的 dict（移除大体积原始数据）。"""
    d = asdict(snapshot)
    # 移除 raw_json 中的大体积数据，保留摘要
    if "raw_json" in d:
        raw = d["raw_json"]
        raw.pop("orderbook_raw", None)
        raw.pop("ohlcv_candles", None)
    return d


def build_output(
    token: str,
    snapshots: dict[str, VenueSnapshot],
    baselines: dict[str, BaselineValues],
    alerts: list[Alert],
) -> MonitorOutput:
    """构建标准输出对象。"""
    from datetime import timezone

    output = MonitorOutput(
        ts_utc=datetime.now(timezone.utc).isoformat(),
        token=token,
        snapshots={k: _snapshot_to_dict(v) for k, v in snapshots.items()},
        baselines={k: asdict(v) for k, v in baselines.items()},
        alerts=alerts,
    )
    return output


def output_to_json(output: MonitorOutput) -> str:
    """将输出对象序列化为 JSON 字符串。"""
    d = asdict(output)
    return json.dumps(d, indent=2, default=str, ensure_ascii=False)


def print_summary(
    snapshots: dict[str, VenueSnapshot],
    baselines: dict[str, BaselineValues],
    alerts: list[Alert],
    tz_name: str = "Asia/Tokyo",
):
    """
    打印 human-readable stdout 摘要。
    """
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    print(f"\n{'='*60}")
    print(f"  MON 公开数据监控 — {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"{'='*60}")

    for venue_name, snap in snapshots.items():
        print(f"\n--- {venue_name.upper()} ---")

        if snap.missing_market:
            print(f"  状态: missing_market")
            if snap.errors:
                for e in snap.errors:
                    print(f"  错误: {e}")
            continue

        # Price
        price = "missing"
        if snap.ticker and snap.ticker.last_price is not None:
            price = f"{snap.ticker.last_price:.4f}"
        print(f"  Price: {price}")

        # Spread
        spread = "missing"
        if snap.orderbook and snap.orderbook.spread_bps is not None:
            spread = f"{snap.orderbook.spread_bps:.2f} bps"
        print(f"  Spread: {spread}")

        # Depth 1%
        depth_total = "missing"
        if snap.orderbook:
            bid = snap.orderbook.depth_1pct_usdt_bid
            ask = snap.orderbook.depth_1pct_usdt_ask
            if bid is not None and ask is not None:
                depth_total = f"{bid + ask:,.0f} USDT (bid={bid:,.0f} ask={ask:,.0f})"
        print(f"  Depth 1%: {depth_total}")

        # Slip N2
        slip = "missing"
        if snap.orderbook:
            vals = []
            if snap.orderbook.impact_buy_n2 and snap.orderbook.impact_buy_n2.slip_bps is not None:
                vals.append(snap.orderbook.impact_buy_n2.slip_bps)
            if snap.orderbook.impact_sell_n2 and snap.orderbook.impact_sell_n2.slip_bps is not None:
                vals.append(snap.orderbook.impact_sell_n2.slip_bps)
            if vals:
                slip = f"max {max(vals):.2f} bps"
        print(f"  Slip N2 (100k): {slip}")

        # Funding
        funding = "missing"
        if snap.funding and snap.funding.funding_rate is not None:
            funding = f"{snap.funding.funding_rate * 100:.4f}%"
        print(f"  Funding: {funding}")

        # OI
        oi = "missing"
        if snap.open_interest:
            if snap.open_interest.open_interest_value_usdt is not None:
                oi = f"{snap.open_interest.open_interest_value_usdt:,.0f} USDT"
            elif snap.open_interest.open_interest_amount_contracts is not None:
                oi = f"{snap.open_interest.open_interest_amount_contracts:,.0f} contracts"
        print(f"  OI: {oi}")

        # 错误
        if snap.errors:
            print(f"  ⚠ 部分采集失败: {', '.join(snap.errors)}")

    # 告警摘要
    print(f"\n--- 告警 ---")
    if not alerts:
        print("  本轮无新增告警")
    else:
        print(f"  新增告警: {len(alerts)} 条")
        type_counts: dict[str, int] = {}
        for a in alerts:
            type_counts[a.alert_type] = type_counts.get(a.alert_type, 0) + 1
        for atype, count in type_counts.items():
            print(f"    {atype}: {count}")
        for a in alerts:
            severity_tag = f"[{a.severity.upper()}]"
            print(f"  {severity_tag} {a.venue}: {a.message}")

    print(f"{'='*60}\n")
