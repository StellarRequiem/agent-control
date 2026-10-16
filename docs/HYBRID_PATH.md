# Hybrid control path (batch-1 P0)

**Goal:** High-assurance actions stay on **browser-leash / desktop-leash** (ARM, allowlist, human gates, receipts). Low-risk research browse may use broader tools **only if routed through AdaptiveGate**.

## Default (this workstation)

| Surface | Path |
|---------|------|
| X post / sensitive hosts | browser-leash only |
| GitHub / allowlisted hosts | browser-leash |
| Desktop quit / Return | desktop-leash D4 |
| Shell / FS | agent-control `shell.*` gated — **not** ambient native shell |
| Optional stock browser plugins | **Not** ambient; only if operator installs and still fronts through plane policy |

## Hybrid rules

1. **Never** bypass FREEZE by using a stock plugin while FREEZE is active.  
2. High-blast (publish, quit, broad shell) → leash + confirm.  
3. Low-risk fetch/search → plane tools (`browser.navigate` allowlist, `web_search` in Grok Build) preferred over unrestricted CDP.  
4. If a stock Browser Use plugin is installed for research, constrain via Grok Build permissions **and** keep X/high-stakes on leash.

## Implementation status

- Leash planes: production.  
- AdaptiveGate front door: agent-control.  
- Documented hybrid: this file + `GROK_DEFAULT_PATH.md`.  
- Full dual-plugin wiring is operator opt-in (not default).

## Claim ceiling

Hybrid does **not** mean unlimited CUA. Session-scoped, deny-by-default remains the bar.
