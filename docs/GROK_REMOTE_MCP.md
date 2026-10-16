# Grok bot → agent-control over HTTPS

Expose **browser-leash + desktop-leash** (same AssuredPlaneHost as local Grok Build) to a Grok **Custom Connector**.

```
Grok cloud / grok.com bot
        │  MCP Streamable-HTTP + Bearer
        ▼
   https://….trycloudflare.com/mcp
        │
        ▼
   127.0.0.1:8762  agent-control/mcp_http.py
        │
        ▼
   AssuredPlaneHost → AdaptiveGate → leashes (ARM still required)
```

Not a naked desktop. FREEZE, pack deny-by-default, and D4 confirms still apply.

## Bring-up (this Mac)

```bash
bash ~/agent-control/scripts/mcp_http_up.sh
bash ~/agent-control/scripts/mcp_http_tunnel.sh
# token (do not paste into git / X / Discord):
cat ~/agent-control/receipts/mcp-http.token
```

Quick tunnel URLs change when cloudflared restarts. For a stable hostname use a named Cloudflare tunnel or `tailscale funnel 8762`.

## Grok connector

1. https://grok.com/connectors → **New → Custom**
2. **Server URL:** `https://<host>/mcp`
3. **Auth:** Bearer, token from `receipts/mcp-http.token`  
   (or OAuth: authorize `/oauth/authorize`, token `/oauth/token`, client_secret = same token)
4. ARM **browser-leash** + **desktop-leash** on this Mac (human popup). Status tools work without ARM; clicks/tabs need ARM.

## What the bot can call

Same pack as local `agent_control`: `browser_tabs`, `browser_snapshot`, `browser_navigate`, `desktop_apps`, `desktop_screenshot`, `plane_status`, `plane_call`, …

Never invent `operator_confirm=true`.

## Security

| Control | Notes |
|---------|--------|
| Loopback bind | Default `127.0.0.1` — tunnel is the only public path |
| Bearer | Required on POST `/mcp` |
| Leashes | ARM + TCC; remote bot cannot skip |
| FREEZE | Still blocks non-status tools |
| Token file | `receipts/` gitignored; chmod 600 |

**Do not** put the tunnel URL on a public README with the token.

## Local Grok Build

Keep stdio MCP in `~/.grok/config.toml` for this machine. The HTTPS URL is for **cloud Grok / grok.com**, not a replacement for stdio.
