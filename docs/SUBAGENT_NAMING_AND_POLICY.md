# Subagent naming + policy contracts

Source: Grok history mine Batch 2.1 — Helmholtz conversation  
`https://x.com/i/grok?conversation=2083625356167405981` (operator own quote of Codex orchestration UI).

## Pattern observed (Codex / multi-agent UIs)

- **Scientist / role names** for specialists (e.g. “Helmholtz”) beat generic `worker-3`
- Spawn brief carries a **policy contract**: paths, artifact checks (ZIP alignment), verification gates
- Main orchestrator keeps the board (files / tests / integration); specialists run sandboxed

## How this maps to our stack

| Pattern | Our equivalent |
|---------|----------------|
| Named specialist | CUA session label / spawn description; future `specialist_name` |
| Policy contract | force-mediated path, AdaptiveGate, claim ceiling, dry-run respond |
| Sandbox + verify | proof_suite, purple fixtures, lockfile-scan `--affected` |

## Product guidance (light)

1. When spawning any subagent or CUA session, give it a **role name** and **3–7 contract bullets** (what it may touch, what it must prove, what it must not claim).
2. Prefer names that encode *function* (integrity, forensics, claim-gate) over opaque IDs.
3. Do **not** paste Grok-generated agent code blindly — verify against live repos.

## Status

Doc only. No runtime API change required this pass.  
Related: `GROK_PLUGIN_MCP_SKETCH.md`, `FORCE_MEDIATED_PATH.md`, `agent-soc/specialists.py`.
