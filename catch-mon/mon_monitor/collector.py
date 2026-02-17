"""
数据采集模块。
直接调用 Binance / OKX / Bybit 永续合约公开 REST API 采集市场数据。
零密钥运行，不含任何交易能力。
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from mon_monitor.config import MonitorConfig, VenueConfig
from mon_monitor.models import (
    FundingData,
    OpenInterestData,
    TickerData,
    VenueSnapshot,
)

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BASE_SECONDS = 1.0
REQUEST_TIMEOUT = 15


def _get(
    session: requests.Session,
    url: str,
    params: Optional[dict] = None,
) -> dict:
    """
    带重试的 GET 请求。
    对网络超时、5xx 等可恢复错误进行指数退避重试。
    """
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 429:
                wait = RETRY_BASE_SECONDS * (2 ** attempt)
                logger.warning("限频 429，等待 %.1f 秒重试", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
        ) as e:
            last_error = e
            wait = RETRY_BASE_SECONDS * (2 ** attempt)
            logger.warning(
                "第 %d/%d 次请求失败 (%s): %s，等待 %.1f 秒",
                attempt + 1,
                MAX_RETRIES,
                type(e).__name__,
                str(e)[:120],
                wait,
            )
            time.sleep(wait)
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code >= 500:
                last_error = e
                wait = RETRY_BASE_SECONDS * (2 ** attempt)
                logger.warning("服务端 %d 错误，等待 %.1f 秒重试", e.response.status_code, wait)
                time.sleep(wait)
            else:
                raise
    raise last_error


# ===================================================================
#  Binance USDM 永续合约
# ===================================================================

def _binance_verify(session: requests.Session, base: str, symbol: str) -> bool:
    """验证 Binance 永续合约 symbol 是否存在。"""
    try:
        data = _get(session, f"{base}/fapi/v1/ticker/price", {"symbol": symbol})
        return "price" in data
    except Exception:
        return False


def _binance_ticker(session: requests.Session, base: str, symbol: str) -> tuple[Optional[TickerData], Optional[dict]]:
    try:
        raw = _get(session, f"{base}/fapi/v1/ticker/24hr", {"symbol": symbol})
        data = TickerData(
            last_price=float(raw["lastPrice"]),
            quote_volume_24h=float(raw["quoteVolume"]),
            pct_change_24h=float(raw["priceChangePercent"]),
        )
        return data, raw
    except Exception as e:
        logger.error("binance ticker 失败: %s", e)
        return None, None


def _binance_orderbook(session: requests.Session, base: str, symbol: str, limit: int) -> tuple[Optional[dict], Optional[dict]]:
    try:
        raw = _get(session, f"{base}/fapi/v1/depth", {"symbol": symbol, "limit": limit})
        bids = [[float(p), float(q)] for p, q in raw.get("bids", [])]
        asks = [[float(p), float(q)] for p, q in raw.get("asks", [])]
        ob = {"bids": bids, "asks": asks}
        summary = {"bids_count": len(bids), "asks_count": len(asks)}
        return ob, summary
    except Exception as e:
        logger.error("binance orderbook 失败: %s", e)
        return None, None


def _binance_funding(session: requests.Session, base: str, symbol: str) -> tuple[Optional[FundingData], Optional[dict]]:
    try:
        raw = _get(session, f"{base}/fapi/v1/premiumIndex", {"symbol": symbol})
        data = FundingData(
            funding_rate=float(raw["lastFundingRate"]),
            funding_time=datetime.fromtimestamp(
                int(raw["nextFundingTime"]) / 1000, tz=timezone.utc
            ).isoformat(),
        )
        return data, raw
    except Exception as e:
        logger.error("binance funding 失败: %s", e)
        return None, None


def _binance_oi(session: requests.Session, base: str, symbol: str) -> tuple[Optional[OpenInterestData], Optional[dict]]:
    try:
        raw = _get(session, f"{base}/fapi/v1/openInterest", {"symbol": symbol})
        contracts = float(raw["openInterest"])
        data = OpenInterestData(
            open_interest_amount_contracts=contracts,
            raw_json=raw,
        )
        return data, raw
    except Exception as e:
        logger.error("binance OI 失败: %s", e)
        return None, None


def _binance_klines(session: requests.Session, base: str, symbol: str, limit: int) -> tuple[Optional[list], Optional[dict]]:
    try:
        raw = _get(session, f"{base}/fapi/v1/klines", {"symbol": symbol, "interval": "1h", "limit": limit})
        # Binance kline: [openTime, open, high, low, close, volume, ...]
        candles = [
            [int(c[0]), float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5])]
            for c in raw
        ]
        summary = {"timeframe": "1h", "candle_count": len(candles)}
        return candles, summary
    except Exception as e:
        logger.error("binance klines 失败: %s", e)
        return None, None


# ===================================================================
#  OKX 永续合约 (SWAP)
# ===================================================================

def _okx_verify(session: requests.Session, base: str, symbol: str) -> bool:
    try:
        data = _get(session, f"{base}/api/v5/public/instruments", {"instType": "SWAP", "instId": symbol})
        return bool(data.get("data"))
    except Exception:
        return False


def _okx_ticker(session: requests.Session, base: str, symbol: str) -> tuple[Optional[TickerData], Optional[dict]]:
    try:
        raw = _get(session, f"{base}/api/v5/market/ticker", {"instId": symbol})
        d = raw["data"][0]
        last = float(d["last"])
        vol24h = float(d["volCcy24h"]) if d.get("volCcy24h") else None
        # OKX 不直接提供 pct_change_24h，从 open24h 计算
        pct_24h = None
        if d.get("open24h") and float(d["open24h"]) > 0:
            pct_24h = (last - float(d["open24h"])) / float(d["open24h"]) * 100
        data = TickerData(
            last_price=last,
            quote_volume_24h=vol24h,
            pct_change_24h=pct_24h,
        )
        return data, d
    except Exception as e:
        logger.error("okx ticker 失败: %s", e)
        return None, None


def _okx_orderbook(session: requests.Session, base: str, symbol: str, limit: int) -> tuple[Optional[dict], Optional[dict]]:
    try:
        # OKX books 最大 400 档
        sz = min(limit, 400)
        raw = _get(session, f"{base}/api/v5/market/books", {"instId": symbol, "sz": sz})
        book = raw["data"][0]
        # OKX 格式: [[price, qty, liquidated_orders, num_orders], ...]
        bids = [[float(b[0]), float(b[1])] for b in book.get("bids", [])]
        asks = [[float(a[0]), float(a[1])] for a in book.get("asks", [])]
        ob = {"bids": bids, "asks": asks}
        summary = {"bids_count": len(bids), "asks_count": len(asks)}
        return ob, summary
    except Exception as e:
        logger.error("okx orderbook 失败: %s", e)
        return None, None


def _okx_funding(session: requests.Session, base: str, symbol: str) -> tuple[Optional[FundingData], Optional[dict]]:
    try:
        raw = _get(session, f"{base}/api/v5/public/funding-rate", {"instId": symbol})
        d = raw["data"][0]
        data = FundingData(
            funding_rate=float(d["fundingRate"]),
            funding_time=datetime.fromtimestamp(
                int(d["fundingTime"]) / 1000, tz=timezone.utc
            ).isoformat(),
        )
        return data, d
    except Exception as e:
        logger.error("okx funding 失败: %s", e)
        return None, None


def _okx_oi(session: requests.Session, base: str, symbol: str) -> tuple[Optional[OpenInterestData], Optional[dict]]:
    try:
        raw = _get(session, f"{base}/api/v5/public/open-interest", {"instType": "SWAP", "instId": symbol})
        d = raw["data"][0]
        oi_usd = float(d["oiUsd"]) if d.get("oiUsd") else None
        oi_contracts = float(d["oi"]) if d.get("oi") else None
        data = OpenInterestData(
            open_interest_value_usdt=oi_usd,
            open_interest_amount_contracts=oi_contracts,
            raw_json=d,
        )
        return data, d
    except Exception as e:
        logger.error("okx OI 失败: %s", e)
        return None, None


def _okx_klines(session: requests.Session, base: str, symbol: str, limit: int) -> tuple[Optional[list], Optional[dict]]:
    try:
        raw = _get(session, f"{base}/api/v5/market/candles", {"instId": symbol, "bar": "1H", "limit": limit})
        # OKX 格式: [ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm]
        # 按时间升序排列（OKX 返回降序，需反转）
        candles = [
            [int(c[0]), float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5])]
            for c in reversed(raw["data"])
        ]
        summary = {"timeframe": "1h", "candle_count": len(candles)}
        return candles, summary
    except Exception as e:
        logger.error("okx klines 失败: %s", e)
        return None, None


# ===================================================================
#  Bybit 永续合约 (linear)
# ===================================================================

def _bybit_verify(session: requests.Session, base: str, symbol: str) -> bool:
    try:
        data = _get(session, f"{base}/v5/market/instruments-info", {"category": "linear", "symbol": symbol})
        return bool(data.get("result", {}).get("list"))
    except Exception:
        return False


def _bybit_ticker(session: requests.Session, base: str, symbol: str) -> tuple[Optional[TickerData], Optional[dict]]:
    try:
        raw = _get(session, f"{base}/v5/market/tickers", {"category": "linear", "symbol": symbol})
        d = raw["result"]["list"][0]
        pct_24h = float(d["price24hPcnt"]) * 100 if d.get("price24hPcnt") else None
        data = TickerData(
            last_price=float(d["lastPrice"]),
            quote_volume_24h=float(d["turnover24h"]) if d.get("turnover24h") else None,
            pct_change_24h=pct_24h,
        )
        return data, d
    except Exception as e:
        logger.error("bybit ticker 失败: %s", e)
        return None, None


def _bybit_orderbook(session: requests.Session, base: str, symbol: str, limit: int) -> tuple[Optional[dict], Optional[dict]]:
    try:
        # Bybit orderbook 最大 200 档
        lim = min(limit, 200)
        raw = _get(session, f"{base}/v5/market/orderbook", {"category": "linear", "symbol": symbol, "limit": lim})
        result = raw["result"]
        # Bybit 格式: {"b": [["price","qty"], ...], "a": [...]}
        bids = [[float(b[0]), float(b[1])] for b in result.get("b", [])]
        asks = [[float(a[0]), float(a[1])] for a in result.get("a", [])]
        ob = {"bids": bids, "asks": asks}
        summary = {"bids_count": len(bids), "asks_count": len(asks)}
        return ob, summary
    except Exception as e:
        logger.error("bybit orderbook 失败: %s", e)
        return None, None


def _bybit_funding(session: requests.Session, base: str, symbol: str) -> tuple[Optional[FundingData], Optional[dict]]:
    try:
        raw = _get(session, f"{base}/v5/market/funding/history", {"category": "linear", "symbol": symbol, "limit": 1})
        items = raw["result"]["list"]
        if not items:
            return None, None
        d = items[0]
        data = FundingData(
            funding_rate=float(d["fundingRate"]),
            funding_time=datetime.fromtimestamp(
                int(d["fundingRateTimestamp"]) / 1000, tz=timezone.utc
            ).isoformat(),
        )
        return data, d
    except Exception as e:
        logger.error("bybit funding 失败: %s", e)
        return None, None


def _bybit_oi(session: requests.Session, base: str, symbol: str) -> tuple[Optional[OpenInterestData], Optional[dict]]:
    try:
        raw = _get(session, f"{base}/v5/market/open-interest", {
            "category": "linear",
            "symbol": symbol,
            "intervalTime": "5min",
            "limit": 1,
        })
        items = raw["result"]["list"]
        if not items:
            return None, None
        d = items[0]
        contracts = float(d["openInterest"])
        data = OpenInterestData(
            open_interest_amount_contracts=contracts,
            raw_json=d,
        )
        return data, d
    except Exception as e:
        logger.error("bybit OI 失败: %s", e)
        return None, None


def _bybit_klines(session: requests.Session, base: str, symbol: str, limit: int) -> tuple[Optional[list], Optional[dict]]:
    try:
        raw = _get(session, f"{base}/v5/market/kline", {
            "category": "linear",
            "symbol": symbol,
            "interval": "60",
            "limit": limit,
        })
        # Bybit kline: [startTime, open, high, low, close, volume, turnover]
        # 返回降序，需反转
        candles = [
            [int(c[0]), float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5])]
            for c in reversed(raw["result"]["list"])
        ]
        summary = {"timeframe": "1h", "candle_count": len(candles)}
        return candles, summary
    except Exception as e:
        logger.error("bybit klines 失败: %s", e)
        return None, None


# ===================================================================
#  Venue 调度表
# ===================================================================

VENUE_HANDLERS = {
    "binance": {
        "verify": _binance_verify,
        "ticker": _binance_ticker,
        "orderbook": _binance_orderbook,
        "funding": _binance_funding,
        "oi": _binance_oi,
        "klines": _binance_klines,
    },
    "okx": {
        "verify": _okx_verify,
        "ticker": _okx_ticker,
        "orderbook": _okx_orderbook,
        "funding": _okx_funding,
        "oi": _okx_oi,
        "klines": _okx_klines,
    },
    "bybit": {
        "verify": _bybit_verify,
        "ticker": _bybit_ticker,
        "orderbook": _bybit_orderbook,
        "funding": _bybit_funding,
        "oi": _bybit_oi,
        "klines": _bybit_klines,
    },
}


def collect_venue(
    config: MonitorConfig,
    venue_name: str,
    venue_config: VenueConfig,
) -> VenueSnapshot:
    """
    对单个交易所执行完整的数据采集。
    任一子模块失败不影响其他模块，失败部分标记为 missing。
    """
    ts_utc = datetime.now(timezone.utc).isoformat()
    snapshot = VenueSnapshot(
        venue=venue_name,
        symbol=venue_config.symbol,
        ts_utc=ts_utc,
    )

    handlers = VENUE_HANDLERS.get(venue_name)
    if not handlers:
        snapshot.errors.append(f"不支持的 venue: {venue_name}")
        snapshot.missing_market = True
        return snapshot

    session = requests.Session()
    session.headers["User-Agent"] = "MON-Monitor/1.0"
    base = venue_config.base_url
    symbol = venue_config.symbol

    # 验证 symbol 存在性
    try:
        if not handlers["verify"](session, base, symbol):
            logger.warning("%s 不支持 symbol %s，标记为 missing_market", venue_name, symbol)
            snapshot.missing_market = True
            return snapshot
    except Exception as e:
        snapshot.errors.append(f"验证 symbol 失败: {e}")
        snapshot.missing_market = True
        return snapshot

    # Ticker
    ticker, ticker_raw = handlers["ticker"](session, base, symbol)
    snapshot.ticker = ticker
    if ticker_raw:
        snapshot.raw_json["ticker"] = ticker_raw

    # OrderBook
    ob_raw, ob_summary = handlers["orderbook"](session, base, symbol, config.orderbook_levels)
    if ob_raw:
        snapshot.raw_json["orderbook_summary"] = ob_summary
        snapshot.raw_json["orderbook_raw"] = ob_raw
    else:
        snapshot.errors.append("订单簿采集失败")

    # Funding
    funding, funding_raw = handlers["funding"](session, base, symbol)
    snapshot.funding = funding
    if funding_raw:
        snapshot.raw_json["funding"] = funding_raw

    # Open Interest
    oi, oi_raw = handlers["oi"](session, base, symbol)
    snapshot.open_interest = oi
    if oi_raw:
        snapshot.raw_json["open_interest"] = oi_raw

    # OHLCV
    kline_limit = min(200, config.orderbook_levels * 2) if config.orderbook_levels else 200
    kline_limit = 200
    ohlcv_candles, ohlcv_summary = handlers["klines"](session, base, symbol, kline_limit)
    if ohlcv_candles:
        snapshot.raw_json["ohlcv_summary"] = ohlcv_summary
        snapshot.raw_json["ohlcv_candles"] = ohlcv_candles
    else:
        snapshot.errors.append("OHLCV 采集失败")

    session.close()
    return snapshot


def collect_all(config: MonitorConfig) -> dict[str, VenueSnapshot]:
    """
    对所有配置的交易所执行采集。
    单个交易所失败不影响其他交易所。
    """
    results = {}
    for venue_name, venue_config in config.venues.items():
        logger.info("开始采集 %s ...", venue_name)
        try:
            snapshot = collect_venue(config, venue_name, venue_config)
            results[venue_name] = snapshot
            if snapshot.missing_market:
                logger.warning(
                    "%s: missing_market (symbol=%s)",
                    venue_name,
                    venue_config.symbol,
                )
            else:
                logger.info("%s: 采集完成", venue_name)
        except Exception as e:
            logger.error("%s: 采集异常: %s", venue_name, e)
            results[venue_name] = VenueSnapshot(
                venue=venue_name,
                symbol=venue_config.symbol,
                ts_utc=datetime.now(timezone.utc).isoformat(),
                missing_market=True,
                errors=[str(e)],
            )
    return results
