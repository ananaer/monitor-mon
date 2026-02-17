# MON 公开数据监控器

> **免责声明**：本项目仅用于公开市场数据的采集与监控，**不构成任何投资建议**，**不含任何交易能力**（无下单、撤单、账户操作），**不使用任何 API 密钥**。

## 概述

直接调用 Binance USDM、OKX Swap、Bybit Linear 永续合约的公开 REST API，对 MON 代币的关键市场数据面信号进行采集、存储、异常检测与告警。系统定位为「风控与观察雷达」。

### 核心功能

- **数据采集**：Ticker（价格/量）、订单簿深度、资金费率、持仓量、OHLCV K线
- **派生计算**：订单簿区间深度、冲击成本（吃单滑点）、波动率
- **异常检测**：深度收缩、价差扩张、冲击成本上升、流动性不足、量价异常
- **本地存储**：SQLite 持久化所有采样与告警，支持 CSV/JSONL 导出
- **零密钥**：完全使用公开 API，不读取或使用任何 API Key
- **纯 REST**：不依赖 ccxt，直接调用各交易所公开接口，可控性强

## 安装

```bash
cd catch-mon

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

## 配置

编辑 `config.yaml`（已含默认值）：

```yaml
token_symbol: "MON"
timezone: "Asia/Tokyo"
schedule_seconds: 300        # 采集间隔（秒）
baseline_days: 14            # 异常检测基线窗口（天）
orderbook_levels: 100        # 订单簿拉取深度
notional_1: 10000            # 冲击成本估算档位 1（USDT）
notional_2: 100000           # 冲击成本估算档位 2（USDT）

venues:
  binance:
    market: "usdm_perp"
    symbol: "MONUSDT"
    base_url: "https://fapi.binance.com"
  okx:
    market: "swap"
    symbol: "MON-USDT-SWAP"
    base_url: "https://www.okx.com"
  bybit:
    market: "linear"
    symbol: "MONUSDT"
    base_url: "https://api.bytick.com"      # 备用域名，国内可达

thresholds:
  depth_drop_mult: 0.7       # 深度收缩阈值
  spread_mult: 2.0           # 价差扩张阈值
  slip_mult: 2.0             # 冲击成本上升阈值
  volume_spike_mult: 2.0     # 量价异常阈值

dedupe_window_seconds: 3600  # 同类告警去重窗口（秒）
```

### base_url 说明

每个 venue 可通过 `base_url` 指定 API 根地址，方便在不同网络环境下切换：

| 交易所 | 默认地址 | 备用地址 |
|-------|---------|---------|
| Binance | `https://fapi.binance.com` | — |
| OKX | `https://www.okx.com` | — |
| Bybit | `https://api.bybit.com` | `https://api.bytick.com` |

## 运行

```bash
source .venv/bin/activate

# 单次采集
python -m mon_monitor.cli --mode run_once

# 守护模式（持续循环，Ctrl+C 优雅退出）
python -m mon_monitor.cli --mode run_daemon

# 使用自定义配置
python -m mon_monitor.cli --mode run_once --config my_config.yaml

# 详细日志
python -m mon_monitor.cli --mode run_once --verbose

# 导出数据
python -m mon_monitor.cli --export csv --export-table metrics_snapshot
python -m mon_monitor.cli --export jsonl --export-table alerts
```

## 输出

每轮采集输出：

1. **JSON 文件**：写入 `data/output/` 目录，包含完整采样数据与告警
2. **stdout 摘要**：可读的市场概况与告警汇总
3. **SQLite 数据库**：`data/mon_monitor.db`，持久化所有历史数据

### JSON 结构

```json
{
  "ts_utc": "2026-02-17T09:03:57+00:00",
  "token": "MON",
  "snapshots": {
    "binance": { "ticker": {...}, "orderbook": {...}, "funding": {...}, ... },
    "okx": { "ticker": {...}, "orderbook": {...}, ... },
    "bybit": { "ticker": {...}, "orderbook": {...}, ... }
  },
  "baselines": {
    "binance": { "depth_1pct_total_median": ..., "spread_bps_median": ... },
    "okx": { ... },
    "bybit": { ... }
  },
  "alerts": [
    {
      "alert_type": "insufficient_liquidity",
      "venue": "okx",
      "severity": "critical",
      "message": "...",
      "current_value": ...,
      "baseline_value": ...
    }
  ]
}
```

## 告警规则

| 告警类型 | 触发条件 | 确认机制 | 严重度 |
|---------|---------|---------|-------|
| 深度收缩 | depth_1pct_total < median * 0.7 | 连续 3 次 | warn |
| 价差扩张 | spread_bps > median * 2.0 | 连续 3 次 | warn |
| 冲击成本上升 | slip_bps_n2 > median * 2.0 | 连续 3 次 | warn |
| 流动性不足 | insufficient_liquidity 且缺口 > 20% | 立即触发 | critical |
| 量价异常 | volume_24h > mean_7d * 2.0 | 无需确认 | info |

## 派生指标公式

- **名义额** = price * amount_base
- **累计深度** = 区间内各档名义额求和
- **冲击成本 buy** = 按 asks 由低到高逐档吃单至 notional
- **滑点 buy** = (avg_fill_price - mid) / mid * 10000 (bps)
- **滑点 sell** = (mid - avg_fill_price) / mid * 10000 (bps)
- **realized_vol_24h** = std(ln(close[i] / close[i-1])) for recent 24h
- **atr_like_24h** = mean(high - low) for recent 24 candles

## 测试

```bash
source .venv/bin/activate
python -m pytest tests/ -v
```

## 项目结构

```
catch-mon/
├── README.md
├── requirements.txt
├── config.yaml
├── mon_monitor/
│   ├── __init__.py
│   ├── __main__.py      # python -m 入口
│   ├── cli.py           # CLI 入口（run_once / run_daemon）
│   ├── config.py        # 配置加载与验证
│   ├── collector.py     # 原生 REST API 数据采集（Binance/OKX/Bybit）
│   ├── calculator.py    # 派生指标计算
│   ├── detector.py      # 异常检测与告警
│   ├── storage.py       # SQLite 存储
│   ├── models.py        # 数据模型
│   └── formatter.py     # JSON/stdout 输出
├── tests/
│   ├── test_calculator.py
│   ├── test_detector.py
│   └── test_storage.py
└── data/                # 运行时生成（SQLite、JSON 输出）
```
