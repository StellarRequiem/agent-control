# Native shell cannot-bypass gap (H4)

## Fact

Grok Build’s **native runtime shell tool** does **not** route through `AssuredPlaneHost`.  
Plane tools (`browser.*`, `desktop.*`, gated `shell.*`) do.

Smoke still reports:

```json
"native_runtime_shell_gated": false,
"plane_tools_gated": true
```

## Operator SOP (close the gap in practice)

1. Prefer **gated host shell** for agent work:
   ```bash
   python3 ~/agent-control/cli.py call shell.run --args-json '{"name":"git_status"}'
   python3 ~/agent-control/cli.py call shell.exec --args-json '{"argv":["git","status"],"cwd":"/Users/llm01/agent-control"}'
   ```
2. Treat raw Grok shell as **operator-only** high-trust, not agent ambient.
3. Session preflight:
   ```bash
   python3 ~/agent-control/cli.py session
   # claim_ceiling.native_runtime_shell_gated should stay false until product wires it
   ```
4. Under FREEZE, only freeze-allow tools run (`plane.status`, `browser.status`, …) — **native shell still bypasses FREEZE**.

## What would make the claim true

| Requirement | Owner |
|-------------|--------|
| Disable or wrap native shell in Grok Build host | Product / runtime |
| Route all file/test/git via `shell.*` only | Agent SOP + skills |
| Optional: OS sandbox so unmediated shell is impossible | OS policy (heavy) |

## Closest true claim

> Plane tools on this host are gated through mcp-assure AdaptiveGate. Native Grok shell is **outside** that gate unless the runtime is configured to remove it.

See also: `docs/SHELL_GATING.md`, `smoke/cannot_bypass_planes.py`.
