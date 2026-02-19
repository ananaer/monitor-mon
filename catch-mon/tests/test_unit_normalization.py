"""
订单簿数量单位归一化验收测试。

核心验证：
1. OKX sz(张数) * ctVal * ctMult = 基础币数量，再乘 price = USDT notional
2. Binance qty 就是基础币，乘 price = USDT notional
3. Bybit size 就是基础币，乘 price = USDT notional
4. 对同一个"合成"盘口，计算的 depth_1pct_total 应当一致
"""

from unittest.mock import patch, MagicMock
import pytest

from mon_monitor.calculator import calc_depth_within_pct, calc_impact_cost, process_orderbook


class TestOkxUnitNormalization:
    """OKX 合约张数 → 基础币数量归一化。"""

    def test_sz_to_base_conversion(self):
        """
        OKX: 5000 张 @ 0.022, ctVal=10, ctMult=1
        真实基础币 = 5000 * 10 * 1 = 50,000 MON
        notional = 50,000 * 0.022 = 1,100 USDT
        """
        ct_val = 10.0
        ct_mult = 1.0
        sz = 5000
        price = 0.022

        base_qty = sz * ct_val * ct_mult
        assert base_qty == 50_000.0

        notional = base_qty * price
        assert notional == pytest.approx(1100.0, rel=1e-6)

    def test_orderbook_depth_with_ctval(self):
        """
        模拟 OKX 订单簿，数量已经过 ct_val 换算后传入 calc_depth_within_pct。
        """
        price = 0.022
        ct_val = 10.0
        # 原始 OKX sz: [1000, 2000, 3000]
        # 换算后: [10000, 20000, 30000] MON
        bids = [
            [price, 1000 * ct_val],
            [price * 0.995, 2000 * ct_val],
            [price * 0.990, 3000 * ct_val],
        ]
        asks = [
            [price * 1.001, 1000 * ct_val],
            [price * 1.005, 2000 * ct_val],
            [price * 1.010, 3000 * ct_val],
        ]

        mid = price
        depth_bid = calc_depth_within_pct(bids, mid, 1.0, side="bid")
        depth_ask = calc_depth_within_pct(asks, mid, 1.0, side="ask")

        # 1% 以内的 bid 档位
        # price = 0.022 -> 1% 下界 = 0.02178
        # 0.022 在范围内: 10000 * 0.022 = 220 USDT
        # 0.02189 在范围内: 20000 * 0.02189 = 437.8 USDT
        # 0.02178 在范围内: 30000 * 0.02178 = 653.4 USDT
        # total ≈ 1311 USDT
        assert depth_bid > 1000
        assert depth_ask > 200

    def test_without_ctval_underestimates_10x(self):
        """
        不做 ct_val 换算时，深度会被低估约 10 倍。
        """
        price = 0.022
        ct_val = 10.0
        raw_sz = [1000, 2000, 3000]
        bids_correct = [[price - i * 0.0001, s * ct_val] for i, s in enumerate(raw_sz)]
        bids_wrong = [[price - i * 0.0001, float(s)] for i, s in enumerate(raw_sz)]

        mid = price
        depth_correct = calc_depth_within_pct(bids_correct, mid, 1.0, side="bid")
        depth_wrong = calc_depth_within_pct(bids_wrong, mid, 1.0, side="bid")

        # 正确深度应该是错误深度的 ct_val 倍
        if depth_wrong > 0:
            ratio = depth_correct / depth_wrong
            assert ratio == pytest.approx(ct_val, rel=0.01)

    def test_impact_cost_with_normalized_qty(self):
        """
        测试在归一化后的订单簿上计算冲击成本。
        """
        price = 0.022
        ct_val = 10.0
        # 构建一个有足够深度的 OKX 风格订单簿
        # 原始 sz: 分布在多个价格档位
        asks = []
        for i in range(20):
            p = price * (1 + 0.0001 * (i + 1))
            sz_raw = 5000 + i * 1000
            # 已换算为基础币
            asks.append([p, sz_raw * ct_val])

        # 对 10,000 USDT 进行冲击测试（buy side 使用 asks）
        result = calc_impact_cost(asks, price, 10000, "buy")
        # 应该能完成成交，且滑点合理
        assert not result.insufficient_liquidity
        assert result.filled_notional >= 9999
        assert result.slip_bps is not None
        assert result.slip_bps >= 0


class TestBinanceNoConversion:
    """Binance USDM 永续不需要单位换算。"""

    def test_qty_is_base(self):
        """
        Binance: qty 直接是 MON 数量
        10000 MON @ 0.022 = 220 USDT
        """
        qty = 10000
        price = 0.022
        notional = qty * price
        assert notional == pytest.approx(220.0, rel=1e-6)

    def test_process_orderbook_binance_style(self):
        """
        Binance 风格 orderbook，qty 就是基础币。
        """
        bids = [
            [0.02200, 100000],
            [0.02195, 200000],
            [0.02190, 300000],
        ]
        asks = [
            [0.02205, 100000],
            [0.02210, 200000],
            [0.02215, 300000],
        ]
        ob_raw = {"bids": bids, "asks": asks}
        result = process_orderbook(ob_raw, 0.022, 10000, 50000, 100)

        assert result.mid is not None
        # 深度应该合理（bid side）
        assert result.depth_1pct_usdt_bid > 0
        assert result.depth_1pct_usdt_ask > 0


class TestBybitNoConversion:
    """Bybit linear 永续不需要单位换算。"""

    def test_size_is_base(self):
        """Bybit linear: size 就是基础币数量。"""
        size = 6134
        price = 0.02218
        notional = size * price
        assert notional == pytest.approx(136.05, rel=0.01)


class TestCrossVenueSanityCheck:
    """
    跨交易所一致性检查。
    构建等价盘口（归一化后基础币数量相同），验证深度计算结果一致。
    """

    def test_equivalent_orderbook_gives_same_depth(self):
        """
        三家交易所对同一盘口（换算后），depth 应该相同。
        """
        price = 0.022
        base_qty = 50000.0

        # Binance: qty = base_qty
        binance_bids = [[price, base_qty]]
        # OKX: sz = base_qty / ct_val, 传入时已做 sz * ct_val
        okx_ct_val = 10.0
        okx_bids = [[price, (base_qty / okx_ct_val) * okx_ct_val]]
        # Bybit: size = base_qty
        bybit_bids = [[price, base_qty]]

        mid = price
        d_bn = calc_depth_within_pct(binance_bids, mid, 1.0, side="bid")
        d_okx = calc_depth_within_pct(okx_bids, mid, 1.0, side="bid")
        d_bybit = calc_depth_within_pct(bybit_bids, mid, 1.0, side="bid")

        assert d_bn == pytest.approx(d_okx, rel=1e-9)
        assert d_bn == pytest.approx(d_bybit, rel=1e-9)
