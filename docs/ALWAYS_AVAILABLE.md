# Always available — not always armed

**Phase B policy.** Infrastructure can run at login. **Authority stays off until you ARM.**

| Surface | Always on? | Authority |
|---------|------------|-----------|
| browser-leash bridge `:8756` | Yes (launchd KeepAlive) | No until Chrome popup **ARM** |
| desktop-leash bridge `:8757` | Yes (launchd KeepAlive) | No until `arm` / `cli.py up` |
| agent-soc watch | Optional | Freeze-only by default (`AGENT_SOC_AUTO_DISARM=0`) |
| Auto-post / invent confirm | **Never** | Human high-blast only |

## Install

```bash
# Bridges only (recommended)
bash ~/agent-control/scripts/always_available.sh install

# + freeze-only SOC watch
INSTALL_SOC_WATCH=1 bash ~/agent-control/scripts/always_available.sh install

# Status
python3 ~/agent-control/cli.py available
# or
bash ~/agent-control/scripts/always_available.sh status
```

## Uninstall

```bash
bash ~/agent-control/scripts/always_available.sh uninstall
```

## Work day

```bash
python3 ~/agent-control/cli.py available   # available=true (infra)
# Soft Reload extension if version mismatch
# Chrome → Browser Leash → ARM
python3 ~/agent-control/cli.py up          # desktop sticky arm (or arm only)
# … ambient browser + CUA under host …
# End of day:
# Chrome → DISARM
python3 ~/agent-control/cli.py down        # optional if not using launchd
```

With launchd, **do not** `down` to kill bridges unless you want them off — use **DISARM** to drop authority and leave bridges up.

## Claims

> Bridges may be always available. Session control still requires arm. Not 24/7 ambient OS takeover. Abhorrent lockdown is Phase C.
