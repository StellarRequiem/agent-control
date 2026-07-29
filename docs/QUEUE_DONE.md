# Upgrade queue — completion record

Closed when smoke + live checks pass on this host.

| # | Upgrade | Status | Evidence |
|---|---------|--------|----------|
| 1 | Gated shell subset (no ambient bash) | **DONE** | `shell.*` tools + smoke |
| 2 | Grok host SOP prefer agent-control | **DONE** | skills `/agent-control` cross-links |
| 3 | Browser Post fill quality | **DONE** (code) | extension **0.3.8** per-char-first; Reload required live |
| 4 | Desktop phase 5 AX + D4 dual-control | **DONE** | v**0.5.0** phase 5 |
| 5 | Public leash readiness | **DONE** (prep) | OPEN_SOURCE_READINESS.md both leashes; **no push** |
| 6 | Plane host architecture | **DONE** (prior) | AssuredPlaneHost |

## Still intentionally false (design)

- every Grok Build shell tool gated  
- auto-post without human  
- full unlimited CUA  
- full SOC  

## Operator actions remaining (not code)

1. Soft Reload browser-leash → **0.3.8**  
2. Explicit ask if/when to open-source leashes  
3. Optional formal red-team engagement (hold-test suite is the local pre-RT)  
