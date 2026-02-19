#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p data/logs data/run

if [[ -x ".venv/bin/python" ]]; then
  PY_BIN=".venv/bin/python"
else
  PY_BIN="python3"
fi

start_service() {
  local name="$1"
  local pid_file="$2"
  local out_file="$3"
  shift 3
  local cmd=("$@")

  if [[ -f "$pid_file" ]]; then
    local old_pid
    old_pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
      echo "$name already running (pid=$old_pid)"
      return
    fi
    rm -f "$pid_file"
  fi

  nohup "${cmd[@]}" >>"$out_file" 2>&1 &
  local new_pid=$!
  echo "$new_pid" >"$pid_file"
  echo "$name started (pid=$new_pid, out=$out_file)"
}

start_service \
  "collector" \
  "data/run/collector.pid" \
  "data/logs/collector.stdout.log" \
  "$PY_BIN" -m mon_monitor.cli --mode run_daemon --log-file data/logs/collector.log

start_service \
  "web" \
  "data/run/web.pid" \
  "data/logs/web.stdout.log" \
  "$PY_BIN" web/server.py --host 127.0.0.1 --port 8008 --log-file data/logs/web.log

echo "Logs:"
echo "  collector -> $ROOT_DIR/data/logs/collector.log"
echo "  web       -> $ROOT_DIR/data/logs/web.log"
