import { createClient } from "npm:@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Client-Info, Apikey",
};

interface VenueResult {
  venue: string;
  symbol: string;
  last_price: number | null;
  pct_change_1h: number | null;
  quote_volume_24h: number | null;
  spread_bps: number | null;
  depth_1pct_bid_usdt: number | null;
  depth_1pct_ask_usdt: number | null;
  depth_1pct_total_usdt: number | null;
  slip_bps_n1: number | null;
  slip_bps_n2: number | null;
  funding_rate: number | null;
  open_interest_usd: number | null;
  rvol_24h: number | null;
  error_type: string | null;
  error_msg: string | null;
  raw_json: Record<string, unknown> | null;
}

const NOTIONAL_N1 = 10_000;
const NOTIONAL_N2 = 100_000;

function safeNum(v: unknown): number | null {
  if (v === null || v === undefined || v === "" || v === "NaN") return null;
  const n = Number(v);
  return isFinite(n) ? n : null;
}

function calcSpreadBps(bid: number, ask: number): number | null {
  if (!bid || !ask || bid <= 0) return null;
  return ((ask - bid) / bid) * 10000;
}

function calcDepth(
  bids: [string, string][],
  asks: [string, string][],
  midPrice: number,
  pct: number
): { bid: number; ask: number; total: number } {
  const lo = midPrice * (1 - pct / 100);
  const hi = midPrice * (1 + pct / 100);
  let bidDepth = 0;
  for (const [p, q] of bids) {
    const price = Number(p);
    if (price >= lo) bidDepth += price * Number(q);
  }
  let askDepth = 0;
  for (const [p, q] of asks) {
    const price = Number(p);
    if (price <= hi) askDepth += price * Number(q);
  }
  return { bid: bidDepth, ask: askDepth, total: bidDepth + askDepth };
}

function calcImpactCost(
  side: "buy" | "sell",
  levels: [string, string][],
  notionalUsdt: number,
  midPrice: number
): number | null {
  if (!midPrice || midPrice <= 0) return null;
  let remaining = notionalUsdt;
  let totalCost = 0;
  let totalBase = 0;
  for (const [p, q] of levels) {
    const price = Number(p);
    const qty = Number(q);
    const val = price * qty;
    if (remaining <= 0) break;
    const fillNotional = Math.min(remaining, val);
    const fillBase = fillNotional / price;
    totalCost += fillNotional;
    totalBase += fillBase;
    remaining -= fillNotional;
  }
  if (remaining > 0) return null;
  if (totalBase <= 0) return null;
  const avgPrice = totalCost / totalBase;
  if (side === "buy") return ((avgPrice - midPrice) / midPrice) * 10000;
  return ((midPrice - avgPrice) / midPrice) * 10000;
}

function calcPctChange1hFromKlines(candles: [number, string, string, string, string, string][]): number | null {
  if (!candles || candles.length < 2) return null;
  const sorted = [...candles].sort((a, b) => a[0] - b[0]);
  const current = safeNum(sorted[sorted.length - 1][4]);
  const prev = safeNum(sorted[sorted.length - 2][4]);
  if (current === null || prev === null || prev === 0) return null;
  return ((current - prev) / prev) * 100;
}

function calcRvol24h(candles: [number, string, string, string, string, string][]): number | null {
  if (!candles || candles.length < 3) return null;
  const sorted = [...candles].sort((a, b) => a[0] - b[0]);
  const recent = sorted.slice(-25);
  const closes = recent.map((c) => safeNum(c[4])).filter((v): v is number => v !== null);
  if (closes.length < 3) return null;
  const returns: number[] = [];
  for (let i = 1; i < closes.length; i++) {
    if (closes[i - 1] > 0 && closes[i] > 0) {
      returns.push(Math.log(closes[i] / closes[i - 1]));
    }
  }
  if (returns.length < 2) return null;
  const mean = returns.reduce((a, b) => a + b, 0) / returns.length;
  const variance = returns.reduce((s, r) => s + (r - mean) ** 2, 0) / (returns.length - 1);
  return Math.sqrt(variance);
}

async function collectBinance(): Promise<VenueResult> {
  const venue = "binance";
  const symbol = "MONUSDT";
  try {
    const [tickerRes, bookRes, bookTickerRes, fundRes, oiRes, klinesRes] = await Promise.all([
      fetch(`https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=${symbol}`),
      fetch(`https://fapi.binance.com/fapi/v1/depth?symbol=${symbol}&limit=200`),
      fetch(`https://fapi.binance.com/fapi/v1/ticker/bookTicker?symbol=${symbol}`),
      fetch(`https://fapi.binance.com/fapi/v1/fundingRate?symbol=${symbol}&limit=1`),
      fetch(`https://fapi.binance.com/fapi/v1/openInterest?symbol=${symbol}`),
      fetch(`https://fapi.binance.com/fapi/v1/klines?symbol=${symbol}&interval=1h&limit=26`),
    ]);

    if (!tickerRes.ok) {
      const txt = await tickerRes.text();
      throw new Error(`ticker ${tickerRes.status}: ${txt.slice(0, 80)}`);
    }

    const ticker = await tickerRes.json();
    const book = bookRes.ok ? await bookRes.json() : null;
    const bookTicker = bookTickerRes.ok ? await bookTickerRes.json() : null;
    const fundArr = fundRes.ok ? await fundRes.json() : null;
    const oi = oiRes.ok ? await oiRes.json() : null;
    const klinesRaw = klinesRes.ok ? await klinesRes.json() : null;

    const lastPrice = safeNum(ticker.lastPrice);
    const bidPrice = safeNum(bookTicker?.bidPrice ?? ticker.bidPrice);
    const askPrice = safeNum(bookTicker?.askPrice ?? ticker.askPrice);
    const volume = safeNum(ticker.quoteVolume);
    const fundRate = fundArr?.[0] ? safeNum(fundArr[0].fundingRate) : null;
    const oiUsd = oi && lastPrice ? (safeNum(oi.openInterest) ?? 0) * lastPrice : null;

    const pct1h = calcPctChange1hFromKlines(klinesRaw);
    const rvol = calcRvol24h(klinesRaw);

    const spread = bidPrice && askPrice ? calcSpreadBps(bidPrice, askPrice) : null;
    const mid = lastPrice ?? ((bidPrice ?? 0) + (askPrice ?? 0)) / 2;

    let depthBid = null, depthAsk = null, depthTotal = null;
    let slipN1 = null, slipN2 = null;

    if (book && mid > 0) {
      const bids: [string, string][] = book.bids.map((b: string[]) => [b[0], b[1]] as [string, string]);
      const asks: [string, string][] = book.asks.map((a: string[]) => [a[0], a[1]] as [string, string]);
      const d = calcDepth(bids, asks, mid, 1);
      depthBid = d.bid;
      depthAsk = d.ask;
      depthTotal = d.total;
      slipN1 = calcImpactCost("buy", asks, NOTIONAL_N1, mid);
      slipN2 = calcImpactCost("buy", asks, NOTIONAL_N2, mid);
    }

    return {
      venue, symbol,
      last_price: lastPrice,
      pct_change_1h: pct1h,
      quote_volume_24h: volume,
      spread_bps: spread,
      depth_1pct_bid_usdt: depthBid,
      depth_1pct_ask_usdt: depthAsk,
      depth_1pct_total_usdt: depthTotal,
      slip_bps_n1: slipN1,
      slip_bps_n2: slipN2,
      funding_rate: fundRate,
      open_interest_usd: oiUsd,
      rvol_24h: rvol,
      error_type: null,
      error_msg: null,
      raw_json: { price: lastPrice, volume24h: volume },
    };
  } catch (e) {
    return {
      venue, symbol,
      last_price: null, pct_change_1h: null, quote_volume_24h: null,
      spread_bps: null, depth_1pct_bid_usdt: null, depth_1pct_ask_usdt: null,
      depth_1pct_total_usdt: null, slip_bps_n1: null, slip_bps_n2: null,
      funding_rate: null, open_interest_usd: null, rvol_24h: null,
      error_type: "fetch_error", error_msg: String(e), raw_json: null,
    };
  }
}

async function collectOkx(): Promise<VenueResult> {
  const venue = "okx";
  const instId = "MON-USDT-SWAP";
  const symbol = instId;

  const baseUrls = ["https://app.okx.com", "https://www.okx.com", "https://my.okx.com"];
  let base = baseUrls[0];
  for (const url of baseUrls) {
    try {
      const verifyRes = await fetch(`${url}/api/v5/public/instruments?instType=SWAP&instId=${instId}`);
      if (verifyRes.ok) {
        const data = await verifyRes.json();
        if (data?.data?.length > 0) { base = url; break; }
      }
    } catch (_) { continue; }
  }

  try {
    const [tickerRes, bookRes, fundRes, instRes, klinesRes] = await Promise.all([
      fetch(`${base}/api/v5/market/ticker?instId=${instId}`),
      fetch(`${base}/api/v5/market/books?instId=${instId}&sz=200`),
      fetch(`${base}/api/v5/public/funding-rate?instId=${instId}`),
      fetch(`${base}/api/v5/public/instruments?instType=SWAP&instId=${instId}`),
      fetch(`${base}/api/v5/market/candles?instId=${instId}&bar=1H&limit=26`),
    ]);

    if (!tickerRes.ok) throw new Error(`ticker ${tickerRes.status}`);
    const tickerData = await tickerRes.json();
    if (tickerData.code !== "0") throw new Error(`OKX code=${tickerData.code}: ${tickerData.msg}`);

    const t = tickerData.data?.[0];
    if (!t) throw new Error("no ticker data");

    const instData = instRes.ok ? await instRes.json() : null;
    const inst = instData?.data?.[0];
    const ctVal = inst ? (Number(inst.ctVal) * Number(inst.ctMult || 1)) : 1;

    const bookData = bookRes.ok ? await bookRes.json() : null;
    const book = bookData?.data?.[0];
    const fundData = fundRes.ok ? await fundRes.json() : null;
    const fund = fundData?.data?.[0];
    const klinesRaw = klinesRes.ok ? await klinesRes.json() : null;
    const candles = klinesRaw?.data ? [...klinesRaw.data].reverse() : null;

    const lastPrice = safeNum(t.last);
    const bidPrice = safeNum(t.bidPx);
    const askPrice = safeNum(t.askPx);
    const vol24hContracts = safeNum(t.vol24h);
    const volume = vol24hContracts !== null && lastPrice !== null ? vol24hContracts * ctVal * lastPrice : safeNum(t.volCcy24h);
    const spread = bidPrice && askPrice ? calcSpreadBps(bidPrice, askPrice) : null;
    const mid = lastPrice ?? ((bidPrice ?? 0) + (askPrice ?? 0)) / 2;
    const fundRate = fund ? safeNum(fund.fundingRate) : null;

    const pct1h = calcPctChange1hFromKlines(candles);
    const rvol = calcRvol24h(candles);

    let depthBid = null, depthAsk = null, depthTotal = null;
    let slipN1 = null, slipN2 = null;

    if (book && mid > 0) {
      const bids: [string, string][] = book.bids.map((b: string[]) => [b[0], String(Number(b[1]) * ctVal)] as [string, string]);
      const asks: [string, string][] = book.asks.map((a: string[]) => [a[0], String(Number(a[1]) * ctVal)] as [string, string]);
      const d = calcDepth(bids, asks, mid, 1);
      depthBid = d.bid;
      depthAsk = d.ask;
      depthTotal = d.total;
      slipN1 = calcImpactCost("buy", asks, NOTIONAL_N1, mid);
      slipN2 = calcImpactCost("buy", asks, NOTIONAL_N2, mid);
    }

    let oiUsd = null;
    try {
      const oiRes = await fetch(`${base}/api/v5/public/open-interest?instType=SWAP&instId=${instId}`);
      if (oiRes.ok) {
        const oiData = await oiRes.json();
        if (oiData?.data?.[0]) oiUsd = safeNum(oiData.data[0].oiUsd);
      }
    } catch (_) {}

    return {
      venue, symbol,
      last_price: lastPrice,
      pct_change_1h: pct1h,
      quote_volume_24h: volume,
      spread_bps: spread,
      depth_1pct_bid_usdt: depthBid,
      depth_1pct_ask_usdt: depthAsk,
      depth_1pct_total_usdt: depthTotal,
      slip_bps_n1: slipN1,
      slip_bps_n2: slipN2,
      funding_rate: fundRate,
      open_interest_usd: oiUsd,
      rvol_24h: rvol,
      error_type: null,
      error_msg: null,
      raw_json: { price: lastPrice, volume24h: volume, ctVal },
    };
  } catch (e) {
    return {
      venue, symbol,
      last_price: null, pct_change_1h: null, quote_volume_24h: null,
      spread_bps: null, depth_1pct_bid_usdt: null, depth_1pct_ask_usdt: null,
      depth_1pct_total_usdt: null, slip_bps_n1: null, slip_bps_n2: null,
      funding_rate: null, open_interest_usd: null, rvol_24h: null,
      error_type: "fetch_error", error_msg: String(e), raw_json: null,
    };
  }
}

async function collectBybit(): Promise<VenueResult> {
  const venue = "bybit";
  const symbol = "MONUSDT";
  try {
    const [tickerRes, bookRes, fundRes, klinesRes] = await Promise.all([
      fetch(`https://api.bybit.com/v5/market/tickers?category=linear&symbol=${symbol}`),
      fetch(`https://api.bybit.com/v5/market/orderbook?category=linear&symbol=${symbol}&limit=200`),
      fetch(`https://api.bybit.com/v5/market/funding/history?category=linear&symbol=${symbol}&limit=1`),
      fetch(`https://api.bybit.com/v5/market/kline?category=linear&symbol=${symbol}&interval=60&limit=26`),
    ]);

    if (!tickerRes.ok) throw new Error(`ticker ${tickerRes.status}`);
    const tickerData = await tickerRes.json();
    if (tickerData.retCode !== 0) throw new Error(`Bybit code=${tickerData.retCode}: ${tickerData.retMsg}`);

    const t = tickerData.result?.list?.[0];
    if (!t) throw new Error("no ticker data");

    const bookData = bookRes.ok ? await bookRes.json() : null;
    const book = bookData?.result;
    const fundData = fundRes.ok ? await fundRes.json() : null;
    const fund = fundData?.result?.list?.[0];
    const klinesRaw = klinesRes.ok ? await klinesRes.json() : null;
    const candles = klinesRaw?.result?.list ? [...klinesRaw.result.list].reverse() : null;

    const lastPrice = safeNum(t.lastPrice);
    const bidPrice = safeNum(t.bid1Price);
    const askPrice = safeNum(t.ask1Price);
    const volume = safeNum(t.turnover24h);
    const spread = bidPrice && askPrice ? calcSpreadBps(bidPrice, askPrice) : null;
    const mid = lastPrice ?? ((bidPrice ?? 0) + (askPrice ?? 0)) / 2;
    const fundRate = fund ? safeNum(fund.fundingRate) : null;
    const oiUsd = safeNum(t.openInterestValue);

    const pct1h = calcPctChange1hFromKlines(candles);
    const rvol = calcRvol24h(candles);

    let depthBid = null, depthAsk = null, depthTotal = null;
    let slipN1 = null, slipN2 = null;

    if (book && mid > 0) {
      const bids: [string, string][] = (book.b ?? []).map((b: string[]) => [b[0], b[1]] as [string, string]);
      const asks: [string, string][] = (book.a ?? []).map((a: string[]) => [a[0], a[1]] as [string, string]);
      const d = calcDepth(bids, asks, mid, 1);
      depthBid = d.bid;
      depthAsk = d.ask;
      depthTotal = d.total;
      slipN1 = calcImpactCost("buy", asks, NOTIONAL_N1, mid);
      slipN2 = calcImpactCost("buy", asks, NOTIONAL_N2, mid);
    }

    return {
      venue, symbol,
      last_price: lastPrice,
      pct_change_1h: pct1h,
      quote_volume_24h: volume,
      spread_bps: spread,
      depth_1pct_bid_usdt: depthBid,
      depth_1pct_ask_usdt: depthAsk,
      depth_1pct_total_usdt: depthTotal,
      slip_bps_n1: slipN1,
      slip_bps_n2: slipN2,
      funding_rate: fundRate,
      open_interest_usd: oiUsd,
      rvol_24h: rvol,
      error_type: null,
      error_msg: null,
      raw_json: { price: lastPrice, volume24h: volume },
    };
  } catch (e) {
    return {
      venue, symbol,
      last_price: null, pct_change_1h: null, quote_volume_24h: null,
      spread_bps: null, depth_1pct_bid_usdt: null, depth_1pct_ask_usdt: null,
      depth_1pct_total_usdt: null, slip_bps_n1: null, slip_bps_n2: null,
      funding_rate: null, open_interest_usd: null, rvol_24h: null,
      error_type: "fetch_error", error_msg: String(e), raw_json: null,
    };
  }
}

function detectAlerts(
  results: VenueResult[],
  baselineMap: Map<string, { median_spread_bps: number | null; median_depth_total: number | null; median_slip_n2: number | null }>
): Array<{ venue: string; alert_type: string; severity: string; message: string; threshold_val: number | null; current_val: number | null }> {
  const alerts = [];
  for (const r of results) {
    if (r.error_type) continue;
    const bl = baselineMap.get(r.venue);
    if (!bl) continue;

    if (bl.median_depth_total && r.depth_1pct_total_usdt !== null) {
      const ratio = r.depth_1pct_total_usdt / bl.median_depth_total;
      if (ratio < 0.7) {
        alerts.push({
          venue: r.venue,
          alert_type: "depth_shrink",
          severity: ratio < 0.4 ? "critical" : "warn",
          message: `深度低于基线 ${(ratio * 100).toFixed(1)}% (基线 $${bl.median_depth_total.toFixed(0)})`,
          threshold_val: 0.7,
          current_val: ratio,
        });
      }
    }

    if (bl.median_spread_bps && r.spread_bps !== null) {
      const ratio = r.spread_bps / bl.median_spread_bps;
      if (ratio > 2.0) {
        alerts.push({
          venue: r.venue,
          alert_type: "spread_widen",
          severity: "warn",
          message: `价差扩大至 ${r.spread_bps.toFixed(2)} bps (基线 ${bl.median_spread_bps.toFixed(2)} bps, ${ratio.toFixed(1)}x)`,
          threshold_val: 2.0,
          current_val: ratio,
        });
      }
    }
  }
  return alerts;
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 200, headers: corsHeaders });
  }

  try {
    const supabase = createClient(
      Deno.env.get("SUPABASE_URL")!,
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
    );

    const cycleStart = new Date().toISOString();

    const [binance, okx, bybit] = await Promise.all([
      collectBinance(),
      collectOkx(),
      collectBybit(),
    ]);

    const results = [binance, okx, bybit];
    const tsNow = new Date().toISOString();

    const rows = results.map((r) => ({ ...r, ts_utc: tsNow }));
    const { error: insertErr } = await supabase.from("metrics_snapshot").insert(rows);
    if (insertErr) throw new Error(`insert metrics: ${insertErr.message}`);

    const { data: blData } = await supabase.from("baselines").select("*");
    const baselineMap = new Map<string, { median_spread_bps: number | null; median_depth_total: number | null; median_slip_n2: number | null }>();
    for (const b of (blData ?? [])) {
      baselineMap.set(b.venue, b);
    }

    for (const r of results) {
      if (r.error_type || !r.last_price) continue;
      const { data: recent } = await supabase
        .from("metrics_snapshot")
        .select("spread_bps, depth_1pct_total_usdt, slip_bps_n2, quote_volume_24h")
        .eq("venue", r.venue)
        .is("error_type", null)
        .order("ts_utc", { ascending: false })
        .limit(200);

      if (!recent || recent.length < 3) continue;

      const spreads = recent.map((x: { spread_bps: number | null }) => x.spread_bps).filter((v): v is number => v !== null).sort((a, b) => a - b);
      const depths = recent.map((x: { depth_1pct_total_usdt: number | null }) => x.depth_1pct_total_usdt).filter((v): v is number => v !== null).sort((a, b) => a - b);
      const slips = recent.map((x: { slip_bps_n2: number | null }) => x.slip_bps_n2).filter((v): v is number => v !== null).sort((a, b) => a - b);
      const vols = recent.map((x: { quote_volume_24h: number | null }) => x.quote_volume_24h).filter((v): v is number => v !== null);

      const median = (arr: number[]) => arr.length === 0 ? null : arr[Math.floor(arr.length / 2)];
      const mean = (arr: number[]) => arr.length === 0 ? null : arr.reduce((a, b) => a + b, 0) / arr.length;

      await supabase.from("baselines").upsert({
        venue: r.venue,
        updated_at: tsNow,
        sample_count: recent.length,
        median_spread_bps: median(spreads),
        median_depth_total: median(depths),
        median_slip_n2: median(slips),
        mean_volume_24h: mean(vols),
      }, { onConflict: "venue" });
    }

    const alertRows = detectAlerts(results, baselineMap);
    if (alertRows.length > 0) {
      const oneHourAgo = new Date(Date.now() - 3600_000).toISOString();
      for (const a of alertRows) {
        const { data: existing } = await supabase
          .from("alerts")
          .select("id")
          .eq("venue", a.venue)
          .eq("alert_type", a.alert_type)
          .gte("ts_utc", oneHourAgo)
          .maybeSingle();
        if (!existing) {
          await supabase.from("alerts").insert({ ...a, ts_utc: tsNow });
        }
      }
    }

    const okCount = results.filter((r) => !r.error_type).length;
    await supabase.from("runtime_state").upsert([
      { key: "service_status", value: okCount > 0 ? "running" : "degraded", updated_at: tsNow },
      { key: "last_cycle_end_utc", value: tsNow, updated_at: tsNow },
      { key: "last_cycle_start_utc", value: cycleStart, updated_at: tsNow },
      { key: "last_success_utc", value: okCount > 0 ? tsNow : "", updated_at: tsNow },
      { key: "venues_ok", value: String(okCount), updated_at: tsNow },
      { key: "venues_total", value: String(results.length), updated_at: tsNow },
    ], { onConflict: "key" });

    return new Response(
      JSON.stringify({
        ok: true,
        venues: results.length,
        ok_count: okCount,
        ts: tsNow,
        details: results.map((r) => ({
          venue: r.venue,
          ok: !r.error_type,
          pct_change_1h: r.pct_change_1h,
          slip_bps_n2: r.slip_bps_n2,
          depth_1pct_total_usdt: r.depth_1pct_total_usdt,
          error: r.error_msg,
        })),
      }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  } catch (e) {
    return new Response(
      JSON.stringify({ ok: false, error: String(e) }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  }
});
