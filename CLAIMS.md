# Claim gate — agent-control

## Allowed

| Claim | Evidence |
|-------|----------|
| Assured host routes plane tools through mcp-assure AdaptiveGate | `host/plane_host.py`, smoke |
| Session CUA with step/time budget | `cua.*` tools + persisted session |
| Gated shell **subset** (named commands, rooted FS) | `shell.*` — no ambient `shell_exec` |
| Gated `shell.exec` — validated argv, interpreter-free, read-only git, path-confined | `host/shell_handlers.py:exec`, `tests/test_shell_exec_gate.py` |
| Dual human gates on x_post / quit / Return | handlers + smoke |

## Not allowed

| Overclaim |
|-----------|
| Every Grok/shell tool is gated |
| Full unlimited computer use |
| Full enterprise SOC |
| Auto-post to X |

## Wording

> **agent-control** is a local assured host: browser/desktop/CUA tools pass AdaptiveGate first. Session CUA under arm/allowlist — not ambient OS takeover.
