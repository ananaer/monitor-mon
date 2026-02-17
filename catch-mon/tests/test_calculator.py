"""
calculator 模块单元测试。
覆盖：订单簿深度计算、吃单滑点算法（含 insufficient_liquidity）、波动率计算。
"""

import math

import pytest

from mon_monitor.calculator import (
    calc_atr_like,
    calc_depth_within_pct,
    calc_impact_cost,
    calc_pct_change_from_ohlcv,
    calc_realized_vol,
    process_orderbook,
)


class TestCalcDepthWithinPct:
    """订单簿区间深度计算测试。"""

    def test_bid_depth_1pct(self):
        """mid=100 时，1% 范围内（99~100）的 bids 深度。"""
        # bids: 由高到低
        bids = [
            [100.0, 10.0],
            [99.5, 20.0],
            [99.0, 30.0],
            [98.5, 40.0],
        ]
        mid = 100.0
        # 1% 范围：99.0 ~ 100.0
        # 100.0 * 10 = 1000
        # 99.5 * 20 = 1990
        # 99.0 * 30 = 2970
        # 98.5 在范围外
        result = calc_depth_within_pct(bids, mid, 1.0, "bid")
        expected = 1000.0 + 1990.0 + 2970.0
        assert abs(result - expected) < 0.01

    def test_ask_depth_1pct(self):
        """mid=100 时，1% 范围内（100~101）的 asks 深度。"""
        asks = [
            [100.0, 10.0],
            [100.5, 20.0],
            [101.0, 30.0],
            [101.5, 40.0],
        ]
        mid = 100.0
        # 1% 范围：100.0 ~ 101.0
        # 100.0 * 10 = 1000
        # 100.5 * 20 = 2010
        # 101.0 * 30 = 3030
        # 101.5 在范围外
        result = calc_depth_within_pct(asks, mid, 1.0, "ask")
        expected = 1000.0 + 2010.0 + 3030.0
        assert abs(result - expected) < 0.01

    def test_empty_levels(self):
        """空订单簿返回 0。"""
        result = calc_depth_within_pct([], 100.0, 1.0, "bid")
        assert result == 0.0

    def test_2pct_range(self):
        """2% 范围包含更多档位。"""
        bids = [
            [100.0, 10.0],
            [99.0, 20.0],
            [98.5, 30.0],
            [97.0, 40.0],
        ]
        mid = 100.0
        # 2% 范围：98.0 ~ 100.0
        # 100.0 * 10 = 1000
        # 99.0 * 20 = 1980
        # 98.5 * 30 = 2955
        # 97.0 在范围外
        result = calc_depth_within_pct(bids, mid, 2.0, "bid")
        expected = 1000.0 + 1980.0 + 2955.0
        assert abs(result - expected) < 0.01


class TestCalcImpactCost:
    """吃单滑点算法测试。"""

    def test_buy_full_fill(self):
        """买入完全成交，无流动性不足。"""
        # asks 由低到高
        asks = [
            [100.0, 50.0],
            [100.5, 50.0],
            [101.0, 50.0],
        ]
        mid = 100.0
        # 买 1000 USDT
        # 100.0 * 50 = 5000 > 1000，在第一档即可成交
        # 成交量 = 1000 / 100.0 = 10.0 个
        # avg_fill = 100.0
        result = calc_impact_cost(asks, mid, 1000.0, "buy")
        assert not result.insufficient_liquidity
        assert abs(result.avg_fill_price - 100.0) < 0.01
        assert abs(result.slip_bps - 0.0) < 0.01
        assert abs(result.filled_notional - 1000.0) < 0.01

    def test_buy_multi_level(self):
        """买入跨多档成交。"""
        asks = [
            [100.0, 10.0],
            [101.0, 10.0],
            [102.0, 10.0],
        ]
        mid = 100.0
        # 买 2050 USDT
        # 第一档: 100.0 * 10 = 1000, remaining = 1050
        # 第二档: 101.0 * 10 = 1010, remaining = 40
        # 第三档: 部分成交 40 / 102 = 0.392... 个
        # total_cost = 1000 + 1010 + 40 = 2050
        # total_base = 10 + 10 + 40/102 = 20.392...
        # avg_fill = 2050 / 20.392... = 100.527...
        result = calc_impact_cost(asks, mid, 2050.0, "buy")
        assert not result.insufficient_liquidity
        assert result.avg_fill_price > 100.0
        assert result.slip_bps > 0
        assert abs(result.filled_notional - 2050.0) < 0.01

    def test_sell_full_fill(self):
        """卖出完全成交。"""
        bids = [
            [100.0, 50.0],
            [99.5, 50.0],
        ]
        mid = 100.0
        result = calc_impact_cost(bids, mid, 1000.0, "sell")
        assert not result.insufficient_liquidity
        # 在第一档即可成交
        assert abs(result.avg_fill_price - 100.0) < 0.01
        # sell: slip = (mid - avg_fill) / mid * 10000
        assert abs(result.slip_bps - 0.0) < 0.01

    def test_insufficient_liquidity(self):
        """订单簿不足以满足成交量。"""
        asks = [
            [100.0, 1.0],
            [101.0, 1.0],
        ]
        mid = 100.0
        # 总可用: 100 + 101 = 201 USDT
        # 需要: 1000 USDT
        result = calc_impact_cost(asks, mid, 1000.0, "buy")
        assert result.insufficient_liquidity
        assert result.shortfall > 0
        assert abs(result.filled_notional - 201.0) < 0.01
        assert abs(result.shortfall - 799.0) < 0.01

    def test_empty_orderbook(self):
        """空订单簿。"""
        result = calc_impact_cost([], 100.0, 1000.0, "buy")
        assert result.insufficient_liquidity
        assert result.shortfall == 1000.0
        assert result.avg_fill_price is None

    def test_sell_multi_level_slip(self):
        """卖出跨多档，验证滑点为正值。"""
        bids = [
            [100.0, 5.0],
            [99.0, 5.0],
            [98.0, 5.0],
        ]
        mid = 100.0
        # 卖 990 USDT
        # 第一档: 100 * 5 = 500, remaining = 490
        # 第二档: 99 * 5 = 495 >= 490, 部分成交
        result = calc_impact_cost(bids, mid, 990.0, "sell")
        assert not result.insufficient_liquidity
        assert result.avg_fill_price < 100.0
        # slip_sell = (mid - avg) / mid * 10000 应为正
        assert result.slip_bps > 0


class TestCalcRealizedVol:
    """波动率计算测试。"""

    def test_constant_prices(self):
        """价格不变时波动率为 0。"""
        closes = [100.0] * 30
        vol = calc_realized_vol(closes)
        assert vol is not None
        assert abs(vol) < 1e-10

    def test_varying_prices(self):
        """价格波动时波动率为正。"""
        closes = [100 + (i % 3) * 0.5 for i in range(30)]
        vol = calc_realized_vol(closes)
        assert vol is not None
        assert vol > 0

    def test_insufficient_data(self):
        """数据不足时返回 None。"""
        assert calc_realized_vol([]) is None
        assert calc_realized_vol([100.0]) is None


class TestCalcAtrLike:
    """ATR 近似计算测试。"""

    def test_basic_atr(self):
        """基本 ATR 计算。"""
        # [ts, open, high, low, close, volume]
        candles = [
            [0, 100, 105, 95, 102, 1000],
            [1, 102, 108, 98, 104, 1000],
            [2, 104, 106, 100, 103, 1000],
        ]
        result = calc_atr_like(candles)
        # (105-95 + 108-98 + 106-100) / 3 = (10 + 10 + 6) / 3 = 8.667
        assert result is not None
        assert abs(result - 8.667) < 0.01

    def test_empty_candles(self):
        """空数据返回 None。"""
        assert calc_atr_like([]) is None


class TestCalcPctChange:
    """价格变化百分比测试。"""

    def test_1h_change(self):
        """1 小时变化。"""
        candles = [
            [0, 100, 105, 95, 100, 1000],
            [1, 100, 106, 94, 110, 1000],
        ]
        result = calc_pct_change_from_ohlcv(candles, 1)
        assert result is not None
        assert abs(result - 10.0) < 0.01

    def test_insufficient_data(self):
        """数据不足返回 None。"""
        candles = [[0, 100, 105, 95, 100, 1000]]
        result = calc_pct_change_from_ohlcv(candles, 1)
        assert result is None


class TestProcessOrderbook:
    """完整订单簿处理测试。"""

    def test_full_processing(self):
        """完整处理流程。"""
        ob_raw = {
            "bids": [
                [100.0, 50.0],
                [99.5, 50.0],
                [99.0, 50.0],
                [98.0, 50.0],
            ],
            "asks": [
                [100.5, 50.0],
                [101.0, 50.0],
                [101.5, 50.0],
                [102.0, 50.0],
            ],
        }
        result = process_orderbook(ob_raw, 100.25, 1000.0, 10000.0, 100)

        assert result.best_bid == 100.0
        assert result.best_ask == 100.5
        assert result.mid is not None
        assert result.spread_bps is not None
        assert result.depth_1pct_usdt_bid is not None
        assert result.depth_1pct_usdt_ask is not None
        assert result.impact_buy_n1 is not None
        assert result.impact_sell_n1 is not None
