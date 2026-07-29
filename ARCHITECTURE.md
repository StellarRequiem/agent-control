# agent-control — architecture

**Role:** local host that makes control-plane claims true in *code*, not docs.

```
Grok / CLI
    │
    ▼
AssuredPlaneHost          (this repo)
    │  AdaptiveGate + AssuredToolDispatcher (mcp-assure)
    │  policy: packs/local_planes.json
    │  receipts: receipts/plane-host.jsonl
    │
    ├── browser.*  → browser-leash :8756
    ├── desktop.*  → desktop-leash :8757
    └── plane.*    → status + router (no ambient authority)
```

## Surfaces we are building toward

| Ambition (honest form) | Architecture here |
|------------------------|-------------------|
| Tool calls gated | Plane tools **only** via `AssuredPlaneHost.call` — cannot-bypass dispatcher |
| Not ambient CUA | desktop-leash arm + allowlist + profiles + D4; host dual-gate on quit/Return |
| Not auto-post | `PublishPipeline` + `browser.x_post` requires `operator_confirm=true` **and** leash post confirm |
| Not full SOC | Runtime gate + leashes only — no SIEM/EDR claim |
| Right plane | `plane.route` heuristic → shell / browser / desktop / claim-gate |

## What is still *not* true

- **Every Grok Build shell tool** is gated — only tools that route through this host  
- **Public product** for browser/desktop leashes — local  
- **Human-equivalent unlimited CUA** — explicitly refused by design  

## Human gates (non-negotiable)

| Action | Host gate | Leash gate |
|--------|-----------|------------|
| `browser.x_post` | `operator_confirm=true` | ARM + `require_post_confirm` |
| `desktop.quit` | `operator_confirm=true` + profile | D4 confirm queue |
| `desktop.press` return/enter | `operator_confirm=true` | D4 confirm queue |

## Files

| Path | Purpose |
|------|---------|
| `host/plane_host.py` | AssuredPlaneHost |
| `host/router.py` | Task → plane |
| `host/publish_pipeline.py` | X draft/post state machine |
| `host/browser_handlers.py` | Leash HTTP |
| `host/desktop_handlers.py` | Leash HTTP + profiles |
| `packs/local_planes.json` | Deny-by-default catalog |
| `profiles/desktop_apps.json` | Per-app policy (phase-5 start) |
| `smoke/cannot_bypass_planes.py` | Proof suite |
| `cli.py` | Operator/agent entry |

## Usage

```bash
python3 ~/agent-control/cli.py status
python3 ~/agent-control/cli.py route --task "draft on X"
python3 ~/agent-control/cli.py call browser.navigate --args-json '{"url":"https://xclusivexo.com"}'
python3 ~/agent-control/cli.py smoke
```

## Claim discipline

See `docs/CLAIMS_PATH.md` and `~/desktop-leash/docs/CLAIMS.md`.
