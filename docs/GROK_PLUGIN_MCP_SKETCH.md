# Grok-plugin-shaped MCP packaging (batch-1 P2 sketch)

**Idea:** Expose browser-leash / agent-control as an installable MCP surface with the same deny-by-default posture.

## Shape

```
mcp-server (stdio)
  → AssuredPlaneHost tools only
  → never ambient shell
  → ARM still required for browser
```

## Tool list (proposed)

- `plane.status`  
- `browser.tabs` / `navigate` / `snapshot` / `click` / `type`  
- `shell.run` (named only)  
- `lockdown.status`  

## Non-goals

- Drop-in Browser Use replacement with full autonomy  
- Cloud browser  

## Status

Sketch only — implement when operator prioritizes packaging over local path.
