# File mutation plane (GAP_BRIDGE G1)

## Status (2026-08-04)

| Layer | Status |
|-------|--------|
| `shell.write_file` | **done** — roots, secret names, size, create/overwrite, FREEZE deny |
| `shell.apply_patch` | **done** — exact str replace (StrReplace analog), FREEZE deny |
| Pack tools | `local_planes` v13 |
| MCP | `shell_write_file`, `shell_apply_patch` on agent_control |
| Tests | `tests/test_shell_write_gate.py` (write + patch + freeze) |
| Native Write/StrReplace denied in Grok | **not yet** — claim still `file_edit_tools_native: true` |

## How to use (agents)

Prefer plane tools over native edit when editing under allowlisted roots:

```text
shell.write_file  {path, content, mode?}
shell.apply_patch {path, old_string, new_string, replace_all?}
```

Via MCP (Claude/Grok):

```text
shell_write_file / shell_apply_patch
# or plane_call tool=shell.write_file …
```

## FREEZE

Neither write tool is on `freeze_allow`. Under FREEZE → gate DENY → **nothing written**.

## Honest claim ceiling

- **Available:** mediated write plane under roots (`file_edit_plane_available`)
- **Not yet:** “all agent file mutations go through the gate” — native Grok/Claude edit tools still exist until permission deny is configured for those tool names
- **Next:** Grok `[permission] deny` patterns for Write/StrReplace when supported; Claude remains observe-only

## Soft policy (until native deny)

Skills + AGENTS: prefer `shell.write_file` / `shell.apply_patch` for product trees under plane roots.
