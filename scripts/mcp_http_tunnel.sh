#!/bin/bash
# Public HTTPS tunnel so Grok cloud / grok.com bot can reach agent-control MCP.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${AGENT_CONTROL_MCP_PORT:-8762}"
LOG="$ROOT/receipts/mcp-http-tunnel.log"
PIDF="$ROOT/receipts/mcp-http-tunnel.pid"
mkdir -p "$ROOT/receipts"

bash "$ROOT/scripts/mcp_http_up.sh" >/dev/null || true

if [[ -f "$PIDF" ]]; then
  old=$(cat "$PIDF" 2>/dev/null || true)
  if [[ -n "${old:-}" ]] && kill -0 "$old" 2>/dev/null; then
    echo "{\"ok\":true,\"code\":\"TUNNEL_ALREADY\",\"pid\":$old,\"log\":\"$LOG\"}"
    tail -n 8 "$LOG" 2>/dev/null || true
    exit 0
  fi
fi

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "{\"ok\":false,\"code\":\"NO_CLOUDFLARED\",\"hint\":\"brew install cloudflared  OR  tailscale funnel ${PORT}\"}"
  exit 2
fi

: >"$LOG"
nohup cloudflared tunnel --url "http://127.0.0.1:${PORT}" >>"$LOG" 2>&1 &
echo $! >"$PIDF"
url=""
for _ in 1 2 3 4 5 6 7 8 9 12 15; do
  sleep 1
  url=$(grep -oE 'https://[a-zA-Z0-9.-]+\.trycloudflare\.com' "$LOG" | tail -n1 || true)
  if [[ -n "$url" ]]; then
    break
  fi
done
echo "{"
echo "  \"ok\": true,"
echo "  \"code\": \"CLOUDFLARED\","
echo "  \"public_mcp_url\": \"${url}/mcp\","
echo "  \"health\": \"${url}/health\","
echo "  \"auth\": \"Bearer from $ROOT/receipts/mcp-http.token\","
echo "  \"grok_steps\": ["
echo "    \"https://grok.com/connectors → New Connector → Custom\","
echo "    \"Server URL: ${url}/mcp\","
echo "    \"Auth: Bearer token in receipts/mcp-http.token\","
echo "    \"ARM browser-leash + desktop-leash on this Mac\""
echo "  ],"
echo "  \"log\": \"$LOG\","
echo "  \"pid\": $(cat "$PIDF")"
echo "}"
