const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL;
const ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY;

const BASE = `${SUPABASE_URL}/functions/v1`;

const headers = {
  Authorization: `Bearer ${ANON_KEY}`,
  "Content-Type": "application/json",
};

async function fetchJson(path, timeoutMs = 12000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${BASE}${path}`, {
      headers,
      cache: "no-store",
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`请求失败 ${res.status}: ${path}`);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

export function fetchOverview() {
  return fetchJson("/api-overview");
}

export function fetchHistory(limit = 120) {
  return fetchJson(`/api-history?limit=${limit}`);
}

export function fetchAlerts(limit = 50) {
  return fetchJson(`/api-alerts?limit=${limit}`);
}

export function triggerCollect() {
  return fetchJson("/collect-mon");
}
