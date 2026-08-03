# Phase C — Abhorrent lockdown (mediated plane)

Detect **abhorrent MCP / agentic tool-abuse shapes** on control-plane receipts and **lockdown** (FREEZE ± optional leash disarm).

## What it is

| Is | Is not |
|----|--------|
| Agent-plane detect → FREEZE | Enterprise SIEM / EDR |
| Secret/path/template/shell-spray shapes | Content moderation of all speech |
| Works when tools hit AssuredPlaneHost / leashes | Stops native shell outside the host |
| Freeze-first by default | Auto-disarm unless you pass `--disarm` or env |

## Commands

```bash
# Status (alerts + freeze files + recommendation)
python3 ~/agent-control/cli.py lockdown status
# or
python3 ~/agent-soc/cli.py lockdown status

# Engage only if detectors say high/critical abhorrent
python3 ~/agent-control/cli.py lockdown engage

# Force freeze even if quiet
python3 ~/agent-control/cli.py lockdown engage --force --reason "operator drill"

# Also disarm leashes
python3 ~/agent-control/cli.py lockdown engage --force --disarm

# Clear FREEZE files (operator recovery)
python3 ~/agent-control/cli.py lockdown clear
```

Continuous:

```bash
python3 ~/agent-soc/cli.py watch --interval 30 --auto-respond-high
# disarm only if AGENT_SOC_AUTO_DISARM=1
```

## Abhorrent rules (detect)

| Rule | Severity | Trigger (approx) |
|------|----------|------------------|
| `ABHORRENT_SECRET_SHAPE` | critical | credential-shaped args/details |
| `ABHORRENT_TOOL_SPRAY` | critical | ≥8 UNKNOWN_TOOL probes |
| `ABHORRENT_SHELL_BYPASS` | high | ≥2 shell_exec-shaped attempts |
| `ABHORRENT_PATH_SMELL` | high | ≥2 sensitive-path shapes |
| `ABHORRENT_TEMPLATE_SMELL` | high | ≥2 injection/template shapes |
| `ABHORRENT_HIGHBLAST_SPRAY` | high | ≥6 confirm-required post/quit/return |

Plus existing: DENY_SPIKE, HIGH_BLAST_CHURN, UNKNOWN_TOOL_ATTEMPTS, RISKY_ACTION_SHAPE.

## Recovery

1. `lockdown clear`  
2. Inspect `~/agent-soc/incidents/`  
3. Re-ARM browser/desktop intentionally  
4. Resume work through host only  

## Claim ceiling

> Mediated-plane abhorrent lockdown: freeze agent-control / mcp-assure on high-risk tool shapes from receipts. Not a full SOC; not a guarantee against all agentic abuse.
