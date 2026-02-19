import "jsr:@supabase/functions-js/edge-runtime.d.ts";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Client-Info, Apikey",
};

async function lookupBinance(token: string): Promise<string | null> {
  try {
    const candidates = [
      `${token.toUpperCase()}USDT`,
      `${token.toUpperCase()}USDC`,
    ];
    for (const symbol of candidates) {
      const res = await fetch(`https://fapi.binance.com/fapi/v1/ticker/price?symbol=${symbol}`);
      if (res.ok) {
        const data = await res.json();
        if (data.symbol) return data.symbol;
      }
    }
    return null;
  } catch (_) {
    return null;
  }
}

async function lookupOkx(token: string): Promise<string | null> {
  try {
    const candidates = [
      `${token.toUpperCase()}-USDT-SWAP`,
      `${token.toUpperCase()}-USDC-SWAP`,
    ];
    const baseUrls = ["https://app.okx.com", "https://www.okx.com"];
    for (const base of baseUrls) {
      for (const instId of candidates) {
        try {
          const res = await fetch(`${base}/api/v5/public/instruments?instType=SWAP&instId=${instId}`);
          if (res.ok) {
            const data = await res.json();
            if (data?.data?.length > 0) return data.data[0].instId;
          }
        } catch (_) {}
      }
      break;
    }
    return null;
  } catch (_) {
    return null;
  }
}

async function lookupBybit(token: string): Promise<string | null> {
  try {
    const candidates = [
      `${token.toUpperCase()}USDT`,
      `${token.toUpperCase()}USDC`,
    ];
    for (const symbol of candidates) {
      const res = await fetch(`https://api.bybit.com/v5/market/tickers?category=linear&symbol=${symbol}`);
      if (res.ok) {
        const data = await res.json();
        if (data?.retCode === 0 && data?.result?.list?.length > 0) {
          return data.result.list[0].symbol;
        }
      }
    }
    return null;
  } catch (_) {
    return null;
  }
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 200, headers: corsHeaders });
  }

  try {
    const url = new URL(req.url);
    const token = url.searchParams.get("token");

    if (!token || token.trim().length === 0) {
      return new Response(
        JSON.stringify({ error: "token parameter is required" }),
        { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    const [binance, okx, bybit] = await Promise.all([
      lookupBinance(token.trim()),
      lookupOkx(token.trim()),
      lookupBybit(token.trim()),
    ]);

    return new Response(
      JSON.stringify({ binance, okx, bybit }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  } catch (e) {
    return new Response(
      JSON.stringify({ error: String(e) }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } }
    );
  }
});
