# Ollama agent

A local harness that lets an Ollama model work through the assured plane the way Codex and Claude do: stdio MCP into `mcp_server.py`, tool calls only from the server's advertised list, receipts stamped `actor=ollama`.

This is a prototype. See [Honest ceiling](#honest-ceiling).

The process actor is the stdio `--actor` flag from [STDIO_ACTOR.md](STDIO_ACTOR.md). `ollama` is **not** in the built-in roster (`grok`, `claude`, `codex`). The operator adds it. The harness does not write that file and does not edit `DEFAULT_ROSTER`.

## Setup

Ollama is running on the operator Mac (`ollama serve`, or the Ollama app). The plane interpreter is the same one that already imports the MCP SDK for `mcp_server.py`.

```bash
ollama pull qwen3:8b

mkdir -p ~/agent-control/receipts
grep -qx 'ollama' ~/agent-control/receipts/stdio-actors 2>/dev/null \
  || printf 'ollama\n' >> ~/agent-control/receipts/stdio-actors
```

`receipts/stdio-actors` is gitignored. One actor id per line. `#` starts a comment.

Confirm the interpreter can import both the server and the client. `mcp_server.py` uses `mcp.server.fastmcp`, which is mcp 1.x. mcp 2 renamed that class and will not start this server. Use the venv that already launches the server; do not `pip install -U mcp` over it.

```bash
~/mcp-assure/.venv/bin/python -c "from mcp.server.fastmcp import FastMCP; from mcp.client.stdio import stdio_client"
```

If the client import fails and FastMCP still imports, pin the 1.x line:

```bash
~/mcp-assure/.venv/bin/python -m pip install 'mcp>=1,<2'
```

## Run

Dry-run lists the tools the server actually advertised, intersected with the allowlist, and prints the system prompt. It does not call the model. It does start `mcp_server.py --actor ollama`, so the roster line above has to be in place.

```bash
~/mcp-assure/.venv/bin/python ~/agent-control/ollama_agent.py --dry-run \
  "report plane status"
```

One task:

```bash
~/mcp-assure/.venv/bin/python ~/agent-control/ollama_agent.py \
  "Call plane_status. Quote only fields the tool returned. Close with a VERIFIED block."
```

Useful flags:

```bash
~/mcp-assure/.venv/bin/python ~/agent-control/ollama_agent.py \
  --model qwen3:8b \
  --host http://127.0.0.1:11434 \
  --max-steps 20 \
  --timeout 180 \
  --max-errors 3 \
  --rules ~/.codex/AGENTS.md \
  "Call plane_status and quote only what it returned."
```

| Flag | Default | What it does |
|------|---------|----------------|
| `--model` | `qwen3:8b` | Ollama model name |
| `--host` | `http://127.0.0.1:11434` | Ollama daemon |
| `--max-steps` | `20` | Model turns. A turn that still wants tools after this stops. |
| `--timeout` | `180` | Wall-clock seconds for the whole run |
| `--max-errors` | `3` | Consecutive tool errors (a success resets the count) |
| `--tools` | (see below) | Comma-separated names to **add** to the allowlist. Repeatable. |
| `--rules` | (none) | Operator protocol file appended to the system prompt. Repeatable. |
| `--prompt` | `docs/OLLAMA_AGENT_PROMPT.md` | Replaces the default rules file |
| `--dry-run` | off | Print tools and prompt. No `/api/chat` call and no preflight. |
| `--no-preflight` | off | Skip the `plane_status` call that runs before the model. |

Each run appends a JSONL transcript at `receipts/ollama-agent/<UTC timestamp>.jsonl` (gitignored) and prints a short trace on stdout. The model is called with `think: false`.

## Tools

The harness calls `list_tools` on the stdio server and exposes the **intersection** of the allowlist and those exact names. A candidate the server did not advertise is dropped. The model never receives a name the server did not list.

Pack names in the allowlist (`shell.read_file`) match the FastMCP name (`shell_read_file`) by turning dots into underscores. At call time the match is exact: if the model sends `shell.read_file` after it was shown `shell_read_file`, that call is a local miss and is not forwarded.

Default allowlist:

| Pack tool | MCP name the model sees |
|-----------|-------------------------|
| `plane.status` | `plane_status` |
| `shell.read_file` | `shell_read_file` |
| `shell.list_dir` | `shell_list_dir` |
| `shell.stat` | `shell_stat` |
| `desktop.status` | `desktop_status` |
| `desktop.screenshot` | `desktop_screenshot` |
| `desktop.layout` | `desktop_layout` |
| `cua.observe` | `cua_observe` |

`shell_stat` and `desktop_status` are thin wrappers added so those read-only pack tools have a `list_tools` name. They are not a second gate.

`--tools shell_exec` widens the list. The name still has to be advertised. `--tools plane_call` exposes the general dispatcher, which can invoke any pack tool, including high-blast ones. This harness strips `operator_confirm` inside `arguments_json`, and it does **not** re-check the inner tool name. Leave `plane_call` off unless that is what you mean.

## Loop

1. Call `plane_status` before the model speaks. The trace prints the actor and whether a freeze is engaged. A status body that *reports* a freeze does not stop the run. A gate FREEZE, any other denial, or a failed status does, and the model is not called. `--no-preflight` skips this. `--dry-run` does not call it.
2. Send the task, the system prompt, and the exposed tool schemas to `POST /api/chat`.
3. Parse `message.tool_calls`. If that list is empty, also parse `<tool_call>` blocks in `content` (a JSON `{"name","arguments"}` object, or Qwen `<function=...><parameter=...>`). Prose that merely names a tool is not a call. Parsed names still have to be exact exposed names.
4. No tool calls: print the answer and stop.
5. Otherwise dispatch each call, append `{"role":"tool","tool_name":...,"content":...}`, and repeat.

Stops, without another model turn and without retrying the call:

- **Unknown tool.** The name is not in the exposed list. The plane is not called. The model receives a local `TOOL_NOT_EXPOSED` error that lists the valid names. Three such misses end the run. This is what keeps a hallucinated name from becoming an `UNKNOWN_TOOL` receipt and tripping agent-soc's spray freeze.
- **FREEZE or any other plane denial.** The verdict is reported and the loop stops.
- **`HUMAN_CONFIRM_REQUIRED`.** `operator_confirm` is removed from the arguments (including a JSON string under `arguments_json`) before dispatch. The model cannot set it. If the plane still says a human has to confirm, the harness stops and prints the tool and arguments the model wanted.
- **Limits.** `--max-steps`, the wall-clock `--timeout`, or `--max-errors` consecutive tool failures. An Ollama connection failure stops immediately.

`plane_status` is allowed to *report* that a freeze is engaged. That successful status call is not itself a FREEZE denial, and the loop does not treat it as one.

## Closeout

After the model answer, or after a stop, the harness prints `HARNESS VERIFIED`. Tested, Results, Live-proof, and Gaps are taken from the preflight and the tool calls this process dispatched. A tool that was rejected locally is listed as not forwarded. The model's own VERIFIED block stays in the answer; it is not the record. Live-proof is the transcript path and the task string to re-run, not a claim that the plane was proven beyond this process.

## Honest ceiling

- **Prototype.** One Python file, a mocked test loop, and a stdio client. It is not a second Codex.
- **Small-model reliability.** `qwen3:8b` drops tool-call format, invents names, and stops early. The spray guard then ends the run on purpose. A clean VERIFIED block from this model is not evidence the plane was exercised correctly; the transcript is.
- **Stdio actor is local trust, not a security boundary.** Whoever launches the process picks `--actor ollama`. There is no bearer. Receipts will say `ollama` if the operator added the name and the harness started the server. AdaptiveGate, FREEZE, `operator_confirm`, and the leash ports are unchanged. A different client can still call the plane without this harness.
- **The allowlist is this process's courtesy.** It keeps the model off tools it was not shown. It is not the pack, and it is not agent-soc. Widening with `--tools` is an operator action.
- **Human gates are enforced here by stripping and stopping.** The pack and the handlers remain the authority for a call that does reach them.
- **Not claimed.** Unattended computer use, auto-post, a freeze that covers native OS tools outside this process, or parity with Claude or Codex on the same plane.
