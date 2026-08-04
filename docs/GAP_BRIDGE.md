# Gap bridge map — Grok Build mediated quality

**Updated:** 2026-08-04  
**Purpose:** How we close residuals that still weaken Grok Build / claim ceilings.  
**Rule:** promote claim only when evidence is green (see `CLAIM_LADDER.md`).  
**Handoff freeze:** `~/ops/POSITION_FREEZE_2026-08-04.md` — Claude harden work starts from this plan; do not reopen settled Phase A.

Live ceiling today (`plane.status`):

| Flag | Value |
|------|--------|
| `plane_tools_gated` | true |
| `native_runtime_shell_gated` | true (bash deny + MCP) |
| `file_edit_tools_native` | **true** ← primary remaining hole |
| `every_grok_tool_gated` | **false** |
| `full_cua_unlimited` | false (by design) |
| `enterprise_soc` | false (by design) |

---

## Gap inventory → bridge

### G1 — File edits still native (Write / StrReplace / etc.)

| | |
|--|--|
| **Why it hurts** | FREEZE and AdaptiveGate do not see file mutations; largest bypass of “mediated work path.” |
| **Target claim** | “On this host, agent file mutations under allowlisted roots go through AssuredPlaneHost.” |
| **Bridge options** | **A (product):** Grok `[permission] deny` on native edit tools + MCP `shell.write_file` / `shell.apply_patch` under roots, size/path policy, receipts. **B (soft):** skill/AGENTS force plane writes only (honor system, not hard). **C (hybrid):** deny Write in config when Grok supports pattern; keep soft routing until then. |
| **Evidence** | Deny native edit live; plane write ALLOW under root; path traversal DENY; FREEZE blocks write; offline + live board items. |
| **Pri** | **P0** — biggest Grok Build quality jump |
| **Dependency** | Confirm which tool names Grok permission engine can deny (`Write(*)`, `search_replace`, …). |

### G2 — Not every Grok tool gated

| | |
|--|--|
| **Why it hurts** | Subagents, other MCPs, image tools, etc. remain outside agent-control. |
| **Target claim** | “High-blast and FS/shell/GUI planes are mediated; other tools listed as out-of-band.” |
| **Bridge** | Inventory all tool classes; classify **must-gate / optional / never-gate**. Expand pack only for must-gate. Document permanent outs (e.g. pure LLM, memory). Do **not** claim every_grok_tool_gated until inventory is closed. |
| **Evidence** | Tool inventory table in CLAIMS + `plane.status` fields per class. |
| **Pri** | **P1** |

### G3 — MCP code drift (disk ≠ live process)

| | |
|--|--|
| **Why it hurts** | Fixes (receipts flock, unfreeze, named cmds) invisible until reload; wasted recovery time. |
| **Target claim** | “Session start loads current host code; version/receipt tip visible in plane.status.” |
| **Bridge** | **Post-restart checklist** (below). Add `plane.status` → `host_code` (git short SHA or pack version + receipts tip). Optional: skill preflight `grok_session.py` prints pack version. |
| **Evidence** | After cold boot, `plane.status` shows pack v10+ and new tools; offline board green. |
| **Pri** | **P0** for ops; **P1** for version surface |

### G4 — Shell/FS depth still thinner than native agent work

| | |
|--|--|
| **Why it hurts** | Even with bash deny, work that needs write/patch still leans on native edits (G1). |
| **Target claim** | Same as G1 + “named cmds cover proof/commit/test loop.” |
| **Bridge** | `shell.write_file` / `shell.apply_patch` (rooted, size-capped); optional `git push` only via marker (already pattern); expand roots carefully; never interpreters in exec. |
| **Evidence** | Full edit→test→commit loop without native Write. |
| **Pri** | **P0** coupled to G1 |

### G5 — FREEZE doesn’t stop out-of-band tools

| | |
|--|--|
| **Why it hurts** | Operator thinks “lockdown” = all agent power off; native edits/other MCP still run. |
| **Target claim** | “FREEZE blocks plane host tools; lockdown engagement optionally denies broader permission set.” |
| **Bridge** | Document honest freeze scope. Optional: lockdown engage also toggles Grok permission deny list via operator script (not auto from agent). |
| **Evidence** | Hold-test: FREEZE + attempt native Write still works until G1; after G1, Write denied. |
| **Pri** | **P1** (honesty now; hard couple after G1) |

### G6 — Receipt multi-process / long session robustness

| | |
|--|--|
| **Status** | Mostly **done** (flock, re-sync, rotate, skip poison append). |
| **Residual** | Rare races; tip growth unbounded. |
| **Bridge** | Rotate policy by size/age; `plane.receipts_status` in session preflight; CI keeps multi-process test. |
| **Pri** | **P2** |

### G7 — CUA idle / budget not “product-grade” proof

| | |
|--|--|
| **Why it hurts** | Multi-step GUI quality is real but under-proven in CI. |
| **Target claim** | R2 session CUA under leash with flake budget. |
| **Bridge** | Offline mocks for layout-first; live hold-test matrix; budget exhaust proof. |
| **Pri** | **P2** |

### G8 — Detector not a measured study

| | |
|--|--|
| **Status** | N=100 synthetic + holdout split **tooling**; no public %. |
| **Bridge** | Ops log weekly; holdout freeze when labels stable; only then P/R wording. |
| **Pri** | **P2** for science; not blocking Grok Build daily quality |

### G9 — Full OS lockdown / every process gated

| | |
|--|--|
| **Status** | **Permanently out of scope** without OS partner hooks. |
| **Bridge** | Keep claim language: configured agent runtime path, not Mac lockdown. |
| **Pri** | **Do not climb** |

---

## Recommended sequence (after computer restart)

### Immediate (same day) — load what we already built

1. Cold boot → start bridges if not launchd → Soft Reload + **ARM** browser/desktop if GUI work.  
2. Open Grok → confirm MCP `agent_control` connects (19+ tools).  
3. Live matrix (10 min):

```text
plane_status          → native_runtime_shell_gated true, file_edit still true
native bash           → DENY
shell_run git_status  → ALLOW
plane_receipts_status → INTACT
agent_control_proof_offline → 10/10
```

4. Log result in `agent-soc/ops_log/` for the week.  
5. **Do not** expand public claims until G1 evidence exists.

### Sprint 1 — close G1/G4 (file mutation plane)

| Step | Deliverable |
|------|-------------|
| 1.1 | Enumerate Grok edit tool names; test which `permission.deny` patterns work |
| 1.2 | Implement `shell.write_file` + `shell.apply_patch` (roots, max bytes, no secrets paths) |
| 1.3 | Pack + MCP tools + freeze_allow policy (writes blocked under FREEZE except status) |
| 1.4 | Skill/AGENTS: prefer plane write; after deny works, native edits blocked |
| 1.5 | Proof board: write allow/deny, FREEZE blocks write, path traversal |
| 1.6 | Flip claim_ceiling `file_edit_tools_native: false` only when deny+plane green |

### Sprint 2 — G2/G3/G5 hygiene

| Step | Deliverable |
|------|-------------|
| 2.1 | Full Grok tool inventory → gate class table |
| 2.2 | `plane.status` host pack version + git short SHA |
| 2.3 | Session preflight (`grok_session.py`) includes receipts + version |
| 2.4 | FREEZE/lockdown doc + optional operator “deep lockdown” permission profile |

### Sprint 3 — R2/R3 quality (not daily blocker)

| Step | Deliverable |
|------|-------------|
| 3.1 | CUA layout/D4 offline matrix |
| 3.2 | Holdout study freeze only if you want public metrics (optional) |
| 3.3 | Third-machine live paste into ops_log |

---

## Post-restart checklist (print / pin)

```
[ ] Machine cold boot complete
[ ] browser-leash / desktop-leash up (launchd or manual)
[ ] Chrome extension Soft Reload + ARM if needed
[ ] Grok Build starts; agent_control MCP ready
[ ] plane_status OK
[ ] bash DENY
[ ] shell_run git_status ALLOW
[ ] plane_receipts_status INTACT (else plane_receipts_rotate)
[ ] agent_control_proof_offline 10/10
[ ] Note pack version / any missing tools → if stale, MCP already reloaded by reboot; else recheck config
[ ] Ops log line: restart + matrix result
```

---

## Decision points for operator ([YOUR CALL])

| Call | Options |
|------|---------|
| **G1 hardness** | Soft skill-only vs hard `permission.deny` on edit tools (prefer hard if Grok supports it) |
| **Write surface** | Whole-file write only vs apply_patch/diff |
| **Push policy** | Stay marker-only (current) vs gated `git push` in shell.exec (still no force) |
| **Deep lockdown** | FREEZE plane-only vs script that also expands permission deny set |

---

## Success picture (honest)

After Sprint 1: Grok Build agent can **inspect, edit under roots, test, commit, push-on-ask** entirely through the plane + config denials—with FREEZE actually stopping FS mutation—not just shell and browser.

After Sprint 2: no more “I fixed it on disk but session still broken” ambiguity; freeze semantics match operator intuition.

Never claimed: whole Mac gated, unlimited CUA, enterprise SOC, unmeasured catch rates.
