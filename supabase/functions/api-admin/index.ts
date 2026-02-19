import { createClient } from "npm:@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
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
    const path = url.pathname.replace(/^\/api-admin/, "");

    if (path === "/tokens" || path === "/tokens/") {
      if (req.method === "GET") {
        const { data, error } = await supabase
          .from("tokens")
          .select("*")
          .order("created_at", { ascending: true });

        if (error) throw error;
        return new Response(JSON.stringify({ tokens: data ?? [] }), {
          headers: { ...corsHeaders, "Content-Type": "application/json" },
        });
      }

      if (req.method === "POST") {
        const body = await req.json();
        const { token, enabled, binance_symbol, okx_inst_id, bybit_symbol, note } = body;
        if (!token) {
          return new Response(JSON.stringify({ error: "token is required" }), {
            status: 400,
            headers: { ...corsHeaders, "Content-Type": "application/json" },
          });
        }

        const { data, error } = await supabase
          .from("tokens")
          .insert({
            token: token.toUpperCase().trim(),
            enabled: enabled ?? true,
            binance_symbol: binance_symbol ?? "",
            okx_inst_id: okx_inst_id ?? "",
            bybit_symbol: bybit_symbol ?? "",
            note: note ?? "",
            updated_at: new Date().toISOString(),
          })
          .select()
          .single();

        if (error) throw error;
        return new Response(JSON.stringify({ token: data }), {
          status: 201,
          headers: { ...corsHeaders, "Content-Type": "application/json" },
        });
      }
    }

    const tokenMatch = path.match(/^\/tokens\/(\d+)$/);
    if (tokenMatch) {
      const id = Number(tokenMatch[1]);

      if (req.method === "PUT") {
        const body = await req.json();
        const { token, enabled, binance_symbol, okx_inst_id, bybit_symbol, note } = body;
        const updateData: Record<string, unknown> = { updated_at: new Date().toISOString() };
        if (token !== undefined) updateData.token = token.toUpperCase().trim();
        if (enabled !== undefined) updateData.enabled = enabled;
        if (binance_symbol !== undefined) updateData.binance_symbol = binance_symbol;
        if (okx_inst_id !== undefined) updateData.okx_inst_id = okx_inst_id;
        if (bybit_symbol !== undefined) updateData.bybit_symbol = bybit_symbol;
        if (note !== undefined) updateData.note = note;

        const { data, error } = await supabase
          .from("tokens")
          .update(updateData)
          .eq("id", id)
          .select()
          .single();

        if (error) throw error;
        return new Response(JSON.stringify({ token: data }), {
          headers: { ...corsHeaders, "Content-Type": "application/json" },
        });
      }

      if (req.method === "DELETE") {
        const { error } = await supabase.from("tokens").delete().eq("id", id);
        if (error) throw error;
        return new Response(JSON.stringify({ ok: true }), {
          headers: { ...corsHeaders, "Content-Type": "application/json" },
        });
      }
    }

    if (path === "/collector/status" && req.method === "GET") {
      const { data: state } = await supabase.from("runtime_state").select("*");
      const stateMap: Record<string, string> = {};
      for (const row of state ?? []) stateMap[row.key] = row.value;

      const { count: snapshotCount } = await supabase
        .from("metrics_snapshot")
        .select("id", { count: "exact", head: true });

      const { count: alertCount } = await supabase
        .from("alerts")
        .select("id", { count: "exact", head: true })
        .gte("ts_utc", new Date(Date.now() - 86400_000).toISOString());

      return new Response(
        JSON.stringify({
          state: stateMap,
          total_snapshots: snapshotCount ?? 0,
          alerts_24h: alertCount ?? 0,
        }),
        { headers: { ...corsHeaders, "Content-Type": "application/json" } }
      );
    }

    return new Response(JSON.stringify({ error: "not found" }), {
      status: 404,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  } catch (e) {
    return new Response(JSON.stringify({ error: String(e) }), {
      status: 500,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }
});
