# How architecture upgrades claims

Map: overclaim → real architecture → allowed wording after proof.

| Forbidden overclaim | What we built | Allowed after smoke green |
|---------------------|---------------|---------------------------|
| Every Grok tool is gated | `AssuredPlaneHost` for **plane** tools only | “Control-plane tools (browser/desktop/plane.*) route through mcp-assure AdaptiveGate on this host” |
| Full CUA no limits | desktop handlers + profiles + dual D4 | “Arm-gated allowlisted desktop actions with host+leash human confirms on high-blast” |
| Auto-posts to X | `PublishPipeline` + `operator_confirm` | “Draft/publish pipeline with mandatory human confirm at host and leash” |
| Full SOC / stops all attacks | Not in scope | Unchanged refuse — gate + leashes are not a SOC |

## Proof command

```bash
python3 ~/agent-control/cli.py smoke
# cannot_bypass_planes=PASS
```

## Next architecture (still to build)

1. **Grok host integration** — make Build session prefer `agent-control` for plane tools (skill SOP + optional wrapper scripts).  
2. **Optional shell high-blast pack** — gated subset only (never ambient `bash`).  
3. **Desktop phase 5** — AX tree, richer profiles, dual-control session time-box.  
4. **browser Post enable** — improve fill until Post enables; still never skip human confirm.  
5. **Public open-source** decision for leashes (separate product claim).
