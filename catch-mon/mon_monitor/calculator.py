"""
派生指标计算模块。
所有公式均可用 raw_json + 本模块函数复算。

公式说明：
1. 名义额 = price * amount_base
2. 累计深度 = 区间内各档名义额求和
3. 冲击成本（吃单滑点）：
   - buy：按 asks 由低到高逐档吃单，直到累计名义额 >= notional
   - sell：按 bids 由高到低逐档吃单
   - slip_bps_buy = (avg_fill_price_buy - mid) / mid * 10000
   - slip_bps_sell = (mid - avg_fill_price_sell) / mid * 10000
4. realized_vol_24h：近 24 根 1h 收益率的标准差
5. atr_like_24h：近 24 根 1h 高低差绝对值的均值
"""

import math
from typing import Optional

from mon_monitor.models import (
    ImpactCostResult,
    OhlcvData,
    OrderBookData,
    VenueSnapshot,
)


def calc_depth_within_pct(
    levels: list[list[float]],
    mid: float,
    pct: float,
    side: str,
) -> float:
    """
    计算 mid 上下 pct% 范围内的累计名义额（USDT）。

    参数:
        levels: [[price, amount], ...] 订单簿某一侧的档位
        mid: 中间价
        pct: 百分比范围（如 1.0 表示 1%）
        side: "bid" 或 "ask"

    返回:
        累计名义额（USDT）
    """
    total_notional = 0.0
    if side == "bid":
        # bids: mid 下方 pct% 范围
        lower_bound = mid * (1 - pct / 100.0)
        for price, amount in levels:
            if price >= lower_bound:
                total_notional += price * amount
    elif side == "ask":
        # asks: mid 上方 pct% 范围
        upper_bound = mid * (1 + pct / 100.0)
        for price, amount in levels:
            if price <= upper_bound:
                total_notional += price * amount
    return total_notional


def calc_impact_cost(
    levels: list[list[float]],
    mid: float,
    notional: float,
    side: str,
) -> ImpactCostResult:
    """
    吃单滑点估算。

    参数:
        levels: 订单簿某一侧的档位 [[price, amount], ...]
                buy 用 asks（价格由低到高），sell 用 bids（价格由高到低）
        mid: 中间价
        notional: 目标成交名义额（USDT）
        side: "buy" 或 "sell"

    返回:
        ImpactCostResult 包含均价、滑点、是否流动性不足等
    """
    result = ImpactCostResult(target_notional=notional)
    remaining = notional
    total_cost = 0.0
    total_base = 0.0

    for price, amount in levels:
        if remaining <= 0:
            break
        level_notional = price * amount
        if level_notional <= remaining:
            # 整档吃完
            total_cost += level_notional
            total_base += amount
            remaining -= level_notional
        else:
            # 部分成交
            fill_amount = remaining / price
            total_cost += remaining
            total_base += fill_amount
            remaining = 0

    result.filled_notional = notional - remaining

    if total_base > 0:
        result.avg_fill_price = total_cost / total_base

    if remaining > 0:
        result.insufficient_liquidity = True
        result.shortfall = remaining

    if result.avg_fill_price is not None and mid > 0:
        if side == "buy":
            # slip_bps_buy = (avg_fill - mid) / mid * 10000
            result.slip_bps = (result.avg_fill_price - mid) / mid * 10000
        else:
            # slip_bps_sell = (mid - avg_fill) / mid * 10000
            result.slip_bps = (mid - result.avg_fill_price) / mid * 10000

    return result


def calc_realized_vol(closes: list[float]) -> Optional[float]:
    """
    计算收益率波动率（标准差）。
    使用最近 24 根 1h 收盘价。

    公式: std(ln(close[i] / close[i-1])) for i in 1..24
    """
    if len(closes) < 2:
        return None

    # 取最近 25 个价格（产生 24 个收益率）
    recent = closes[-25:] if len(closes) >= 25 else closes
    returns = []
    for i in range(1, len(recent)):
        if recent[i - 1] > 0 and recent[i] > 0:
            returns.append(math.log(recent[i] / recent[i - 1]))

    if len(returns) < 2:
        return None

    mean_r = sum(returns) / len(returns)
    variance = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(variance)


def calc_atr_like(candles: list[list]) -> Optional[float]:
    """
    高低差近似 ATR。
    使用最近 24 根 1h K线的 (high - low) 绝对值均值。

    candles 格式: [[timestamp, open, high, low, close, volume], ...]
    """
    recent = candles[-24:] if len(candles) >= 24 else candles
    if not recent:
        return None

    ranges = []
    for candle in recent:
        # candle: [ts, open, high, low, close, volume]
        high = candle[2]
        low = candle[3]
        if high is not None and low is not None:
            ranges.append(abs(high - low))

    if not ranges:
        return None
    return sum(ranges) / len(ranges)


def calc_pct_change_from_ohlcv(
    candles: list[list],
    hours: int,
) -> Optional[float]:
    """
    从 OHLCV 数据计算 N 小时价格变化百分比。
    """
    if not candles or len(candles) < hours + 1:
        return None

    current_close = candles[-1][4]
    past_close = candles[-(hours + 1)][4]

    if past_close and past_close > 0 and current_close:
        return ((current_close - past_close) / past_close) * 100
    return None


def process_orderbook(
    ob_raw: dict,
    mid: float,
    notional_1: float,
    notional_2: float,
    orderbook_levels: int,
) -> OrderBookData:
    """
    处理原始订单簿数据，计算所有派生指标。
    """
    bids = ob_raw.get("bids", [])
    asks = ob_raw.get("asks", [])

    data = OrderBookData()

    if bids:
        data.best_bid = bids[0][0]
    if asks:
        data.best_ask = asks[0][0]

    if data.best_bid is not None and data.best_ask is not None:
        data.mid = (data.best_bid + data.best_ask) / 2
        if data.mid > 0:
            data.spread_bps = (
                (data.best_ask - data.best_bid) / data.mid * 10000
            )

    effective_mid = mid if mid > 0 else (data.mid or 0)

    if effective_mid > 0:
        # 深度计算
        data.depth_1pct_usdt_bid = calc_depth_within_pct(
            bids, effective_mid, 1.0, "bid"
        )
        data.depth_1pct_usdt_ask = calc_depth_within_pct(
            asks, effective_mid, 1.0, "ask"
        )
        data.depth_2pct_usdt_bid = calc_depth_within_pct(
            bids, effective_mid, 2.0, "bid"
        )
        data.depth_2pct_usdt_ask = calc_depth_within_pct(
            asks, effective_mid, 2.0, "ask"
        )

        # 冲击成本计算
        # asks 已经是由低到高排列（用于 buy）
        # bids 已经是由高到低排列（用于 sell）
        data.impact_buy_n1 = calc_impact_cost(
            asks, effective_mid, notional_1, "buy"
        )
        data.impact_sell_n1 = calc_impact_cost(
            bids, effective_mid, notional_1, "sell"
        )
        data.impact_buy_n2 = calc_impact_cost(
            asks, effective_mid, notional_2, "buy"
        )
        data.impact_sell_n2 = calc_impact_cost(
            bids, effective_mid, notional_2, "sell"
        )

    # 保存原始档位数据
    data.orderbook_levels_raw = {
        "bids": bids[:orderbook_levels],
        "asks": asks[:orderbook_levels],
    }

    return data


def process_ohlcv(candles: list[list]) -> OhlcvData:
    """
    处理 OHLCV 数据，计算波动率与 ATR。
    """
    data = OhlcvData(candle_count=len(candles) if candles else 0)

    if not candles:
        return data

    # 提取收盘价
    closes = [c[4] for c in candles if c[4] is not None]
    data.realized_vol_24h = calc_realized_vol(closes)
    data.atr_like_24h = calc_atr_like(candles)

    return data


def enrich_snapshot(snapshot: VenueSnapshot, config) -> VenueSnapshot:
    """
    对采集后的 snapshot 进行派生计算填充。
    """
    if snapshot.missing_market:
        return snapshot

    ob_raw = snapshot.raw_json.get("orderbook_raw")
    if ob_raw:
        # 先取 ticker 里的 last_price 作为参考 mid
        ticker_mid = 0
        if snapshot.ticker and snapshot.ticker.last_price:
            ticker_mid = snapshot.ticker.last_price

        snapshot.orderbook = process_orderbook(
            ob_raw,
            ticker_mid,
            config.notional_1,
            config.notional_2,
            config.orderbook_levels,
        )

    ohlcv_candles = snapshot.raw_json.get("ohlcv_candles")
    if ohlcv_candles:
        snapshot.ohlcv = process_ohlcv(ohlcv_candles)

        # 尝试从 OHLCV 计算 pct_change
        if snapshot.ticker:
            if snapshot.ticker.pct_change_1h is None:
                snapshot.ticker.pct_change_1h = calc_pct_change_from_ohlcv(
                    ohlcv_candles, 1
                )
            if snapshot.ticker.pct_change_24h is None:
                snapshot.ticker.pct_change_24h = calc_pct_change_from_ohlcv(
                    ohlcv_candles, 24
                )

    # 当 OI 只有合约数量时，用 last_price 推算 USDT 值
    oi = snapshot.open_interest
    if oi and oi.open_interest_value_usdt is None:
        if oi.open_interest_amount_contracts is not None:
            price = None
            if snapshot.ticker and snapshot.ticker.last_price:
                price = snapshot.ticker.last_price
            elif snapshot.orderbook and snapshot.orderbook.mid:
                price = snapshot.orderbook.mid
            if price and price > 0:
                oi.open_interest_value_usdt = (
                    oi.open_interest_amount_contracts * price
                )

    return snapshot
