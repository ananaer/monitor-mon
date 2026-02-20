const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Client-Info, Apikey",
};

const BINANCE_FAPI = "https://fapi.binance.com/fapi/v1/fundingInfo";

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 200, headers: corsHeaders });
  }

  try {
    const res = await fetch(BINANCE_FAPI, {
      headers: { "Accept": "application/json" },
    });

    if (!res.ok) {
      throw new Error(`Binance API error ${res.status}`);
    }

    const raw: Array<Record<string, unknown>> = await res.json();

    const hourly = raw
      .filter((item) => Number(item.fundingIntervalHours) === 1)
      .map((item) => ({
        symbol: item.symbol,
        fundingIntervalHours: Number(item.fundingIntervalHours),
        adjustedFundingRateCap: item.adjustedFundingRateCap,
        adjustedFundingRateFloor: item.adjustedFundingRateFloor,
      }));

    return new Response(
      JSON.stringify({
        total: raw.length,
        hourly_count: hourly.length,
        items: hourly,
        fetched_at: new Date().toISOString(),
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
