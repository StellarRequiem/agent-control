# MCP HTTP passports — token → actor

Internal agents **Grok, Claude, Codex** share the agent-control HTTP MCP. Each
gets its own bearer passport. Receipts then show who called the plane.

This is identity on the mediated path. It does **not** stop worms, and it is
**not** a full SOC. A separate agent-soc watch change can skip catalog-spray
FREEZE for this internal roster; that skip is not implemented here.

`claude-control` (if you run it) is a **separate** receipt plane — leave its
actor as `claude` if it already stamps that. These passports apply to
**agent-control** `mcp_http.py`.

## Files (gitignored, under `receipts/`)

| Actor | File |
|-------|------|
| grok | `receipts/mcp-http.token` (existing; do not rotate unless replacing Grok) |
| claude | `receipts/mcp-http.claude.token` |
| codex | `receipts/mcp-http.codex.token` |

One secret per file, first non-comment line. Mode `0600` when minted here.

## Mint a Claude or Codex passport

```bash
python3 ~/agent-control/mcp_http.py mint --actor claude
python3 ~/agent-control/mcp_http.py mint --actor codex
```

Stdout prints the token **once**. Put it in the connector. Do not commit the
file. Logs and this doc use prefixes only (`abcd1234…`).

Refuses to overwrite an existing file (keeps the live Grok token). `--force`
rotates; do not use that on Grok unless you intend to replace it.

## Connector Authorization header

HTTP MCP (loopback):

```text
URL:    http://127.0.0.1:8768/mcp
Header: Authorization: Bearer <token from mint>
```

Cursor / Claude / Codex HTTP MCP settings take the same header. Do **not** set
`X-Actor`, `User-Agent` identity, or a JSON `actor` field — those are ignored.
Only the bearer mapping sets actor.

Grok’s existing `receipts/mcp-http.token` stays the Grok passport so the live
token keeps working. Stdio `mcp_server.py` still defaults actor `grok` (no
bearer).

## Serve

```bash
python3 ~/agent-control/mcp_http.py serve
# 127.0.0.1:8768 only
```

`plane.status` → `actors` lists the roster (`grok` / `claude` / `codex`) and
which passport files are present. No secrets.

## What 401 means

Unknown or missing bearer is HTTP **401**. No passport actor, no receipt.

## Claims ceiling

Passports mark internal agents on this host’s HTTP MCP. They do not gate native
runtime tools, do not replace AdaptiveGate, and do not make agent-soc an
enterprise SOC.
