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

    const url = new URL(req.url);
    const limit = Math.min(Number(url.searchParams.get("limit") ?? "120"), 500);

    const venues = ["binance", "okx", "bybit"];
    const byVenue: Record<string, unknown[]> = {};

    await Promise.all(
      venues.map(async (venue) => {
        const { data } = await supabase
          .from("metrics_snapshot")
          .select("ts_utc, last_price, spread_bps, depth_1pct_total_usdt, quote_volume_24h")
          .eq("venue", venue)
          .is("error_type", null)
          .order("ts_utc", { ascending: false })
          .limit(limit);

        byVenue[venue] = (data ?? []).reverse();
      })
    );

    return new Response(
      JSON.stringify({ by_venue: byVenue }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  } catch (e) {
    return new Response(
      JSON.stringify({ error: String(e) }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  }
});
