let BASE = "";
let authHeaders = {};

function initConfig(url, key) {
  BASE = `${url}/functions/v1`;
  authHeaders = {
    Authorization: `Bearer ${key}`,
    "Content-Type": "application/json",
  };
}

async function fetchJson(path, timeoutMs = 12000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${BASE}${path}`, {
      headers: authHeaders,
      cache: "no-store",
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`请求失败 ${res.status}: ${path}`);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

async function fetchData() {
  self.postMessage({ type: "status", status: "fetching" });

  const [overview, history, alerts] = await Promise.all([
    fetchJson("/api-overview"),
    fetchJson("/api-history?limit=120"),
    fetchJson("/api-alerts?limit=50"),
  ]);

  self.postMessage({ type: "data", overview, history, alerts });
}

async function runFetch() {
  try {
    await fetchData();
  } catch (err) {
    self.postMessage({ type: "error", message: err?.message || String(err) });
  }
}

async function runCollect() {
  self.postMessage({ type: "status", status: "collecting" });

  try {
    await fetchJson("/collect-mon");
    await fetchData();
  } catch (err) {
    self.postMessage({ type: "error", message: err?.message || String(err) });
  }
}

self.onmessage = (e) => {
  const { type, supabaseUrl, anonKey } = e.data;

  if (type === "init") {
    initConfig(supabaseUrl, anonKey);
    runFetch();
    return;
  }

  if (type === "fetch") {
    runFetch();
    return;
  }

  if (type === "collect") {
    runCollect();
    return;
  }
};
