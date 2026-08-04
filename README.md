# agent-control

**Local assured host** for Grok’s control planes: **mcp-assure** gate → **browser-leash** / **desktop-leash** handlers.

Not a full SOC. Not ambient computer use. Not auto-post to X.

```
python3 ~/agent-control/cli.py status
python3 ~/agent-control/cli.py smoke
```

## Why this exists

Claim ceilings only move when **architecture and code** enforce them:

| Goal | Mechanism |
|------|-----------|
| Plane tools gated | `AssuredToolDispatcher(adaptive=True)` — handlers only after ALLOW |
| Right surface | `plane.route` |
| Human publish | `browser.x_post` needs `operator_confirm=true` + leash confirm |
| Human high-blast desktop | quit/Return need `operator_confirm=true` + desktop D4 |
| App policy | `profiles/desktop_apps.json` (plus leash allow/deny) |

## Quick start

```bash
# bridges (separate terminals or nohup)
python3 ~/browser-leash/bridge/server.py &
python3 ~/desktop-leash/bridge/server.py &

python3 ~/agent-control/cli.py status
python3 ~/agent-control/cli.py route --task "screenshot the desktop"
python3 ~/agent-control/cli.py call desktop.screenshot --args-json '{}'
python3 ~/agent-control/cli.py call browser.x_post --args-json '{"operator_confirm":false}'
# → HUMAN_CONFIRM_REQUIRED (by design)
```

## Docs

- `docs/CLAIM_LADDER.md` — how claims promote from ceiling → target (evidence checklist)
- `docs/MEDIATED_AMBIENT.md` — force routing + FREEZE/CHAIN recovery
- `ARCHITECTURE.md` — diagram and contracts  
- `docs/CLAIMS_PATH.md` — claim upgrade map  
- `~/desktop-leash/docs/CLAIMS.md` — stack hard refuses  
- `~/mcp-assure/CLAIMS.md` — package claims  

## Skill

`/agent-control` → `~/.grok/skills/agent-control/SKILL.md`


## License

Apache-2.0

## Related

- [mcp-assure](https://github.com/StellarRequiem/mcp-assure) — tool-call gate
- [browser-leash](https://github.com/StellarRequiem/browser-leash) — Chrome plane
- [desktop-leash](https://github.com/StellarRequiem/desktop-leash) — macOS desktop plane
- [agent-soc](https://github.com/StellarRequiem/agent-soc) — agent-plane SOC
