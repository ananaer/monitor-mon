const LOOKBACK = 96;
const FR_EXTREME_PCTILE = 0.85;

function last(arr) {
  return arr.length > 0 ? arr[arr.length - 1] : null;
}

function mean(arr) {
  if (arr.length === 0) return null;
  return arr.reduce((a, b) => a + b, 0) / arr.length;
}

function percentile(arr, p) {
  if (arr.length === 0) return null;
  const sorted = [...arr].sort((a, b) => a - b);
  const idx = (sorted.length - 1) * p;
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
}

function slope(arr) {
  const n = arr.length;
  if (n < 2) return 0;
  const recent = arr.slice(-Math.min(n, 12));
  const last6 = mean(recent.slice(-6));
  const first6 = mean(recent.slice(0, 6));
  if (last6 === null || first6 === null || first6 === 0) return 0;
  return (last6 - first6) / first6;
}

function latestVal(points, key) {
  for (let i = points.length - 1; i >= 0; i--) {
    const v = Number(points[i][key]);
    if (Number.isFinite(v)) return v;
  }
  return null;
}

function numericSeries(points, key) {
  return points.map((p) => Number(p[key])).filter((v) => Number.isFinite(v));
}

function priceBreakout(venue, points) {
  const prices = numericSeries(points, "last_price");
  if (prices.length < 10) return { score: 0, detail: "价格数据不足" };
  const lookback = prices.slice(-Math.min(prices.length, LOOKBACK));
  const current = last(lookback);
  const recent = lookback.slice(0, -1);
  const isHigh = current > Math.max(...recent);
  const isLow = current < Math.min(...recent);
  const sl = slope(lookback);
  if (isHigh) return { score: 1, detail: `创新高 斜率 ${(sl * 100).toFixed(2)}%`, direction: "long" };
  if (isLow) return { score: 1, detail: `创新低 斜率 ${(sl * 100).toFixed(2)}%`, direction: "short" };
  if (sl > 0.005) return { score: 0.5, detail: `上行趋势 斜率 ${(sl * 100).toFixed(2)}%`, direction: "long" };
  if (sl < -0.005) return { score: 0.5, detail: `下行趋势 斜率 ${(sl * 100).toFixed(2)}%`, direction: "short" };
  return { score: 0, detail: "无明显方向", direction: "flat" };
}

function oiCrowding(venue, points) {
  const oiSeries = numericSeries(points, "open_interest_usd");
  const frSeries = numericSeries(points, "funding_rate");
  if (oiSeries.length < 6) return { score: 0, detail: "OI 数据不足", crowded: false };

  const oiRecent = oiSeries.slice(-Math.min(oiSeries.length, LOOKBACK));
  const oiSlope = slope(oiRecent);
  const oiRising = oiSlope > 0.002;
  const oiFalling = oiSlope < -0.002;

  let frExtreme = false;
  let frDirection = "neutral";
  let frVal = null;
  if (frSeries.length >= 6) {
    const frRecent = frSeries.slice(-Math.min(frSeries.length, LOOKBACK));
    frVal = last(frRecent);
    const frHigh = percentile(frRecent, FR_EXTREME_PCTILE);
    const frLow = percentile(frRecent, 1 - FR_EXTREME_PCTILE);
    if (frVal !== null && frHigh !== null && frVal >= frHigh) {
      frExtreme = true;
      frDirection = "long_crowded";
    } else if (frVal !== null && frLow !== null && frVal <= frLow) {
      frExtreme = true;
      frDirection = "short_crowded";
    } else if (frVal !== null) {
      frDirection = frVal > 0 ? "long_mild" : frVal < 0 ? "short_mild" : "neutral";
    }
  }

  const frPct = frVal !== null ? (frVal * 100).toFixed(4) + "%" : "-";
  const oiSlopePct = (oiSlope * 100).toFixed(2) + "%";

  if (oiRising && !frExtreme) {
    return {
      score: 1,
      detail: `OI 增仓 ${oiSlopePct} 费率温和 ${frPct}`,
      crowded: false,
      frDirection,
      oiTrend: "rising",
    };
  }
  if (oiRising && frExtreme) {
    return {
      score: 0.5,
      detail: `OI 增仓但费率极端 ${frPct}，拥挤风险`,
      crowded: true,
      frDirection,
      oiTrend: "rising",
    };
  }
  if (oiFalling) {
    return {
      score: 0,
      detail: `OI 去杠杆 ${oiSlopePct} 费率 ${frPct}`,
      crowded: false,
      frDirection,
      oiTrend: "falling",
      deleveraging: true,
    };
  }
  return {
    score: 0.3,
    detail: `OI 横盘 费率 ${frPct}`,
    crowded: frExtreme,
    frDirection,
    oiTrend: "flat",
  };
}

function executionQuality(venue, points, baseline) {
  const spreadSeries = numericSeries(points, "spread_bps");
  const depthSeries = numericSeries(points, "depth_1pct_total_usdt");
  const n2Series = numericSeries(points, "slip_bps_n2");

  const spreadNow = latestVal(points, "spread_bps");
  const depthNow = latestVal(points, "depth_1pct_total_usdt");
  const n2Now = latestVal(points, "slip_bps_n2");

  const details = [];
  let badCount = 0;
  let hasData = false;

  if (spreadSeries.length >= 6) {
    hasData = true;
    const spreadBase = mean(spreadSeries.slice(0, Math.max(1, spreadSeries.length - 6)));
    if (spreadBase && spreadNow !== null && spreadNow > spreadBase * 2.0) {
      details.push(`价差扩大 ${spreadNow.toFixed(2)} bps`);
      badCount++;
    } else if (spreadNow !== null) {
      details.push(`价差 ${spreadNow.toFixed(2)} bps`);
    }
  }

  if (depthSeries.length >= 6) {
    hasData = true;
    const depthBase = mean(depthSeries.slice(0, Math.max(1, depthSeries.length - 6)));
    if (depthBase && depthNow !== null && depthNow < depthBase * 0.5) {
      details.push(`深度萎缩 $${(depthNow / 1000).toFixed(0)}k`);
      badCount++;
    } else if (depthNow !== null) {
      details.push(`深度 $${(depthNow / 1000).toFixed(0)}k`);
    }
  }

  if (n2Series.length >= 6) {
    hasData = true;
    const n2Base = mean(n2Series.slice(0, Math.max(1, n2Series.length - 6)));
    if (n2Base && n2Now !== null && n2Now > n2Base * 2.0) {
      details.push(`N2 抬升 ${n2Now.toFixed(2)} bps`);
      badCount++;
    } else if (n2Now !== null) {
      details.push(`N2 ${n2Now.toFixed(2)} bps`);
    }
  }

  if (!hasData) return { score: 1, detail: "执行数据不足，默认通过", degraded: false };

  const degraded = badCount >= 2;
  const score = badCount === 0 ? 1 : badCount === 1 ? 0.5 : 0;

  return {
    score,
    detail: details.join(" · "),
    degraded,
    spreadNow,
    depthNow,
    n2Now,
  };
}

function classifySignal(price, oi, exec) {
  const execOk = !exec.degraded;

  if (!execOk) {
    return {
      type: "filter",
      label: "执行质量差",
      description: "盘口恶化，暂不建议交易",
      confidence: 0,
      color: "signal-filter",
    };
  }

  if (oi.deleveraging && price.score >= 0.5) {
    return {
      type: "reversal",
      label: "清算释放",
      description: "OI 去杠杆后回摆机会，等下一根四小时确认",
      confidence: Math.round((price.score + (oi.score > 0 ? 0.5 : 0.3)) * 50),
      direction: price.direction === "long" ? "short" : "long",
      color: "signal-reversal",
    };
  }

  if (oi.crowded && price.score >= 0.5) {
    return {
      type: "squeeze",
      label: "挤仓突破",
      description: "OI 增仓但费率极端，波动加速或反转，小仓快进快出",
      confidence: Math.round(price.score * 60),
      direction: price.direction,
      color: "signal-squeeze",
    };
  }

  if (price.score >= 0.5 && oi.score >= 0.8 && execOk) {
    return {
      type: "trend",
      label: "顺势延续",
      description: "价格突破 + OI 增仓 + 执行质量良好，跟随四小时趋势",
      confidence: Math.round((price.score + oi.score + 1) / 3 * 100),
      direction: price.direction,
      color: "signal-trend",
    };
  }

  return {
    type: "wait",
    label: "观望",
    description: "信号强度不足，等待更清晰的结构",
    confidence: 0,
    color: "signal-wait",
  };
}

export function computeSignals(history, overviewVenues) {
  const byVenue = history?.by_venue || {};
  const venues = Object.keys(byVenue);

  return venues.map((venue) => {
    const points = byVenue[venue] || [];
    if (points.length < 6) {
      return {
        venue,
        signal: { type: "wait", label: "数据不足", description: "历史数据过少，无法计算信号", confidence: 0, color: "signal-wait" },
        components: {},
      };
    }

    const venueMeta = overviewVenues?.find((v) => v.venue === venue) ?? null;
    const price = priceBreakout(venue, points);
    const oi = oiCrowding(venue, points);
    const exec = executionQuality(venue, points, venueMeta);
    const signal = classifySignal(price, oi, exec);

    return {
      venue,
      signal,
      components: { price, oi, exec },
    };
  });
}
