#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

stop_service() {
  local name="$1"
  local pid_file="$2"
  if [[ ! -f "$pid_file" ]]; then
    echo "$name not running (pid file missing)"
    return
  fi

  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -z "$pid" ]]; then
    rm -f "$pid_file"
    echo "$name pid file invalid (cleaned)"
    return
  fi

  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" || true
    echo "$name stopped (pid=$pid)"
  else
    echo "$name not running (stale pid=$pid)"
  fi
  rm -f "$pid_file"
}

stop_service "collector" "data/run/collector.pid"
stop_service "web" "data/run/web.pid"
