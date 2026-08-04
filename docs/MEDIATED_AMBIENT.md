# Mediated ambient control plane — force routing

**Goal:** Operator and agent work as if the control plane is ambient, while
**authority** stays deny-by-default and high-blast human-gated.

## Honest boundary

| Path | Forced through AssuredPlaneHost? |
|------|----------------------------------|
| MCP `agent_control` tools | **Yes** (by construction) |
| `cli.py call …` | **Yes** |
| Native `run_terminal_cmd` / Bash | **Only if denied in Grok config** (below) |
| File edit tools (`search_replace`, …) | **No** — still native Grok (by product design) |
| Subagents with shell capability | **Inherit** parent denials; still use MCP for shell |

We do **not** claim OS-level inability to open Terminal.app. We claim **mediated agent tool path** when config is applied.

## What we install

1. **MCP server** `agent_control` → `mcp_server.py` wraps `AssuredPlaneHost`.  
2. **Grok permission deny** on native Bash / shell tool.  
3. **Skills / AGENTS** prefer MCP plane tools.  
4. **Headless wrapper** `scripts/grok-mediated` strips `run_terminal_cmd`.

## Config (applied to `~/.grok/config.toml`)

```toml
[permission]
deny = [
  "Bash(*)",
  "Bash",
]

[mcp_servers.agent_control]
command = "/Users/llm01/mcp-assure/.venv/bin/python"
args = ["/Users/llm01/agent-control/mcp_server.py"]
enabled = true
startup_timeout_sec = 45
tool_timeout_sec = 180
```

After edit: **restart Grok** so MCP connects and permission rules load.

## Agent usage (after restart)

Prefer MCP tools (names may appear as `agent_control__plane_call` etc.):

- `plane_call` with `tool=browser.navigate` / `shell.exec` / …  
- `shell_exec` / `shell_run` / `shell_list_dir` / `shell_read_file`  
- `browser_*`, `desktop_*`, `cua_*`

Do **not** use native shell when Bash is denied — the model must call MCP.

## Recovery under FREEZE (no native bash)

```bash
# Prefer MCP (freeze_allow includes these after MCP reload):
#   agent_control__plane_unfreeze  or  plane_call tool=plane.unfreeze
# Or operator terminal (outside agent deny):
rm -f ~/agent-control/FREEZE ~/mcp-assure/FREEZE
```

## Recovery under CHAIN_BROKEN (no native bash)

```text
# Diagnose (allowed even when chain is broken):
#   agent_control__plane_receipts_status
# Archive broken jsonl + start empty tip:
#   agent_control__plane_receipts_rotate
# Optional force even if intact:
#   plane_receipts_rotate force=true
```

mcp-assure re-syncs tip under flock on every append (multi-writer safe).  
Stale MCP processes without that code still need **MCP reload** after upgrade.


## Proof (post-restart live matrix)

| Check | Expected |
|-------|----------|
| Native `run_terminal_command` | Denied by permission policy (bash) |
| MCP `plane_status` | ALLOW · `native_runtime_shell_gated: true` |
| MCP `shell_run` / `shell_exec` (git) | ALLOW · RAN |
| MCP `shell.exec` with python3 | result INTERPRETER_DENIED |
| MCP unknown `shell_exec` tool | DENY UNKNOWN_TOOL |
| MCP `browser.x_post` without confirm | HUMAN_CONFIRM_REQUIRED |
| MCP navigate example.com | HOST_DENIED |
| MCP focus 1Password | PROFILE_DENIED |
| FREEZE file present | navigate DENY FREEZE; plane.status ALLOW |
| AdaptiveGate under tool spray | may ESCALATE (campaign) — correct |

```bash
# Offline host board (needs a shell outside agent, or named shell.run after unfreeze)
python3 ~/agent-control/smoke/proof_suite.py --offline
```

## Claim language

**After config + MCP live:**

> Native shell is **denied by Grok permission rules** on this host; shell and plane actions are intended to go through the agent-control MCP → AssuredPlaneHost. File edit tools remain native. Not OS-wide ambient lock.

**Still false without product change:** every possible process on the Mac is gated.

## Disable mediated shell deny (break glass)

Comment out `[permission] deny` Bash rules in `~/.grok/config.toml` and restart Grok.
