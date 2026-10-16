# Force mediated path — deploy checklist (batch-1 P0)

**Goal:** Agent cannot silently exercise ambient authority. Every high-blast action goes through the plane.

## Operator deploy checklist

| # | Check | How |
|---|--------|-----|
| 1 | Grok native Bash denied | `~/.grok/config.toml` permission deny on bash / shell |
| 2 | agent-control MCP configured | tools only via AssuredPlaneHost |
| 3 | browser-leash up + ARM when working | `cli.py session` / plane.status |
| 4 | desktop-leash up for GUI outside Chrome | port 8757 |
| 5 | FREEZE works | `lockdown engage --force` → navigate DENY → clear |
| 6 | No ambient `shell_exec` | smoke / cannot-bypass includes shell gate |
| 7 | agent-soc watch optional | `agent-soc watch --auto-respond-high` |
| 8 | Receipts intact | `plane.receipts_status` / mcp-assure receipts |
| 9 | Claim ceiling honest | session CUA · not enterprise SOC · not auto_post |
| 10 | Re-arm after IR | clear FREEZE; ARM leashes consciously |

## Fail-closed signals

- `native_runtime_shell_gated=false` → **do not** claim cannot-bypass  
- FREEZE files missing while severity critical → engage  
- Extension version lag → reload before high-blast  

## Related

- `SHELL_CANNOT_BYPASS.md` · `GROK_DEFAULT_PATH.md` · `HYBRID_PATH.md`  
- Paper: mediated control plane  
