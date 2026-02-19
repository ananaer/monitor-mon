import { createClient } from "npm:@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Client-Info, Apikey",
};

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 200, headers: corsHeaders });
  }

  try {
    const supabase = createClient(
      Deno.env.get("SUPABASE_URL")!,
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
    );

    const venues = ["binance", "okx", "bybit"];

    const venueRows = await Promise.all(
      venues.map(async (venue) => {
        const { data } = await supabase
          .from("metrics_snapshot")
          .select("*")
          .eq("venue", venue)
          .order("ts_utc", { ascending: false })
          .limit(1)
          .maybeSingle();

        const { data: bl } = await supabase
          .from("baselines")
          .select("*")
          .eq("venue", venue)
          .maybeSingle();

        if (!data) {
          return { venue, symbol: "-", status: "down", error_reason: "no_data" };
        }

        const snapshotAge = data.ts_utc
          ? Math.floor((Date.now() - new Date(data.ts_utc).getTime()) / 1000)
          : null;

        let status = "ok";
        if (data.error_type) status = "down";
        else if (snapshotAge !== null && snapshotAge > 180) status = "stale";

        const depthRatio =
          bl?.median_depth_total && data.depth_1pct_total_usdt
            ? data.depth_1pct_total_usdt / bl.median_depth_total
            : null;

        return {
          venue,
          symbol: data.symbol ?? "-",
          status,
          last_price: data.last_price,
          pct_change_1h: data.pct_change_1h,
          quote_volume_24h: data.quote_volume_24h,
          spread_bps: data.spread_bps,
          depth_1pct_total_usdt: data.depth_1pct_total_usdt,
          slip_bps_n2: data.slip_bps_n2,
          snapshot_ts_utc: data.ts_utc,
          snapshot_age_seconds: snapshotAge,
          last_success_ts_utc: data.error_type ? null : data.ts_utc,
          data_lag_seconds: null,
          error_reason: data.error_type ?? null,
          funding_rate: data.funding_rate ?? null,
          open_interest_usd: data.open_interest_usd ?? null,
          ratios: { depth_vs_baseline: depthRatio },
        };
      })
    );

    const { data: stateRows } = await supabase.from("runtime_state").select("*");
    const state: Record<string, string> = {};
    for (const r of stateRows ?? []) state[r.key] = r.value;

    const oneDay = new Date(Date.now() - 86400_000).toISOString();
    const { count: alerts24h } = await supabase
      .from("alerts")
      .select("id", { count: "exact", head: true })
      .gte("ts_utc", oneDay);
    const { count: critical24h } = await supabase
      .from("alerts")
      .select("id", { count: "exact", head: true })
      .eq("severity", "critical")
      .gte("ts_utc", oneDay);

    const lastEnd = state["last_cycle_end_utc"] || null;
    const lastSuccessAge = lastEnd
      ? Math.floor((Date.now() - new Date(lastEnd).getTime()) / 1000)
      : null;

    const collector = {
      service_status: state["service_status"] ?? "unknown",
      last_cycle_start_utc: state["last_cycle_start_utc"] ?? null,
      last_cycle_end_utc: lastEnd,
      last_success_utc: state["last_success_utc"] ?? null,
      last_success_age_seconds: lastSuccessAge,
      venues_ok: Number(state["venues_ok"] ?? 0),
      venues_total: Number(state["venues_total"] ?? 0),
    };

    return new Response(
      JSON.stringify({
        token_hint: "MON",
        db_path: "Supabase",
        updated_at_utc: new Date().toISOString(),
        collector,
        venues: venueRows,
        stats: {
          venue_count: venueRows.length,
          alerts_24h: alerts24h ?? 0,
          critical_alerts_24h: critical24h ?? 0,
        },
      }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  } catch (e) {
    return new Response(
      JSON.stringify({ error: String(e) }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  }
});
