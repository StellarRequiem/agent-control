# Claim ladder — mediated control plane

**Living contract.** Promote claims only when the evidence checklist is green.  
**Updated:** 2026-08-04  
**Related:** `docs/paper/STRONG_PROOF_BACKLOG.md` · `CLAIMS.md` · `docs/MEDIATED_AMBIENT.md`

## Rule

```
target claim → evidence checklist → build → try to break → CLAIMS.md + plane.status
  → only then public wording
```

Never market a higher rung than evidence. Site copy stays **weaker** than this ladder.

---

## Rungs

| # | Today (honest) | Target | Evidence to promote |
|---|----------------|--------|---------------------|
| R0 | Plane tools gated; file edits native | — baseline | MCP host + AdaptiveGate smoke |
| R1 | Shell subset + bash deny *when configured* | **Mediated agent work path** | Live matrix; CI offline proof; durable receipts |
| R2 | Session CUA budgeted | **Production multi-step CUA under leash** | Layout/D4 matrix; flake budget; budget-exhaust proof |
| R3 | Abhorrent FREEZE + synthetic hit table | **Measured detector (holdout)** | N≥100; held-out 20%; P/R with method; ops FP log |
| R4 | Agent-plane SOC | **Operator-grade agent-plane SOC** | Multi-day metrics; clear non-SIEM scope; optional export |
| R5 | Works on this Mac | **Independent re-run** | Third machine script; signed releases; 15-min bring-up |
| R6 | Grok-centric wire | **Portable authority plane** | Second runtime adapter; shared gateway fixtures |

### Permanently out of scope (do not climb)

- “Stops all agent attacks”
- Unlimited human-equivalent CUA / ambient OS takeover
- Enterprise SIEM/EDR rebrand
- Every process on the Mac gated without product-partner OS hooks

---

## Phase A (this sprint) — harden the current ceiling

| Work | Status | Unlocks |
|------|--------|---------|
| Receipt re-sync + flock multi-writer | **done** (mcp-assure) | Durable mediated ambient |
| CHAIN_BROKEN does not grow poison file | **done** | Recovery without manual truncate races |
| `plane.receipts_status` / `plane.receipts_rotate` | **done** | Chain repair without native bash |
| `plane.unfreeze` under FREEZE allow | **done** | FREEZE recovery without bash |
| Proof suite isolated receipts | **done** | No MCP/proof race |
| agent-control CI offline board | **done** (workflow) | R1 evidence |
| Ops log template | **done** (agent-soc/ops_log) | R3/R4 ops metrics |
| Holdout design for hit_table | **done** (design + flag) | Path to R3 |
| CLAIM_LADDER.md | **done** | Explicit promotion process |

## Phase B (next) — promote 2–3 ceilings

1. **Shell/FS depth** — enough gated `shell.*` that real agent work never needs native edits.  
2. **Corpus 100+ + holdout** — still no public % until study design green.  
3. **Third-machine re-run doc** — portable proof.  
4. **Weekly ops log discipline** — freeze FP / MTTR / arm-hours.

## Phase C (stretch)

External RT · semantic host policy · multi-runtime · gateway fixture benchmark.

---

## Promotion checklist (all that apply)

1. **Tested** — CI green  
2. **Live-proof** — dated board or transcript  
3. **Honest gaps** — residual bypasses listed  
4. **Calibrated** — rates only with holdout + base rate  
5. **Re-runnable** — stranger can reproduce from docs  

Fail any → stay on current rung.

---

## Operator quick recoveries (mediated)

| Symptom | Action |
|---------|--------|
| FREEZE stuck | MCP `plane_unfreeze` (or `plane.unfreeze`) |
| CHAIN_BROKEN | MCP `plane_receipts_status` → `plane_receipts_rotate` → retry |
| Need offline board | `shell_run agent_control_proof_offline` or `python3 smoke/proof_suite.py --offline` |

---

## Claim-safe one-liners by rung

| Rung | OK to say |
|------|-----------|
| R0–R1 | Local assured host: plane tools pass AdaptiveGate; arm-gated leashes; bash deny when configured; file edits may remain native. |
| R2 | Budgeted session CUA under arm/allowlist — not unlimited RPA. |
| R3 | Abhorrent shapes FREEZE; synthetic hit table re-runnable; **not** a published detection rate until holdout study. |
| R4 | Agent-plane collect/detect/respond — **not** enterprise SOC. |
