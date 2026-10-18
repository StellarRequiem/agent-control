#!/bin/bash
# Loopback Streamable-HTTP MCP for agent-control (browser + desktop leashes).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$ROOT/receipts/mcp-http.log"
PIDF="$ROOT/receipts/mcp-http.pid"
PY="${AGENT_CONTROL_PYTHON:-$HOME/mcp-assure/.venv/bin/python}"
mkdir -p "$ROOT/receipts"

if [[ -f "$PIDF" ]]; then
  old=$(cat "$PIDF" 2>/dev/null || true)
  if [[ -n "${old:-}" ]] && kill -0 "$old" 2>/dev/null; then
    echo "{\"ok\":true,\"code\":\"MCP_ALREADY\",\"pid\":$old}"
    exit 0
  fi
  rm -f "$PIDF"
fi

export AGENT_CONTROL_MCP_PORT="${AGENT_CONTROL_MCP_PORT:-8762}"
export AGENT_CONTROL_MCP_HOST="${AGENT_CONTROL_MCP_HOST:-127.0.0.1}"
nohup "$PY" "$ROOT/mcp_http.py" >>"$LOG" 2>&1 &
echo $! >"$PIDF"
sleep 0.5
curl -s "http://127.0.0.1:${AGENT_CONTROL_MCP_PORT}/health" || true
echo
echo "{\"ok\":true,\"code\":\"MCP_STARTED\",\"pid\":$(cat "$PIDF"),\"port\":$AGENT_CONTROL_MCP_PORT,\"log\":\"$LOG\"}"
