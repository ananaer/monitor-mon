"""
数据模型定义。
所有采集、计算、告警相关的数据结构。
"""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class TickerData:
    last_price: Optional[float] = None
    quote_volume_24h: Optional[float] = None
    pct_change_1h: Optional[float] = None
    pct_change_24h: Optional[float] = None


@dataclass
class ImpactCostResult:
    """吃单滑点估算结果"""
    avg_fill_price: Optional[float] = None
    slip_bps: Optional[float] = None
    filled_notional: float = 0.0
    target_notional: float = 0.0
    insufficient_liquidity: bool = False
    shortfall: float = 0.0


@dataclass
class OrderBookData:
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    mid: Optional[float] = None
    spread_bps: Optional[float] = None
    depth_1pct_usdt_bid: Optional[float] = None
    depth_1pct_usdt_ask: Optional[float] = None
    depth_2pct_usdt_bid: Optional[float] = None
    depth_2pct_usdt_ask: Optional[float] = None
    # 冲击成本 notional_1
    impact_buy_n1: Optional[ImpactCostResult] = None
    impact_sell_n1: Optional[ImpactCostResult] = None
    # 冲击成本 notional_2
    impact_buy_n2: Optional[ImpactCostResult] = None
    impact_sell_n2: Optional[ImpactCostResult] = None
    # 原始订单簿数据（前 N 档）
    orderbook_levels_raw: Optional[dict] = None


@dataclass
class FundingData:
    funding_rate: Optional[float] = None
    funding_time: Optional[str] = None


@dataclass
class OpenInterestData:
    open_interest_value_usdt: Optional[float] = None
    open_interest_amount_contracts: Optional[float] = None
    raw_json: Optional[dict] = None


@dataclass
class OhlcvData:
    realized_vol_24h: Optional[float] = None
    atr_like_24h: Optional[float] = None
    candle_count: int = 0


@dataclass
class VenueSnapshot:
    """单个交易所的完整采样快照"""
    venue: str = ""
    symbol: str = ""
    ts_utc: str = ""
    missing_market: bool = False
    ticker: Optional[TickerData] = None
    orderbook: Optional[OrderBookData] = None
    funding: Optional[FundingData] = None
    open_interest: Optional[OpenInterestData] = None
    ohlcv: Optional[OhlcvData] = None
    raw_json: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class BaselineValues:
    """某个 venue 的基线统计值"""
    venue: str = ""
    symbol: str = ""
    ts_utc: str = ""
    depth_1pct_total_median: Optional[float] = None
    spread_bps_median: Optional[float] = None
    slip_bps_n2_median: Optional[float] = None
    volume_24h_mean_7d: Optional[float] = None
    sample_count: int = 0
    warming_up: bool = True


@dataclass
class Alert:
    """告警记录"""
    alert_type: str = ""
    venue: str = ""
    symbol: str = ""
    severity: str = "info"
    message: str = ""
    threshold_value: Optional[float] = None
    current_value: Optional[float] = None
    baseline_value: Optional[float] = None
    ts_utc: str = ""
    dedupe_key: str = ""


@dataclass
class MonitorOutput:
    """每轮监控的完整输出"""
    ts_utc: str = ""
    token: str = "MON"
    snapshots: dict[str, Any] = field(default_factory=dict)
    baselines: dict[str, Any] = field(default_factory=dict)
    alerts: list[Alert] = field(default_factory=list)
