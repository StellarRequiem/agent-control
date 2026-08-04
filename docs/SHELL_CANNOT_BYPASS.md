# Native shell cannot-bypass gap (H4)

## Fact (updated: mediated deployment)

Plane tools always route through `AssuredPlaneHost` when called via `cli.py` or **MCP `agent_control`**.

Native Grok shell (`Bash` / `run_terminal_cmd`) is **outside** the host unless the deployment **denies** it and exposes the MCP plane.

### Mediated ambient mode (this host)

| Control | Status |
|---------|--------|
| MCP server `agent_control` → `mcp_server.py` | Installed in `~/.grok/config.toml` |
| `[permission] deny Bash(*)` | Installed — restart Grok to load |
| Headless `scripts/grok-mediated -p …` | Strips `run_terminal_cmd` |
| File edit tools | Still native (not shell) |

After Grok restart, `plane.status` → `claim_ceiling.native_runtime_shell_gated` becomes **true** when config is detected (`mediated_deployment` block).

```bash
python3 ~/agent-control/cli.py call plane.status
# mediated_deployment.native_bash_deny_configured + agent_control_mcp_configured
```

### Residual (still true)

| Residual | Why |
|----------|-----|
| File edits (`search_replace`, write) | Native Grok tools — not AssuredPlaneHost |
| Operator Terminal.app | Outside agent tool plane |
| Subagents | May still need MCP discipline; deny rules should apply |
| FREEZE vs OS | FREEZE gates plane tools; denied Bash should not run if permission engine honors deny |

## Operator SOP

1. **Restart Grok** after config change.  
2. Shell work via MCP `shell_exec` / `shell_run` or `cli.py call shell.*`.  
3. Plane GUI via MCP `plane_call` / browser_* / desktop_* / cua_*.  
4. Break-glass: comment out Bash deny in `~/.grok/config.toml`, restart.  
5. Full detail: `docs/MEDIATED_AMBIENT.md`.

## Closest true claim (mediated mode)

> On this deployment, native Bash is permission-denied and shell/plane actions are intended through agent-control MCP → AssuredPlaneHost. File-edit tools remain native. Not OS-wide lockdown.

See also: `docs/SHELL_GATING.md`, `docs/MEDIATED_AMBIENT.md`, `smoke/cannot_bypass_planes.py`.
