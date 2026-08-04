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

## Proof

```bash
# MCP process starts
~/mcp-assure/.venv/bin/python ~/agent-control/mcp_server.py --help 2>/dev/null || true

# Host still gates
python3 ~/agent-control/cli.py call shell.exec --args-json '{"argv":["git","status"],"cwd":"/Users/llm01/agent-control"}'

# FREEZE still blocks plane tools
python3 ~/agent-control/cli.py proof --offline

# Claim ceiling remains honest until interactive session confirms Bash deny
python3 ~/agent-control/cli.py session
```

## Claim language

**After config + MCP live:**

> Native shell is **denied by Grok permission rules** on this host; shell and plane actions are intended to go through the agent-control MCP → AssuredPlaneHost. File edit tools remain native. Not OS-wide ambient lock.

**Still false without product change:** every possible process on the Mac is gated.

## Disable mediated shell deny (break glass)

Comment out `[permission] deny` Bash rules in `~/.grok/config.toml` and restart Grok.
