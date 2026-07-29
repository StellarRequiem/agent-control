# Grok default path — CUA + SOC first

**Default operating path for plane / GUI / high-blast work on this host.**

```
1. agent-soc status          (posture)
2. agent-control plane.status
3. route task                (plane.route)
4. if multi-step GUI:        cua.start → observe → step* → stop
5. browser.* / desktop.* via agent-control (not raw leash unless debug)
6. high-blast: never invent operator_confirm
7. end of day: DISARM + optional agent-soc watch stop
```

## Why

- **Receipts + AdaptiveGate** on plane tools  
- **Session CUA budget** instead of open-ended RPA  
- **agent-soc** detects high-blast churn / deny spikes  
- **Layout first** — never full-screen click guessing (Terminal/Chrome split)  

## Desktop GUI (tight control)

```bash
python3 ~/desktop-leash/bridge/client.py layout
# frames_by_app: Chrome x=959 w=961 · Terminal x=0 w=960  (example split)

python3 ~/desktop-leash/bridge/client.py shot-window --app "Google Chrome" --out /tmp/chrome.png
python3 ~/desktop-leash/bridge/client.py click-window --app "Google Chrome" --rel-x 0.92 --rel-y 0.88
```

See `~/desktop-leash/docs/LAYOUT_CONTROL.md`.

## Commands (copy-paste)

```bash
# Preflight
python3 ~/agent-soc/cli.py status
python3 ~/agent-control/cli.py status
python3 ~/agent-control/cli.py smoke

# Route
python3 ~/agent-control/cli.py route --task "your task here"

# CUA session (GUI multi-step)
python3 ~/agent-control/cli.py call cua.start --args-json '{"max_steps":20,"max_seconds":900}'
python3 ~/agent-control/cli.py call cua.observe
python3 ~/agent-control/cli.py call cua.step --args-json '{"tool":"desktop.focus","arguments":{"app":"TextEdit"}}'
python3 ~/agent-control/cli.py call cua.stop

# Continuous SOC (background)
# python3 ~/agent-soc/cli.py watch --interval 30
# optional: --auto-respond-high  (FREEZE only unless AGENT_SOC_AUTO_DISARM=1)
```

## Direct leash CLIs

Use only for debug when agent-control is wrong; prefer host for agent work.

## Claim

Session CUA + agent-plane SOC on default path — **not** ambient unlimited OS control / enterprise SOC.
