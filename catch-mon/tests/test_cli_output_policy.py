from mon_monitor.cli import run_once_cycle
from mon_monitor.config import MonitorConfig, VenueConfig
from mon_monitor.models import BaselineValues, TickerData, VenueSnapshot
from mon_monitor.storage import Storage


def _make_config() -> MonitorConfig:
    return MonitorConfig(
        token_symbol="MON",
        venues={
            "binance": VenueConfig(
                market="usdm_perp",
                symbol="MONUSDT",
                base_url="https://fapi.binance.com",
            )
        },
        schedule_seconds=60,
    )


def _make_snapshot() -> VenueSnapshot:
    return VenueSnapshot(
        venue="binance",
        symbol="MONUSDT",
        ts_utc="2026-02-17T00:00:00+00:00",
        ticker=TickerData(last_price=0.02),
    )


def test_run_once_cycle_default_no_json_output(monkeypatch, tmp_path):
    db_path = tmp_path / "test.db"
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    config = _make_config()
    storage = Storage(str(db_path))

    monkeypatch.setattr("mon_monitor.cli.collect_all", lambda _config: {"binance": _make_snapshot()})
    monkeypatch.setattr("mon_monitor.cli.enrich_snapshot", lambda _snap, _config: None)
    monkeypatch.setattr(
        "mon_monitor.cli.compute_baselines",
        lambda _storage, venue, symbol, _days: BaselineValues(
            venue=venue,
            symbol=symbol,
            ts_utc="2026-02-17T00:00:00+00:00",
        ),
    )
    monkeypatch.setattr("mon_monitor.cli.run_all_checks", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("mon_monitor.cli.print_summary", lambda *_args, **_kwargs: None)

    try:
        run_once_cycle(config, storage, str(output_dir), write_json_output=False)
        assert list(output_dir.glob("mon_snapshot_*.json")) == []
        states = storage.get_runtime_states()
        assert states["collector.last_cycle_status"] == "ok"
        assert "collector.last_success_utc" in states
    finally:
        storage.close()


def test_run_once_cycle_can_write_json_output(monkeypatch, tmp_path):
    db_path = tmp_path / "test.db"
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    config = _make_config()
    storage = Storage(str(db_path))

    monkeypatch.setattr("mon_monitor.cli.collect_all", lambda _config: {"binance": _make_snapshot()})
    monkeypatch.setattr("mon_monitor.cli.enrich_snapshot", lambda _snap, _config: None)
    monkeypatch.setattr(
        "mon_monitor.cli.compute_baselines",
        lambda _storage, venue, symbol, _days: BaselineValues(
            venue=venue,
            symbol=symbol,
            ts_utc="2026-02-17T00:00:00+00:00",
        ),
    )
    monkeypatch.setattr("mon_monitor.cli.run_all_checks", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("mon_monitor.cli.print_summary", lambda *_args, **_kwargs: None)

    try:
        run_once_cycle(config, storage, str(output_dir), write_json_output=True)
        files = list(output_dir.glob("mon_snapshot_*.json"))
        assert len(files) == 1
    finally:
        storage.close()
