# Publishing plan — Mediated Agent Control Plane paper

**Paper:** `2026-08-mediated-agent-control-plane.md`  
**Author surface:** StellarRequiem · security@xclusivexo.com · xclusivexo.com  
**Date:** 2026-08-03  

---

## Recommended sequence (ROI + honesty)

| Order | Venue | Why | Effort | Gate |
|------:|-------|-----|--------|------|
| **1** | **xclusivexo.com** long-form / assurance page | You own the claim ladder; live proof links; professional inbound | Low–med | Operator ship-site; claim-gate pass |
| **2** | **arXiv** (cs.CR + cs.AI) | Citeable preprint; matches “working paper”; peers MCP-Secure-class work | Med | Clean PDF; no PII; repo links only |
| **3** | **GitHub** monorepo or paper/ folder + README pointer | Reproducibility default for this audience | Low | Already have repos; add paper path |
| **4** | **X thread** (claim-safe abstract + links) | Distribution, not archival | Low | Human Post; no overclaim |
| **5** | **Workshop / industry talk** | MCP Dev Summit, RSAC-adjacent, CSA/CoSAI community | Med–high | Abstract deadline; talk not product pitch |
| **6** | **Academic venue** (later) | IEEE/ACM agent-security or usable security | High | Stronger eval section; related-work depth |

**Do not lead with:** Reddit self-promo-heavy subs; “we stop all agent attacks” abstracts; metrics without studies.

---

## Venue notes

### A. Site (primary professional surface)

- Add `/papers/` or expand `/assurance/` with abstract + PDF/HTML.  
- Link mcp-assure PyPI + five GitHub repos.  
- Keep homepage claims **weaker** than paper (paper is detailed; site is ceiling-safe).  
- Ship via portfolio Pages only on explicit `/ship-site` ask.

### B. arXiv

- **Categories:** primary `cs.CR`, cross-list `cs.AI` or `cs.SE`.  
- **Format:** export MD → LaTeX or pandoc PDF; 8–12 pages is fine for a systems/experience paper.  
- **License:** match Apache-2.0 code where possible; arXiv non-exclusive.  
- **Authors:** Alex Price / StellarRequiem; contact security@ only.  
- **Positioning:** “systems architecture + open artifacts + verification method,” not “ML accuracy paper.”

### C. Related academic/industry context (for positioning)

- Host-side MCP least-privilege wrappers (e.g. MCP-Secure-class IEEE work).  
- NSA / CSA MCP security design guidance (cite carefully; we are local mediation, not full enterprise AS).  
- Computer-use product stacks (Claude/Codex)—differentiate **control philosophy**, not feature cloning.

### D. Talks / workshops

- **MCP Dev Summit** (LF) workshops — practical host mediation demo.  
- Security practitioner tracks: “deny-by-default tool plane + leashes.”  
- Demo script: smoke → FREEZE → navigate DENY → clear → session surface.

### E. What we skip (for now)

| Venue | Why skip first |
|-------|----------------|
| Top-tier ML conferences | Wrong eval shape (no leaderboard story) |
| “Full SOC product” marketing sites | Claim violation |
| Unsolicited vendor comparison pages | Stick to architecture + evidence |

---

## Pre-publish checklist

- [x] Working paper drafted (claim-safe)  
- [ ] Operator read-through (tone + any private paths scrubbed)  
- [ ] PDF build (pandoc or typst)  
- [ ] All repo URLs 200; PyPI install proof  
- [ ] Figures: one architecture diagram (optional image_gen or export from ASCII)  
- [ ] claim-gate / verity pass on abstract numbers (there should be **no** win-rate %)  
- [ ] Site page draft  
- [ ] arXiv account + endorsement if needed  
- [ ] Explicit operator OK to publish each surface  

---

## Suggested abstract (≤150 words, for arXiv)

> Agent tool use and computer-use interfaces create a trust boundary where models propose privileged actions. We present a mediated control plane that separates capability from authority: a deny-by-default runtime gate for MCP-style tool calls (mcp-assure), arm-gated local leashes for Chrome and macOS desktop input, an assured host that routes plane tools through AdaptiveGate, and an agent-plane detector that FREEZEs on abhorrent tool shapes. Infrastructure may be always available while session authority remains arm-gated and high-blast actions remain dual-controlled by humans. We report a verification method based on re-runnable purple fixtures, cannot-bypass smoke tests, and operator hold-tests rather than unmeasured detection rates. We explicitly do not claim enterprise SOC coverage, unlimited computer use, or gating of native host shells outside the mediated path. Open artifacts accompany the design.

---

## Next actions (pick order)

1. **Operator review** of `2026-08-mediated-agent-control-plane.md`  
2. **PDF export** + architecture figure  
3. **Site page** under portfolio (ship only when asked)  
4. **arXiv submit** when PDF ready  
5. Optional: short **X** pointer post after site/arXiv live  

---

## Claim reminder

Publishing **increases** scrutiny. Every public sentence must remain ≤ evidence in CLAIMS.md files. Prefer “working paper / open systems report” over “peer-reviewed results” until a venue review exists.
