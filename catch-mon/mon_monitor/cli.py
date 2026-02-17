"""
CLI 入口模块。
支持 run_once 和 run_daemon 两种运行模式。

用法:
    python -m mon_monitor.cli --mode run_once
    python -m mon_monitor.cli --mode run_daemon --config config.yaml
"""

import argparse
import json
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from mon_monitor.calculator import enrich_snapshot
from mon_monitor.collector import collect_all
from mon_monitor.config import MonitorConfig, load_config
from mon_monitor.detector import compute_baselines, run_all_checks
from mon_monitor.formatter import build_output, output_to_json, print_summary
from mon_monitor.storage import Storage

logger = logging.getLogger("mon_monitor")

# 优雅退出标志
_shutdown = False


def _signal_handler(signum, frame):
    global _shutdown
    _shutdown = True
    logger.info("收到退出信号 (%s)，将在当前轮次结束后退出", signum)


def setup_logging(verbose: bool = False):
    """配置日志。"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def run_once_cycle(config: MonitorConfig, storage: Storage, output_dir: str):
    """
    执行一轮完整的监控循环。
    返回本轮告警列表。
    """
    ts = datetime.now(timezone.utc).isoformat()
    logger.info("=== 开始采集轮次 %s ===", ts)

    # 1. 采集数据
    snapshots = collect_all(config)

    # 2. 派生计算
    for venue_name, snap in snapshots.items():
        enrich_snapshot(snap, config)

    # 3. 保存快照
    snapshot_ids = {}
    for venue_name, snap in snapshots.items():
        sid = storage.save_snapshot(snap)
        snapshot_ids[venue_name] = sid

    # 4. 计算基线
    baselines = {}
    for venue_name, venue_config in config.venues.items():
        baseline = compute_baselines(
            storage, venue_name, venue_config.symbol, config.baseline_days
        )
        baselines[venue_name] = baseline
        storage.save_baseline(baseline)

    # 5. 异常检测
    all_alerts = []
    for venue_name, snap in snapshots.items():
        if venue_name in baselines:
            venue_alerts = run_all_checks(
                snap, baselines[venue_name], config, storage
            )
            for alert in venue_alerts:
                storage.save_alert(alert, snapshot_ids.get(venue_name))
            all_alerts.extend(venue_alerts)

    # 6. 输出
    output = build_output(config.token_symbol, snapshots, baselines, all_alerts)
    json_str = output_to_json(output)

    # 写入 JSON 文件
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    ts_safe = ts.replace(":", "-").replace("+", "_")
    json_file = output_path / f"mon_snapshot_{ts_safe}.json"
    with open(json_file, "w", encoding="utf-8") as f:
        f.write(json_str)
    logger.info("JSON 输出已写入: %s", json_file)

    # 打印摘要
    print_summary(snapshots, baselines, all_alerts, config.timezone)

    logger.info("=== 轮次完成 ===")
    return all_alerts


def run_once(config: MonitorConfig, db_path: str, output_dir: str):
    """单次运行模式。"""
    storage = Storage(db_path)
    try:
        run_once_cycle(config, storage, output_dir)
    finally:
        storage.close()


def run_daemon(config: MonitorConfig, db_path: str, output_dir: str):
    """守护进程模式。循环执行，异常不退出。"""
    global _shutdown
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    storage = Storage(db_path)
    logger.info(
        "守护模式启动，间隔 %d 秒，Ctrl+C 退出",
        config.schedule_seconds,
    )

    try:
        while not _shutdown:
            try:
                run_once_cycle(config, storage, output_dir)
            except Exception as e:
                logger.error("本轮执行异常（不退出）: %s", e, exc_info=True)

            # 等待下一轮
            logger.info(
                "下次采集将在 %d 秒后...", config.schedule_seconds
            )
            for _ in range(config.schedule_seconds):
                if _shutdown:
                    break
                time.sleep(1)
    finally:
        storage.close()
        logger.info("守护模式已退出")


def main():
    parser = argparse.ArgumentParser(
        description="MON 公开数据监控器 — 零密钥，不含交易能力",
    )
    parser.add_argument(
        "--mode",
        choices=["run_once", "run_daemon"],
        default="run_once",
        help="运行模式 (默认: run_once)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="配置文件路径 (默认: config.yaml)",
    )
    parser.add_argument(
        "--db-path",
        default="data/mon_monitor.db",
        help="SQLite 数据库路径 (默认: data/mon_monitor.db)",
    )
    parser.add_argument(
        "--output-dir",
        default="data/output",
        help="JSON 输出目录 (默认: data/output)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="启用详细日志",
    )
    parser.add_argument(
        "--export",
        choices=["csv", "jsonl"],
        default=None,
        help="导出数据后退出 (可选)",
    )
    parser.add_argument(
        "--export-table",
        default="metrics_snapshot",
        help="导出的表名 (默认: metrics_snapshot)",
    )
    parser.add_argument(
        "--export-path",
        default=None,
        help="导出文件路径",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    config = load_config(args.config)

    # 导出模式
    if args.export:
        storage = Storage(args.db_path)
        export_path = args.export_path
        if not export_path:
            export_path = f"data/{args.export_table}.{args.export}"
        if args.export == "csv":
            storage.export_csv(args.export_table, export_path)
        else:
            storage.export_jsonl(args.export_table, export_path)
        storage.close()
        return

    if args.mode == "run_once":
        run_once(config, args.db_path, args.output_dir)
    elif args.mode == "run_daemon":
        run_daemon(config, args.db_path, args.output_dir)


if __name__ == "__main__":
    main()
