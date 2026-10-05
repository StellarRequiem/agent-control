# Stdio process actor

`mcp_server.py` stamps one actor on every receipt for the life of the process, including `UNKNOWN_TOOL` denials. `plane.status` reports that name as `actors.current`.

Codex launches the server over stdio. Put the actor on the args the client already passes:

```toml
args = ["/Users/llm01/agent-control/mcp_server.py", "--actor", "codex"]
```

A full block, next to the existing Python command:

```toml
[mcp_servers.agent_control]
command = "/Users/llm01/mcp-assure/.venv/bin/python"
args = ["/Users/llm01/agent-control/mcp_server.py", "--actor", "codex"]
enabled = true
```

Grok's config stays without the flag. The default actor is `grok`.

## How the name is chosen

1. `--actor <name>` when the flag is present
2. otherwise the environment variable `AGENT_CONTROL_ACTOR`, when it is non-blank
3. otherwise `grok`

The value is lowercased and checked against the roster before the server listens. An unknown name prints an error and exits.

Built-in roster: `grok`, `claude`, `codex`.

`ollama` is not in that roster. The local harness in `docs/OLLAMA_AGENT.md` launches this server with `--actor ollama` only after the operator adds that name to `receipts/stdio-actors`.

Operators can add a name without a code change. Files live under `receipts/` and are gitignored, same place as HTTP passport files:

| File | What it does |
|------|----------------|
| `receipts/stdio-actors` | One actor id per line. `#` starts a comment. Use this for a stdio-only name. |
| `receipts/mcp-http.<actor>.token` | The filename admits `<actor>`. The body is never read, so a bearer is not loaded or logged. |

Ids match `^[a-z][a-z0-9_-]{0,31}$`. This server does not import the HTTP passport code; it only shares the filename convention so a name minted there is also a legal stdio actor.

## What is authority

The actor is set once at process start. A tool argument named `actor`, `agent`, or `agent_id` is removed before the gate and cannot change the receipt.

## Honest ceiling

The stdio actor is self-declared by the launching client's config (local trust). The operator who writes the Codex or Cursor MCP block chooses the string receipts will show. A bearer passport binds the actor to a token the caller has to present; this flag has no secret behind it. It labels an honestly configured Codex as `actor=codex`. AdaptiveGate, FREEZE, `operator_confirm`, and the leash HTTP calls on `:8756` and `:8757` stay as they are.
