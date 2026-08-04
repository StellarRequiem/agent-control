# Claim gate — agent-control

## Allowed

| Claim | Evidence |
|-------|----------|
| Assured host routes plane tools through mcp-assure AdaptiveGate | `host/plane_host.py`, smoke |
| Session CUA with step/time budget | `cua.*` tools + persisted session (V1 default 40/30m) |
| Stack lifecycle one-command bring-up | `cli.py up|down|stack`, `host/lifecycle.py` |
| Always-available bridges without auto-arm | launchd + `cli.py available` · docs/ALWAYS_AVAILABLE.md |
| Unified session + proof board | `cli.py session` · `cli.py proof` |
| Layout included in CUA observe | `host/cua_loop.py` observe |
| Gated shell **subset** (named commands, rooted FS) | `shell.*` — no ambient `shell_exec` |
| Gated `shell.exec` — validated argv, interpreter-free, read-only git, path-confined | `host/shell_handlers.py:exec`, `tests/test_shell_exec_gate.py` |
| Dual human gates on x_post / quit / Return | handlers + smoke |
| Lockdown proxy to agent-soc FREEZE | `cli.py lockdown` · docs/ABHORRENT_LOCKDOWN.md |
| Working paper artifacts | `docs/paper/` |
| Mediated ambient: Bash deny + MCP plane host (when configured) | `docs/MEDIATED_AMBIENT.md` · `mcp_server.py` · `plane.status` mediated_deployment |

## Not allowed

| Overclaim |
|-----------|
| Every Grok/shell tool is gated |
| Full unlimited computer use / ambient OS takeover |
| Full enterprise SOC |
| Auto-post to X |
| Browser auto-arm without extension popup |
| Detection-rate % without holdout study |

## Wording

> **agent-control** is a local assured host: browser/desktop/CUA tools pass AdaptiveGate first. Always-available infrastructure optional; session authority stays arm-gated — **not** ambient OS takeover.
