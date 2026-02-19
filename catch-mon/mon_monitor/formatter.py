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
    """安全格式化数值，None 时返回 '-'。"""
    if val is None:
        return "-"
    if isinstance(val, float):
        return f"{val:{fmt}}"
    return str(val)


def _fmt_usd(val, decimals=0) -> str:
    if val is None:
        return "-"
    if val >= 1_000_000:
        return f"${val / 1_000_000:,.{max(decimals, 1)}f}M"
    if val >= 1_000:
        return f"${val / 1_000:,.{max(decimals, 1)}f}K"
    return f"${val:,.{decimals}f}"


def _fmt_pct(val) -> str:
    if val is None:
        return "-"
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.2f}%"


def _fmt_bps(val) -> str:
    if val is None:
        return "-"
    return f"{val:.1f}bp"


def _fmt_funding(val) -> str:
    if val is None:
        return "-"
    return f"{val * 100:.4f}%"


def _snapshot_to_dict(snapshot: VenueSnapshot) -> dict:
    """将 VenueSnapshot 转为可序列化的 dict（移除大体积原始数据）。"""
    d = asdict(snapshot)
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


def _get_slip_n2_max(snap: VenueSnapshot):
    """取 n2 滑点 max(buy, sell)。"""
    if not snap.orderbook:
        return None
    vals = []
    if snap.orderbook.impact_buy_n2 and snap.orderbook.impact_buy_n2.slip_bps is not None:
        vals.append(snap.orderbook.impact_buy_n2.slip_bps)
    if snap.orderbook.impact_sell_n2 and snap.orderbook.impact_sell_n2.slip_bps is not None:
        vals.append(snap.orderbook.impact_sell_n2.slip_bps)
    return max(vals) if vals else None


def _get_depth_total(snap: VenueSnapshot):
    if not snap.orderbook:
        return None
    bid = snap.orderbook.depth_1pct_usdt_bid
    ask = snap.orderbook.depth_1pct_usdt_ask
    if bid is not None and ask is not None:
        return bid + ask
    return None


def _get_oi(snap: VenueSnapshot):
    if not snap.open_interest:
        return None
    return snap.open_interest.open_interest_value_usdt


def print_summary(
    snapshots: dict[str, VenueSnapshot],
    baselines: dict[str, BaselineValues],
    alerts: list[Alert],
    tz_name: str = "Asia/Tokyo",
):
    """
    打印用户友好的表格化摘要。
    三家交易所横向对比，一目了然。
    """
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)

    W = 72
    venues = list(snapshots.keys())
    COL = 16

    def line(char="─"):
        return char * W

    def header_bar():
        left = "  MON Monitor"
        right = now.strftime("%Y-%m-%d %H:%M:%S %Z") + "  "
        gap = W - len(left) - len(right)
        return left + " " * max(gap, 2) + right

    def row(label: str, values: list[str]):
        """生成一行：label 固定宽度 + 各 venue 列。"""
        cells = f"  {label:<18}"
        for v in values:
            cells += f"{v:>{COL}}"
        return cells

    print()
    print(f"  {line('━')}")
    print(header_bar())
    print(f"  {line('━')}")

    # venue header
    venue_labels = []
    for v in venues:
        snap = snapshots[v]
        if snap.missing_market:
            venue_labels.append(f"{v.upper()}*")
        else:
            venue_labels.append(v.upper())
    print(row("", venue_labels))
    print(f"  {line()}")

    # Price
    prices = []
    for v in venues:
        snap = snapshots[v]
        if snap.missing_market:
            prices.append("N/A")
        elif snap.ticker and snap.ticker.last_price is not None:
            prices.append(f"${snap.ticker.last_price:.5f}")
        else:
            prices.append("-")
    print(row("Price", prices))

    # 24h Change
    changes = []
    for v in venues:
        snap = snapshots[v]
        if snap.missing_market:
            changes.append("N/A")
        elif snap.ticker:
            changes.append(_fmt_pct(snap.ticker.pct_change_24h))
        else:
            changes.append("-")
    print(row("24h Change", changes))

    # 24h Volume
    vols = []
    for v in venues:
        snap = snapshots[v]
        if snap.missing_market:
            vols.append("N/A")
        elif snap.ticker:
            vols.append(_fmt_usd(snap.ticker.quote_volume_24h))
        else:
            vols.append("-")
    print(row("24h Volume", vols))

    print(f"  {line()}")

    # Spread
    spreads = []
    for v in venues:
        snap = snapshots[v]
        if snap.missing_market:
            spreads.append("N/A")
        elif snap.orderbook:
            spreads.append(_fmt_bps(snap.orderbook.spread_bps))
        else:
            spreads.append("-")
    print(row("Spread", spreads))

    # Depth 1%
    depths = []
    for v in venues:
        snap = snapshots[v]
        if snap.missing_market:
            depths.append("N/A")
        else:
            depths.append(_fmt_usd(_get_depth_total(snap)))
    print(row("Depth 1%", depths))

    # Depth 2%
    depths2 = []
    for v in venues:
        snap = snapshots[v]
        if snap.missing_market:
            depths2.append("N/A")
        elif snap.orderbook:
            b2 = snap.orderbook.depth_2pct_usdt_bid
            a2 = snap.orderbook.depth_2pct_usdt_ask
            if b2 is not None and a2 is not None:
                depths2.append(_fmt_usd(b2 + a2))
            else:
                depths2.append("-")
        else:
            depths2.append("-")
    print(row("Depth 2%", depths2))

    # Slip 10K
    slips1 = []
    for v in venues:
        snap = snapshots[v]
        if snap.missing_market:
            slips1.append("N/A")
        elif snap.orderbook and snap.orderbook.impact_buy_n1:
            slips1.append(_fmt_bps(snap.orderbook.impact_buy_n1.slip_bps))
        else:
            slips1.append("-")
    print(row("Slip 10K buy", slips1))

    # Slip 100K
    slips2 = []
    for v in venues:
        snap = snapshots[v]
        if snap.missing_market:
            slips2.append("N/A")
        else:
            slips2.append(_fmt_bps(_get_slip_n2_max(snap)))
    print(row("Slip 100K max", slips2))

    print(f"  {line()}")

    # Funding
    fundings = []
    for v in venues:
        snap = snapshots[v]
        if snap.missing_market:
            fundings.append("N/A")
        elif snap.funding:
            fundings.append(_fmt_funding(snap.funding.funding_rate))
        else:
            fundings.append("-")
    print(row("Funding Rate", fundings))

    # OI
    ois = []
    for v in venues:
        snap = snapshots[v]
        if snap.missing_market:
            ois.append("N/A")
        else:
            ois.append(_fmt_usd(_get_oi(snap)))
    print(row("Open Interest", ois))

    # Volatility
    vols_rv = []
    for v in venues:
        snap = snapshots[v]
        if snap.missing_market:
            vols_rv.append("N/A")
        elif snap.ohlcv and snap.ohlcv.realized_vol_24h is not None:
            vols_rv.append(f"{snap.ohlcv.realized_vol_24h * 100:.2f}%")
        else:
            vols_rv.append("-")
    print(row("RVol 24h", vols_rv))

    # Baseline status
    bl_status = []
    for v in venues:
        bl = baselines.get(v)
        if bl is None:
            bl_status.append("-")
        elif bl.warming_up:
            bl_status.append(f"warmup({bl.sample_count})")
        else:
            bl_status.append(f"ok({bl.sample_count})")
    print(row("Baseline", bl_status))

    print(f"  {line()}")

    # Errors
    has_errors = False
    for v in venues:
        snap = snapshots[v]
        if snap.missing_market:
            print(f"  * {v.upper()}: missing_market (symbol 不存在或网络不可达)")
            has_errors = True
        elif snap.errors:
            print(f"  ! {v.upper()}: {', '.join(snap.errors)}")
            has_errors = True

    if has_errors:
        print(f"  {line()}")

    # Alerts
    if not alerts:
        print("  Alerts: 0 (all clear)")
    else:
        severity_icon = {
            "critical": "!!",
            "warn": " !",
            "info": " i",
        }
        print(f"  Alerts: {len(alerts)}")
        for a in alerts:
            icon = severity_icon.get(a.severity, "  ")
            print(f"  [{icon}] {a.venue:>8} | {a.alert_type}: {a.message}")

    print(f"  {line('━')}")
    print()
