"""
配置加载与验证模块。
从 YAML 文件读取配置并映射到 dataclass。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class VenueConfig:
    market: str
    symbol: str
    base_url: str = ""


@dataclass
class ThresholdsConfig:
    depth_drop_mult: float = 0.7
    spread_mult: float = 2.0
    slip_mult: float = 2.0
    volume_spike_mult: float = 2.0


@dataclass
class MonitorConfig:
    token_symbol: str = "MON"
    timezone: str = "Asia/Tokyo"
    schedule_seconds: int = 300
    baseline_days: int = 14
    orderbook_levels: int = 100
    notional_1: float = 10000.0
    notional_2: float = 100000.0
    venues: dict[str, VenueConfig] = field(default_factory=dict)
    thresholds: ThresholdsConfig = field(default_factory=ThresholdsConfig)
    dedupe_window_seconds: int = 3600


DEFAULT_BASE_URLS = {
    "binance": "https://fapi.binance.com",
    "okx": "https://www.okx.com",
    "bybit": "https://api.bytick.com",
}


def load_config(config_path: Optional[str] = None) -> MonitorConfig:
    """
    从 YAML 文件加载配置。
    如果未指定路径，使用项目根目录下的 config.yaml。
    """
    if config_path is None:
        config_path = str(Path(__file__).parent.parent / "config.yaml")

    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if raw is None:
        raise ValueError("配置文件为空")

    venues = {}
    for venue_name, venue_data in raw.get("venues", {}).items():
        default_url = DEFAULT_BASE_URLS.get(venue_name, "")
        venues[venue_name] = VenueConfig(
            market=venue_data["market"],
            symbol=venue_data["symbol"],
            base_url=venue_data.get("base_url", default_url),
        )

    thresholds_data = raw.get("thresholds", {})
    thresholds = ThresholdsConfig(
        depth_drop_mult=thresholds_data.get("depth_drop_mult", 0.7),
        spread_mult=thresholds_data.get("spread_mult", 2.0),
        slip_mult=thresholds_data.get("slip_mult", 2.0),
        volume_spike_mult=thresholds_data.get("volume_spike_mult", 2.0),
    )

    config = MonitorConfig(
        token_symbol=raw.get("token_symbol", "MON"),
        timezone=raw.get("timezone", "Asia/Tokyo"),
        schedule_seconds=raw.get("schedule_seconds", 300),
        baseline_days=raw.get("baseline_days", 14),
        orderbook_levels=raw.get("orderbook_levels", 100),
        notional_1=float(raw.get("notional_1", 10000)),
        notional_2=float(raw.get("notional_2", 100000)),
        venues=venues,
        thresholds=thresholds,
        dedupe_window_seconds=raw.get("dedupe_window_seconds", 3600),
    )

    _validate_config(config)
    return config


def _validate_config(config: MonitorConfig) -> None:
    """校验配置合法性。"""
    if not config.venues:
        raise ValueError("venues 配置不能为空，至少需要一个交易所")

    valid_markets = {"usdm_perp", "swap", "linear"}
    for name, venue in config.venues.items():
        if venue.market not in valid_markets:
            raise ValueError(
                f"venue '{name}' 的 market 类型 '{venue.market}' 不合法，"
                f"合法值: {valid_markets}"
            )
        if not venue.symbol:
            raise ValueError(f"venue '{name}' 的 symbol 不能为空")

    if config.schedule_seconds < 10:
        raise ValueError("schedule_seconds 不能小于 10 秒")

    if config.baseline_days < 1:
        raise ValueError("baseline_days 不能小于 1")

    if config.orderbook_levels < 1:
        raise ValueError("orderbook_levels 不能小于 1")
