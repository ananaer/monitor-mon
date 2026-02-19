"""
数据采集模块。
直接调用 Binance / OKX / Bybit 永续合约公开 REST API 采集市场数据。
零密钥运行，不含任何交易能力。

单位归一化说明：
- Binance USDM perp: 订单簿 qty = 基础币数量 (MON)，无需换算
- OKX SWAP: 订单簿 sz = 合约张数，真实数量 = sz * ctVal * ctMult
  需要先拉 instrument 元数据获取 ctVal/ctMult
- Bybit linear: 订单簿 size = 基础币数量 (MON)，无需换算
"""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
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
OKX_BASE_URL_FALLBACKS = [
    "https://app.okx.com",
    "https://my.okx.com",
    "https://www.okx.com",
]

ERR_UNSUPPORTED_VENUE = "unsupported_venue"
ERR_VERIFY_FAILED = "verify_failed"
ERR_SYMBOL_NOT_FOUND = "symbol_not_found"
ERR_NETWORK_ERROR = "network_error"
ERR_VENUE_TIMEOUT = "venue_timeout"
ERR_TICKER_FAILED = "ticker_failed"
ERR_ORDERBOOK_FAILED = "orderbook_failed"
ERR_FUNDING_FAILED = "funding_failed"
ERR_OI_FAILED = "open_interest_failed"
ERR_OHLCV_FAILED = "ohlcv_failed"
ERR_MARKET_DATA_UNAVAILABLE = "market_data_unavailable"


def _append_error(snapshot: VenueSnapshot, code: str, detail: str) -> None:
    msg = f"{code}: {detail}"
    snapshot.errors.append(msg)
    snapshot.raw_json.setdefault("error_details", []).append(
        {"code": code, "detail": detail}
    )


def _verify_reason_to_error_code(reason: str) -> str:
    lowered = (reason or "").lower()
    if "symbol_not_found" in lowered:
        return ERR_SYMBOL_NOT_FOUND
    if "network_error" in lowered or "timeout" in lowered:
        return ERR_NETWORK_ERROR
    return ERR_VERIFY_FAILED


def _get(
    session: requests.Session,
    url: str,
    params: Optional[dict] = None,
) -> dict:
    """
    带重试的 GET 请求。
    对网络超时、5xx、429 限频等可恢复错误进行指数退避重试。
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
#  订单簿 qty = 基础币数量 (MON)，无需换算
# ===================================================================

def _binance_verify(session: requests.Session, base: str, symbol: str) -> bool:
    try:
        data = _get(session, f"{base}/fapi/v1/ticker/price", {"symbol": symbol})
        return "price" in data
    except Exception:
        return False


def _binance_instrument(session: requests.Session, base: str, symbol: str) -> dict:
    """Binance 无需合约面值换算，返回 ct_val=1。"""
    return {"ct_val": 1.0, "venue": "binance"}


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


def _binance_orderbook(
    session: requests.Session,
    base: str,
    symbol: str,
    limit: int,
    ct_val: float,
) -> tuple[Optional[dict], Optional[dict]]:
    try:
        raw = _get(session, f"{base}/fapi/v1/depth", {"symbol": symbol, "limit": limit})
        # Binance: qty 已是基础币，ct_val=1
        bids = [[float(p), float(q) * ct_val] for p, q in raw.get("bids", [])]
        asks = [[float(p), float(q) * ct_val] for p, q in raw.get("asks", [])]
        ob = {"bids": bids, "asks": asks}
        summary = {"bids_count": len(bids), "asks_count": len(asks), "ct_val": ct_val}
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
#  订单簿 sz = 合约张数，真实基础币数量 = sz * ctVal * ctMult
# ===================================================================

def _okx_verify(session: requests.Session, base: str, symbol: str) -> tuple[bool, str]:
    try:
        data = _get(session, f"{base}/api/v5/public/instruments", {"instType": "SWAP", "instId": symbol})
        if data.get("data"):
            return True, "ok"
        return False, "symbol_not_found"
    except requests.exceptions.RequestException as e:
        return False, f"network_error:{type(e).__name__}"
    except Exception as e:
        return False, f"verify_error:{type(e).__name__}:{str(e)[:120]}"


def _okx_candidate_base_urls(base_url: str) -> list[str]:
    """
    构造 OKX API 域名候选列表。
    优先 app 路线，同时兼容配置域名与官方备用域名。
    """
    candidates = ["https://app.okx.com"]
    if base_url:
        candidates.append(base_url.rstrip("/"))
    candidates.extend(OKX_BASE_URL_FALLBACKS)
    uniq: list[str] = []
    seen = set()
    for item in candidates:
        if item not in seen:
            uniq.append(item)
            seen.add(item)
    return uniq


def _okx_resolve_base_url(
    session: requests.Session,
    base_url: str,
    symbol: str,
) -> tuple[Optional[str], list[dict], str]:
    attempts = []
    final_reason = "network_error"
    for candidate in _okx_candidate_base_urls(base_url):
        ok, reason = _okx_verify(session, candidate, symbol)
        attempts.append({"base_url": candidate, "verify_status": reason})
        if ok:
            return candidate, attempts, "ok"
        final_reason = reason
    return None, attempts, final_reason


def _okx_instrument(session: requests.Session, base: str, symbol: str) -> dict:
    """
    拉取 OKX instrument 元数据，提取 ctVal 和 ctMult。
    ct_val = ctVal * ctMult（每张合约对应的基础币数量）
    """
    try:
        raw = _get(session, f"{base}/api/v5/public/instruments", {"instType": "SWAP", "instId": symbol})
        d = raw["data"][0]
        ct_val = float(d["ctVal"]) * float(d["ctMult"])
        logger.info(
            "okx instrument: ctVal=%s, ctMult=%s, ctValCcy=%s => ct_val=%.4f",
            d["ctVal"], d["ctMult"], d["ctValCcy"], ct_val,
        )
        return {
            "ct_val": ct_val,
            "ct_val_raw": d["ctVal"],
            "ct_mult": d["ctMult"],
            "ct_val_ccy": d["ctValCcy"],
            "venue": "okx",
        }
    except Exception as e:
        logger.error("okx instrument 拉取失败: %s，默认 ct_val=1", e)
        return {"ct_val": 1.0, "venue": "okx"}


def _okx_ticker(session: requests.Session, base: str, symbol: str) -> tuple[Optional[TickerData], Optional[dict]]:
    try:
        raw = _get(session, f"{base}/api/v5/market/ticker", {"instId": symbol})
        d = raw["data"][0]
        last = float(d["last"])
        vol24h = float(d["volCcy24h"]) if d.get("volCcy24h") else None
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


def _okx_orderbook(
    session: requests.Session,
    base: str,
    symbol: str,
    limit: int,
    ct_val: float,
) -> tuple[Optional[dict], Optional[dict]]:
    """
    OKX 订单簿：sz 是合约张数，乘以 ct_val 得到基础币数量。
    """
    try:
        sz = min(limit, 400)
        raw = _get(session, f"{base}/api/v5/market/books", {"instId": symbol, "sz": sz})
        book = raw["data"][0]
        # 关键：sz * ct_val = 真实基础币数量
        bids = [[float(b[0]), float(b[1]) * ct_val] for b in book.get("bids", [])]
        asks = [[float(a[0]), float(a[1]) * ct_val] for a in book.get("asks", [])]
        ob = {"bids": bids, "asks": asks}
        summary = {"bids_count": len(bids), "asks_count": len(asks), "ct_val": ct_val}
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
#  订单簿 size = 基础币数量 (MON)，无需换算
# ===================================================================

def _bybit_verify(session: requests.Session, base: str, symbol: str) -> bool:
    try:
        data = _get(session, f"{base}/v5/market/instruments-info", {"category": "linear", "symbol": symbol})
        return bool(data.get("result", {}).get("list"))
    except Exception:
        return False


def _bybit_instrument(session: requests.Session, base: str, symbol: str) -> dict:
    """Bybit linear perp: size = 基础币数量，ct_val=1。"""
    return {"ct_val": 1.0, "venue": "bybit"}


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


def _bybit_orderbook(
    session: requests.Session,
    base: str,
    symbol: str,
    limit: int,
    ct_val: float,
) -> tuple[Optional[dict], Optional[dict]]:
    try:
        lim = min(limit, 200)
        raw = _get(session, f"{base}/v5/market/orderbook", {"category": "linear", "symbol": symbol, "limit": lim})
        result = raw["result"]
        # Bybit: size 已是基础币，ct_val=1
        bids = [[float(b[0]), float(b[1]) * ct_val] for b in result.get("b", [])]
        asks = [[float(a[0]), float(a[1]) * ct_val] for a in result.get("a", [])]
        ob = {"bids": bids, "asks": asks}
        summary = {"bids_count": len(bids), "asks_count": len(asks), "ct_val": ct_val}
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
        "instrument": _binance_instrument,
        "ticker": _binance_ticker,
        "orderbook": _binance_orderbook,
        "funding": _binance_funding,
        "oi": _binance_oi,
        "klines": _binance_klines,
    },
    "okx": {
        "verify": _okx_verify,
        "instrument": _okx_instrument,
        "ticker": _okx_ticker,
        "orderbook": _okx_orderbook,
        "funding": _okx_funding,
        "oi": _okx_oi,
        "klines": _okx_klines,
    },
    "bybit": {
        "verify": _bybit_verify,
        "instrument": _bybit_instrument,
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
    started_at = time.perf_counter()

    handlers = VENUE_HANDLERS.get(venue_name)
    if not handlers:
        _append_error(snapshot, ERR_UNSUPPORTED_VENUE, venue_name)
        snapshot.missing_market = True
        return snapshot

    session = requests.Session()
    session.headers["User-Agent"] = "MON-Monitor/1.0"
    base = venue_config.base_url
    symbol = venue_config.symbol

    # 验证 symbol 存在性，并解析 OKX 可用域名
    if venue_name == "okx":
        resolved_base, attempts, verify_reason = _okx_resolve_base_url(
            session=session,
            base_url=base,
            symbol=symbol,
        )
        snapshot.raw_json["attempted_base_urls"] = attempts
        if resolved_base:
            base = resolved_base
            snapshot.raw_json["resolved_base_url"] = resolved_base
        else:
            logger.warning(
                "okx verify 失败 (symbol=%s): %s",
                symbol,
                verify_reason,
            )
            _append_error(
                snapshot,
                _verify_reason_to_error_code(verify_reason),
                f"okx verify failed ({verify_reason})",
            )
            snapshot.missing_market = True
            session.close()
            snapshot.raw_json["collect_latency_ms"] = int(
                (time.perf_counter() - started_at) * 1000
            )
            return snapshot
    else:
        try:
            verify_result = handlers["verify"](session, base, symbol)
            ok = bool(verify_result)
            reason = "symbol_not_found"
            if isinstance(verify_result, tuple):
                ok = bool(verify_result[0])
                reason = str(verify_result[1])
            if not ok:
                logger.warning("%s 不支持 symbol %s，标记为 missing_market", venue_name, symbol)
                _append_error(
                    snapshot,
                    _verify_reason_to_error_code(reason),
                    f"{venue_name} verify failed ({reason})",
                )
                snapshot.missing_market = True
                session.close()
                snapshot.raw_json["collect_latency_ms"] = int(
                    (time.perf_counter() - started_at) * 1000
                )
                return snapshot
        except Exception as e:
            _append_error(snapshot, ERR_VERIFY_FAILED, f"{venue_name} verify exception: {e}")
            snapshot.missing_market = True
            session.close()
            snapshot.raw_json["collect_latency_ms"] = int(
                (time.perf_counter() - started_at) * 1000
            )
            return snapshot

    # 拉取 instrument 元数据（获取合约面值 ct_val）
    inst = handlers["instrument"](session, base, symbol)
    ct_val = inst.get("ct_val", 1.0)
    snapshot.raw_json["instrument"] = inst

    # Ticker
    ticker, ticker_raw = handlers["ticker"](session, base, symbol)
    snapshot.ticker = ticker
    if ticker_raw:
        snapshot.raw_json["ticker"] = ticker_raw
    else:
        _append_error(snapshot, ERR_TICKER_FAILED, f"{venue_name} ticker request failed")

    # OrderBook（传入 ct_val 做单位归一化）
    ob_raw, ob_summary = handlers["orderbook"](session, base, symbol, config.orderbook_levels, ct_val)
    if ob_raw:
        snapshot.raw_json["orderbook_summary"] = ob_summary
        snapshot.raw_json["orderbook_raw"] = ob_raw
    else:
        _append_error(snapshot, ERR_ORDERBOOK_FAILED, f"{venue_name} orderbook request failed")

    # Funding
    funding, funding_raw = handlers["funding"](session, base, symbol)
    snapshot.funding = funding
    if funding_raw:
        snapshot.raw_json["funding"] = funding_raw
    else:
        _append_error(snapshot, ERR_FUNDING_FAILED, f"{venue_name} funding request failed")

    # Open Interest
    oi, oi_raw = handlers["oi"](session, base, symbol)
    snapshot.open_interest = oi
    if oi_raw:
        snapshot.raw_json["open_interest"] = oi_raw
    else:
        _append_error(snapshot, ERR_OI_FAILED, f"{venue_name} open interest request failed")

    # OHLCV
    ohlcv_candles, ohlcv_summary = handlers["klines"](session, base, symbol, 200)
    if ohlcv_candles:
        snapshot.raw_json["ohlcv_summary"] = ohlcv_summary
        snapshot.raw_json["ohlcv_candles"] = ohlcv_candles
    else:
        _append_error(snapshot, ERR_OHLCV_FAILED, f"{venue_name} ohlcv request failed")

    if snapshot.ticker is None and ob_raw is None:
        snapshot.missing_market = True
        _append_error(
            snapshot,
            ERR_MARKET_DATA_UNAVAILABLE,
            f"{venue_name} ticker+orderbook both unavailable",
        )

    session.close()
    snapshot.raw_json["collect_latency_ms"] = int((time.perf_counter() - started_at) * 1000)
    return snapshot


def collect_all(config: MonitorConfig) -> dict[str, VenueSnapshot]:
    """
    对所有配置的交易所执行采集。
    单个交易所失败不影响其他交易所。
    """
    results: dict[str, VenueSnapshot] = {}
    venue_items = list(config.venues.items())
    if not venue_items:
        return results

    workers = max(1, min(config.collect_workers, len(venue_items)))
    logger.info("开始并发采集: venues=%d workers=%d", len(venue_items), workers)

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="collector") as executor:
        future_map = {
            venue_name: executor.submit(collect_venue, config, venue_name, venue_config)
            for venue_name, venue_config in venue_items
        }
        for venue_name, venue_config in venue_items:
            future = future_map[venue_name]
            try:
                snapshot = future.result(timeout=config.venue_timeout_seconds)
                results[venue_name] = snapshot
                if snapshot.missing_market:
                    logger.warning(
                        "%s: missing_market (symbol=%s, errors=%s)",
                        venue_name,
                        venue_config.symbol,
                        snapshot.errors[:2],
                    )
                else:
                    logger.info("%s: 采集完成", venue_name)
            except TimeoutError:
                logger.error(
                    "%s: 采集超时（>%ss）",
                    venue_name,
                    config.venue_timeout_seconds,
                )
                timeout_snapshot = VenueSnapshot(
                    venue=venue_name,
                    symbol=venue_config.symbol,
                    ts_utc=datetime.now(timezone.utc).isoformat(),
                    missing_market=True,
                )
                _append_error(
                    timeout_snapshot,
                    ERR_VENUE_TIMEOUT,
                    f"collect timeout after {config.venue_timeout_seconds}s",
                )
                timeout_snapshot.raw_json["collect_timeout_seconds"] = config.venue_timeout_seconds
                results[venue_name] = timeout_snapshot
            except Exception as e:
                logger.error("%s: 采集异常: %s", venue_name, e)
                crash_snapshot = VenueSnapshot(
                    venue=venue_name,
                    symbol=venue_config.symbol,
                    ts_utc=datetime.now(timezone.utc).isoformat(),
                    missing_market=True,
                )
                _append_error(crash_snapshot, ERR_NETWORK_ERROR, str(e))
                results[venue_name] = crash_snapshot
    return results
