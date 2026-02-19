#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

show_service() {
  local name="$1"
  local pid_file="$2"
  if [[ ! -f "$pid_file" ]]; then
    echo "$name: stopped (no pid file)"
    return
  fi

  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    echo "$name: running (pid=$pid)"
  else
    echo "$name: stopped (stale pid=${pid:-unknown})"
  fi
}

show_service "collector" "data/run/collector.pid"
show_service "web" "data/run/web.pid"

echo
echo "api health:"
curl -sS --max-time 2 http://127.0.0.1:8008/api/health || echo "(web api unavailable)"

echo
echo "api runtime:"
curl -sS --max-time 2 http://127.0.0.1:8008/api/runtime || echo "(runtime api unavailable)"

echo
echo "last collector logs:"
tail -n 8 data/logs/collector.log 2>/dev/null || echo "(collector.log missing)"
tail -n 4 data/logs/collector.stdout.log 2>/dev/null || true

echo
echo "last web logs:"
tail -n 8 data/logs/web.log 2>/dev/null || echo "(web.log missing)"
tail -n 4 data/logs/web.stdout.log 2>/dev/null || true
