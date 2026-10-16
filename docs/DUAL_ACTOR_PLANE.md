# Dual-actor plane — Grok + Claude

**Gate (shared):** `mcp-assure` deny-by-default catalog, blast levels, arg smell, receipts.  
**Grok actor:** `agent-control` MCP → AssuredPlaneHost → leashes / gated shell.  
**Claude actor:** `claude-control` PreToolUse → same gate (pack `claude.json`) + optional **same** MCP host for browser/desktop.

**Session bus (median, multi-surface):** `~/session-bus` — shared `session_id` for Grok Build + light clients (e.g. Grok iOS via Shortcuts). Skills **bound to session**; execution still on host plane. See `session-bus/README.md`.

```
                    mcp-assure
                   /          \
           Grok MCP host    Claude PreToolUse
         (agent-control)    (claude-control)
                |                  |
         browser-leash        receipts jsonl
         desktop-leash        (+ MCP if wired)
         shell.* / cua.*
```

## Authority model

| Surface | Default | Enforce |
|---------|---------|---------|
| Grok shell | Bash **deny** in Grok config + MCP | always (config) |
| Grok plane tools | AdaptiveGate pack | always |
| Claude tools | PreToolUse **observe** | only if `CLAUDE_CONTROL_ARMED=1` |
| Claude plane tools | MCP `agent_control` when connected | host pack (same as Grok) |

**Always available ≠ always armed** applies to both actors.

## SOC

`agent-soc` default sources include:

- `agent-control/receipts`
- `claude-control/receipts`
- leash receipt dirs

Claude events carry `actor=claude`, `mode=observe|armed`.

## Claim ceiling

- Dual-actor mediation **logging** does not imply full OS lockdown  
- Claude native Bash still works until observe is upgraded to arm **and** native fences  
- Same leashes / same Chrome ARM for both when using MCP browser tools  

## Ops

| Check | Command / path |
|-------|----------------|
| Grok plane | `plane.status` → `host_code`, `actors` |
| Claude wire | `claude_control_verify` named cmd / `scripts/verify_slice.py` |
| Map | `~/ops/CLAUDE_STACK_INTEGRATION.md` |
