import time

from mon_monitor.collector import _okx_resolve_base_url, collect_all, collect_venue
from mon_monitor.config import MonitorConfig, VenueConfig
from mon_monitor.models import VenueSnapshot


def test_okx_resolve_base_url_fallback(monkeypatch):
    def fake_verify(_session, base, _symbol):
        if base == "https://my.okx.com":
            return True, "ok"
        return False, "network_error:ConnectionError"

    monkeypatch.setattr("mon_monitor.collector._okx_verify", fake_verify)

    resolved, attempts, reason = _okx_resolve_base_url(
        session=None,
        base_url="https://www.okx.com",
        symbol="MON-USDT-SWAP",
    )

    assert attempts[0]["base_url"] == "https://app.okx.com"
    assert resolved == "https://my.okx.com"
    assert reason == "ok"


def test_collect_venue_marks_missing_when_all_okx_bases_fail(monkeypatch):
    def fake_verify(_session, _base, _symbol):
        return False, "network_error:ConnectionError"

    monkeypatch.setattr("mon_monitor.collector._okx_verify", fake_verify)

    config = MonitorConfig(
        token_symbol="MON",
        venues={
            "okx": VenueConfig(
                market="swap",
                symbol="MON-USDT-SWAP",
                base_url="https://www.okx.com",
            )
        },
    )
    snapshot = collect_venue(config, "okx", config.venues["okx"])

    assert snapshot.missing_market is True
    assert snapshot.errors
    assert "attempted_base_urls" in snapshot.raw_json


def test_collect_all_marks_timeout_when_venue_stuck(monkeypatch):
    def fake_collect_venue(_config, venue_name, venue_config):
        time.sleep(0.2)
        return VenueSnapshot(
            venue=venue_name,
            symbol=venue_config.symbol,
            ts_utc="2026-02-19T00:00:00+00:00",
            missing_market=False,
        )

    monkeypatch.setattr("mon_monitor.collector.collect_venue", fake_collect_venue)

    config = MonitorConfig(
        token_symbol="MON",
        venue_timeout_seconds=0,
        collect_workers=3,
        venues={
            "binance": VenueConfig(market="usdm_perp", symbol="MONUSDT"),
            "okx": VenueConfig(market="swap", symbol="MON-USDT-SWAP"),
        },
    )
    snapshots = collect_all(config)

    assert snapshots["binance"].missing_market is True
    assert snapshots["okx"].missing_market is True
    assert snapshots["binance"].errors
    assert snapshots["okx"].errors
    assert snapshots["binance"].errors[0].startswith("venue_timeout:")
    assert snapshots["okx"].errors[0].startswith("venue_timeout:")
