#!/usr/bin/env python3
"""
轻量监控后端：
- 托管前端静态页面
- 从 SQLite 读取监控数据并提供 JSON API
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT_DIR = Path(__file__).resolve().parent
STATIC_DIR = ROOT_DIR / "static"
DEFAULT_DB_PATH = ROOT_DIR.parent / "data" / "mon_monitor.db"
DEFAULT_LOG_PATH = ROOT_DIR.parent / "data" / "logs" / "web.log"
logger = logging.getLogger("mon_web")


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(ts)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pick_token_hint(symbols: list[str]) -> str:
    for symbol in symbols:
        raw = (symbol or "").upper()
        if not raw:
            continue
        normalized = raw.replace("-", "").replace("_", "")
        normalized = re.sub(r"(USDT|USD|PERP|SWAP)$", "", normalized)
        if normalized:
            return normalized
    return "TOKEN"


def _extract_error_meta(parsed_errors: Any) -> tuple[str | None, str | None]:
    def _split_code(raw: str) -> tuple[str, str | None]:
        if ":" not in raw:
            return raw, None
        maybe_code, detail = raw.split(":", 1)
        code = maybe_code.strip().lower()
        if re.fullmatch(r"[a-z0-9_]+", code):
            return detail.strip(), code
        return raw, None

    if isinstance(parsed_errors, list) and parsed_errors:
        first = parsed_errors[0]
        if isinstance(first, dict):
            code = first.get("code")
            detail = first.get("detail")
            reason = str(detail) if detail else str(first)
            return reason, str(code) if code else None
        first_str = str(first)
        return _split_code(first_str)
    if isinstance(parsed_errors, dict):
        code = parsed_errors.get("code")
        detail = parsed_errors.get("detail")
        reason = str(detail) if detail else str(parsed_errors)
        return reason, str(code) if code else None
    if isinstance(parsed_errors, str):
        return _split_code(parsed_errors)
    if parsed_errors:
        return str(parsed_errors), None
    return None, None


class MonitorRepository:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _query(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._connect() as conn:
            cur = conn.execute(sql, params)
            return cur.fetchall()

    def _query_one(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> sqlite3.Row | None:
        with self._connect() as conn:
            cur = conn.execute(sql, params)
            return cur.fetchone()

    def _get_runtime_states(self) -> dict[str, str]:
        try:
            rows = self._query("SELECT state_key, state_value FROM runtime_state")
            return {row["state_key"]: row["state_value"] for row in rows}
        except sqlite3.Error:
            return {}

    def _get_collector_status(self) -> dict[str, Any]:
        states = self._get_runtime_states()
        now = datetime.now(timezone.utc)
        last_success = states.get("collector.last_success_utc")
        last_cycle_end = states.get("collector.last_cycle_end_utc")
        schedule_seconds = states.get("collector.schedule_seconds")

        last_success_age = None
        last_cycle_age = None
        is_stale = None

        last_success_dt = _parse_ts(last_success)
        if last_success_dt:
            last_success_age = int((now - last_success_dt).total_seconds())

        last_cycle_dt = _parse_ts(last_cycle_end)
        if last_cycle_dt:
            last_cycle_age = int((now - last_cycle_dt).total_seconds())

        try:
            schedule_int = int(schedule_seconds) if schedule_seconds else None
        except ValueError:
            schedule_int = None

        if schedule_int and last_success_age is not None:
            is_stale = last_success_age > (schedule_int * 2)

        daemon_status = states.get("collector.daemon_status", "unknown")
        cycle_status = states.get("collector.last_cycle_status", "unknown")
        service_status = "running"
        if daemon_status != "running":
            service_status = "stopped"
        elif cycle_status == "running":
            service_status = "running"
        elif cycle_status == "error":
            service_status = "degraded"
        elif is_stale:
            service_status = "stale"

        return {
            "service_status": service_status,
            "daemon_status": daemon_status,
            "cycle_status": cycle_status,
            "mode": states.get("collector.mode"),
            "schedule_seconds": schedule_int,
            "last_cycle_start_utc": states.get("collector.last_cycle_start_utc"),
            "last_cycle_end_utc": last_cycle_end,
            "last_success_utc": last_success,
            "last_error": states.get("collector.last_error") or None,
            "last_alert_count": (
                int(states["collector.last_alert_count"])
                if states.get("collector.last_alert_count", "").isdigit()
                else None
            ),
            "cycle_seq": (
                int(states["collector.cycle_seq"])
                if states.get("collector.cycle_seq", "").isdigit()
                else None
            ),
            "last_cycle_duration_ms": (
                int(states["collector.last_cycle_duration_ms"])
                if states.get("collector.last_cycle_duration_ms", "").isdigit()
                else None
            ),
            "last_cycle_venues_total": (
                int(states["collector.last_cycle_venues_total"])
                if states.get("collector.last_cycle_venues_total", "").isdigit()
                else None
            ),
            "last_cycle_venues_ok": (
                int(states["collector.last_cycle_venues_ok"])
                if states.get("collector.last_cycle_venues_ok", "").isdigit()
                else None
            ),
            "last_cycle_venues_down": (
                int(states["collector.last_cycle_venues_down"])
                if states.get("collector.last_cycle_venues_down", "").isdigit()
                else None
            ),
            "last_success_age_seconds": last_success_age,
            "last_cycle_age_seconds": last_cycle_age,
            "is_stale": is_stale,
        }

    def get_overview(self) -> dict[str, Any]:
        collector_status = self._get_collector_status()
        now = datetime.now(timezone.utc)

        latest_current = self._query(
            """
            WITH ranked AS (
                SELECT *,
                       ROW_NUMBER() OVER (
                           PARTITION BY venue
                           ORDER BY ts_utc DESC, id DESC
                       ) AS rn
                FROM metrics_snapshot
            )
            SELECT venue, symbol, ts_utc, missing_market, errors,
                   last_price, quote_volume_24h, pct_change_1h, pct_change_24h,
                   spread_bps, depth_1pct_usdt_bid, depth_1pct_usdt_ask,
                   slip_bps_buy_n2, slip_bps_sell_n2
            FROM ranked
            WHERE rn = 1
            ORDER BY venue;
            """
        )

        latest_success = self._query(
            """
            WITH ranked AS (
                SELECT *,
                       ROW_NUMBER() OVER (
                           PARTITION BY venue
                           ORDER BY ts_utc DESC, id DESC
                       ) AS rn
                FROM metrics_snapshot
                WHERE missing_market = 0
            )
            SELECT venue, ts_utc
            FROM ranked
            WHERE rn = 1
            ORDER BY venue;
            """
        )

        baseline_rows = self._query(
            """
            WITH ranked AS (
                SELECT *,
                       ROW_NUMBER() OVER (
                           PARTITION BY venue
                           ORDER BY ts_utc DESC, id DESC
                       ) AS rn
                FROM baselines
            )
            SELECT venue, ts_utc, depth_1pct_total_median,
                   spread_bps_median, slip_bps_n2_median, volume_24h_mean_7d
            FROM ranked
            WHERE rn = 1
            ORDER BY venue;
            """
        )

        stats_row_raw = self._query_one(
            """
            SELECT
                SUM(CASE WHEN julianday(ts_utc) >= julianday('now', '-24 hours')
                    THEN 1 ELSE 0 END) AS snapshots_24h,
                COUNT(*) AS snapshots_total
            FROM metrics_snapshot;
            """
        )
        stats_row = dict(stats_row_raw) if stats_row_raw else {}

        alert_stats_row_raw = self._query_one(
            """
            SELECT
                SUM(CASE WHEN julianday(ts_utc) >= julianday('now', '-24 hours')
                    THEN 1 ELSE 0 END) AS alerts_24h,
                SUM(CASE WHEN julianday(ts_utc) >= julianday('now', '-24 hours')
                              AND severity = 'critical'
                    THEN 1 ELSE 0 END) AS critical_alerts_24h,
                COUNT(*) AS alerts_total
            FROM alerts;
            """
        )
        alert_stats_row = dict(alert_stats_row_raw) if alert_stats_row_raw else {}

        latest_current_map = {row["venue"]: dict(row) for row in latest_current}
        latest_success_map = {row["venue"]: dict(row) for row in latest_success}
        baseline_map = {row["venue"]: dict(row) for row in baseline_rows}

        venues: list[dict[str, Any]] = []
        all_venues = sorted(
            set(latest_current_map.keys())
            | set(latest_success_map.keys())
            | set(baseline_map.keys())
        )

        symbols = []
        updated_at = None
        for venue in all_venues:
            current_row = latest_current_map.get(venue, {})
            success_row = latest_success_map.get(venue, {})
            base = baseline_map.get(venue, {})

            symbol = current_row.get("symbol")
            if symbol:
                symbols.append(symbol)

            depth_bid = _safe_float(current_row.get("depth_1pct_usdt_bid"))
            depth_ask = _safe_float(current_row.get("depth_1pct_usdt_ask"))
            depth_total = None
            if depth_bid is not None or depth_ask is not None:
                depth_total = (depth_bid or 0.0) + (depth_ask or 0.0)

            slip_buy = _safe_float(current_row.get("slip_bps_buy_n2"))
            slip_sell = _safe_float(current_row.get("slip_bps_sell_n2"))
            slip_n2 = None
            if slip_buy is not None and slip_sell is not None:
                slip_n2 = (slip_buy + slip_sell) / 2.0
            elif slip_buy is not None:
                slip_n2 = slip_buy
            elif slip_sell is not None:
                slip_n2 = slip_sell

            snapshot_ts = current_row.get("ts_utc")
            last_success_ts = success_row.get("ts_utc")
            if snapshot_ts and ((not updated_at) or snapshot_ts > updated_at):
                updated_at = snapshot_ts

            baseline_depth = _safe_float(base.get("depth_1pct_total_median"))
            baseline_spread = _safe_float(base.get("spread_bps_median"))
            baseline_slip = _safe_float(base.get("slip_bps_n2_median"))
            baseline_volume = _safe_float(base.get("volume_24h_mean_7d"))

            spread_now = _safe_float(current_row.get("spread_bps"))
            volume_now = _safe_float(current_row.get("quote_volume_24h"))
            last_price_now = _safe_float(current_row.get("last_price"))
            pct_change_1h_now = _safe_float(current_row.get("pct_change_1h"))
            pct_change_24h_now = _safe_float(current_row.get("pct_change_24h"))

            missing_market = bool(current_row.get("missing_market", 1))
            has_metrics = any(
                v is not None
                for v in (
                    last_price_now,
                    spread_now,
                    depth_total,
                    volume_now,
                    slip_n2,
                )
            )
            snapshot_age_seconds = None
            snapshot_dt = _parse_ts(snapshot_ts)
            if snapshot_dt:
                snapshot_age_seconds = int((now - snapshot_dt).total_seconds())
            schedule_seconds = collector_status.get("schedule_seconds")
            stale_threshold_seconds = (
                max(int(schedule_seconds or 0) * 2, 90)
                if schedule_seconds
                else 180
            )
            is_stale = (
                snapshot_age_seconds is not None
                and snapshot_age_seconds > stale_threshold_seconds
            )
            if missing_market:
                status = "degraded" if has_metrics else "down"
            elif is_stale:
                status = "stale"
            else:
                status = "ok" if has_metrics else "degraded"

            lag_seconds = None
            success_dt = _parse_ts(last_success_ts)
            if snapshot_dt and success_dt:
                lag_seconds = int((snapshot_dt - success_dt).total_seconds())

            raw_errors = current_row.get("errors")
            parsed_errors = None
            if raw_errors:
                try:
                    parsed_errors = json.loads(raw_errors)
                except json.JSONDecodeError:
                    parsed_errors = raw_errors
            error_reason, error_code = _extract_error_meta(parsed_errors)

            venues.append(
                {
                    "venue": venue,
                    "symbol": symbol,
                    "status": status,
                    "missing_market": missing_market,
                    "snapshot_ts_utc": snapshot_ts,
                    "data_ts_utc": snapshot_ts,
                    "last_success_ts_utc": last_success_ts,
                    "data_lag_seconds": lag_seconds,
                    "snapshot_age_seconds": snapshot_age_seconds,
                    "stale_threshold_seconds": stale_threshold_seconds,
                    "is_stale": is_stale,
                    "last_price": last_price_now,
                    "quote_volume_24h": volume_now,
                    "pct_change_1h": pct_change_1h_now,
                    "pct_change_24h": pct_change_24h_now,
                    "spread_bps": spread_now,
                    "depth_1pct_total_usdt": depth_total,
                    "slip_bps_n2": slip_n2,
                    "baseline": {
                        "ts_utc": base.get("ts_utc"),
                        "depth_1pct_total_median": baseline_depth,
                        "spread_bps_median": baseline_spread,
                        "slip_bps_n2_median": baseline_slip,
                        "volume_24h_mean_7d": baseline_volume,
                    },
                    "ratios": {
                        "depth_vs_baseline": (
                            (depth_total / baseline_depth)
                            if depth_total is not None
                            and baseline_depth not in (None, 0.0)
                            else None
                        ),
                        "spread_vs_baseline": (
                            (spread_now / baseline_spread)
                            if spread_now is not None
                            and baseline_spread not in (None, 0.0)
                            else None
                        ),
                        "slip_vs_baseline": (
                            (slip_n2 / baseline_slip)
                            if slip_n2 is not None and baseline_slip not in (None, 0.0)
                            else None
                        ),
                        "volume_vs_baseline": (
                            (volume_now / baseline_volume)
                            if volume_now is not None
                            and baseline_volume not in (None, 0.0)
                            else None
                        ),
                    },
                    "errors": parsed_errors,
                    "error_reason": error_reason,
                    "error_code": error_code,
                }
            )

        latest_alerts = self.get_alerts(limit=20)
        return {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "db_path": str(self.db_path),
            "token_hint": _pick_token_hint(symbols),
            "updated_at_utc": updated_at,
            "collector": collector_status,
            "stats": {
                "snapshots_24h": int(stats_row.get("snapshots_24h") or 0),
                "snapshots_total": int(stats_row.get("snapshots_total") or 0),
                "alerts_24h": int(alert_stats_row.get("alerts_24h") or 0),
                "critical_alerts_24h": int(
                    alert_stats_row.get("critical_alerts_24h") or 0
                ),
                "alerts_total": int(alert_stats_row.get("alerts_total") or 0),
                "venue_count": len(venues),
            },
            "venues": venues,
            "alerts_recent": latest_alerts["items"],
        }

    def get_history(self, limit: int = 120) -> dict[str, Any]:
        rows = self._query(
            """
            WITH ranked AS (
                SELECT
                    ts_utc,
                    venue,
                    symbol,
                    last_price,
                    spread_bps,
                    (COALESCE(depth_1pct_usdt_bid, 0) + COALESCE(depth_1pct_usdt_ask, 0))
                        AS depth_1pct_total_usdt,
                    CASE
                        WHEN slip_bps_buy_n2 IS NULL AND slip_bps_sell_n2 IS NULL
                            THEN NULL
                        WHEN slip_bps_buy_n2 IS NULL
                            THEN slip_bps_sell_n2
                        WHEN slip_bps_sell_n2 IS NULL
                            THEN slip_bps_buy_n2
                        ELSE (slip_bps_buy_n2 + slip_bps_sell_n2) / 2.0
                    END AS slip_bps_n2,
                    ROW_NUMBER() OVER (
                        PARTITION BY venue
                        ORDER BY ts_utc DESC, id DESC
                    ) AS rn
                FROM metrics_snapshot
                WHERE missing_market = 0
            )
            SELECT ts_utc, venue, symbol, last_price, spread_bps,
                   depth_1pct_total_usdt, slip_bps_n2
            FROM ranked
            WHERE rn <= ?
            ORDER BY ts_utc ASC, venue ASC;
            """,
            (limit,),
        )

        points: list[dict[str, Any]] = []
        by_venue: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            point = {
                "ts_utc": row["ts_utc"],
                "venue": row["venue"],
                "symbol": row["symbol"],
                "last_price": _safe_float(row["last_price"]),
                "spread_bps": _safe_float(row["spread_bps"]),
                "depth_1pct_total_usdt": _safe_float(row["depth_1pct_total_usdt"]),
                "slip_bps_n2": _safe_float(row["slip_bps_n2"]),
            }
            points.append(point)
            by_venue.setdefault(row["venue"], []).append(point)

        return {"limit": limit, "points": points, "by_venue": by_venue}

    def get_alerts(self, limit: int = 50) -> dict[str, Any]:
        rows = self._query(
            """
            SELECT ts_utc, venue, symbol, alert_type, severity, message,
                   current_value, baseline_value, threshold_value
            FROM alerts
            ORDER BY ts_utc DESC, id DESC
            LIMIT ?;
            """,
            (limit,),
        )
        items = [
            {
                "ts_utc": row["ts_utc"],
                "venue": row["venue"],
                "symbol": row["symbol"],
                "alert_type": row["alert_type"],
                "severity": row["severity"],
                "message": row["message"],
                "current_value": _safe_float(row["current_value"]),
                "baseline_value": _safe_float(row["baseline_value"]),
                "threshold_value": _safe_float(row["threshold_value"]),
            }
            for row in rows
        ]
        return {"limit": limit, "items": items}


class MonitorHandler(SimpleHTTPRequestHandler):
    def __init__(
        self,
        *args: Any,
        repository: MonitorRepository,
        **kwargs: Any,
    ):
        self.repository = repository
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def _send_json(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _get_limit(self, query: dict[str, list[str]], default: int, cap: int) -> int:
        raw_limit = (query.get("limit") or [str(default)])[0]
        try:
            limit = int(raw_limit)
        except ValueError:
            return default
        return min(max(limit, 1), cap)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        try:
            if parsed.path == "/api/health":
                collector = self.repository._get_collector_status()
                service_status = collector.get("service_status")
                overall = "ok" if service_status in {"running", "degraded"} else "degraded"
                self._send_json(
                    {
                        "status": overall,
                        "service": "mon-monitor-web",
                        "collector": collector,
                        "time_utc": datetime.now(timezone.utc).isoformat(),
                    }
                )
                return

            if parsed.path == "/api/overview":
                self._send_json(self.repository.get_overview())
                return

            if parsed.path == "/api/history":
                limit = self._get_limit(query, default=120, cap=500)
                self._send_json(self.repository.get_history(limit=limit))
                return

            if parsed.path == "/api/alerts":
                limit = self._get_limit(query, default=50, cap=200)
                self._send_json(self.repository.get_alerts(limit=limit))
                return

            if parsed.path == "/api/runtime":
                self._send_json(
                    {"collector": self.repository._get_collector_status()}
                )
                return

            super().do_GET()
        except Exception as exc:  # pragma: no cover - 防止后端崩溃
            self._send_json(
                {
                    "error": str(exc),
                    "path": parsed.path,
                    "hint": "检查数据库文件是否存在且表结构完整",
                },
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def log_message(self, format: str, *args: Any) -> None:
        logger.info("%s - %s", self.client_address[0], format % args)


def setup_logging(log_file: str | None = None) -> None:
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MON 监控前端后端一体服务（SQLite + Vue 页面）"
    )
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8008, help="监听端口")
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="SQLite 数据库路径（默认: data/mon_monitor.db）",
    )
    parser.add_argument(
        "--log-file",
        default=str(DEFAULT_LOG_PATH),
        help="日志文件路径（默认: data/logs/web.log）",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    setup_logging(args.log_file)
    db_path = Path(args.db).resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"数据库不存在: {db_path}")
    if not STATIC_DIR.exists():
        raise FileNotFoundError(f"静态资源目录不存在: {STATIC_DIR}")

    repo = MonitorRepository(db_path=db_path)

    def _handler(*handler_args: Any, **handler_kwargs: Any) -> MonitorHandler:
        return MonitorHandler(
            *handler_args,
            repository=repo,
            **handler_kwargs,
        )

    with ThreadingHTTPServer((args.host, args.port), _handler) as httpd:
        logger.info(
            f"Monitor server listening at http://{args.host}:{args.port} "
            f"(db={db_path})"
        )
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            logger.info("Shutting down...")


if __name__ == "__main__":
    main()
