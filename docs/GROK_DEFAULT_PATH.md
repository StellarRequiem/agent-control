# Grok default path — V1 ambient under leash

**Pursuit:** `~/ops/CONTROL_STACK_V1_PURSUIT.md` · **SOP:** `docs/V1.md`

**Default operating path for plane / GUI / high-blast work on this host.**

```
1. agent-control up / grok_session.py   (bridges + desktop arm)
2. agent-soc status                     (posture)
3. agent-control plane.status / stack
4. route task                           (plane.route)
5. if multi-step GUI:  cua.start → observe (incl. layout) → step* → stop
6. browser.* / desktop.* via agent-control (not raw leash unless debug)
7. high-blast: never invent operator_confirm
8. end of day: cli.py down (+ optional agent-soc watch stop)
```

## Why

- **One-command lifecycle** — cold start without manual nohup  
- **Receipts + AdaptiveGate** on plane tools  
- **Session CUA budget** (V1: 40 / 30m) instead of open-ended RPA  
- **agent-soc** detects high-blast churn / deny spikes  
- **Layout first** — every CUA observe includes window geometry  

## Desktop GUI (tight control)

```bash
python3 ~/agent-control/cli.py call desktop.layout
python3 ~/agent-control/cli.py call desktop.screenshot_window --args-json '{"app":"Google Chrome"}'
python3 ~/agent-control/cli.py call desktop.click_window --args-json '{"app":"Google Chrome","rel_x":0.92,"rel_y":0.88}'
```

See `~/desktop-leash/docs/LAYOUT_CONTROL.md`.

## Commands (copy-paste)

```bash
# Preflight (V1)
python3 ~/agent-control/grok_session.py --start-cua
# or:
python3 ~/agent-control/cli.py up
python3 ~/agent-control/cli.py stack
python3 ~/agent-control/cli.py smoke

# Route
python3 ~/agent-control/cli.py route --task "your task here"

# CUA session (GUI multi-step; defaults 40 steps / 1800s)
python3 ~/agent-control/cli.py call cua.start
python3 ~/agent-control/cli.py call cua.observe
python3 ~/agent-control/cli.py call cua.step --args-json '{"tool":"desktop.focus","arguments":{"app":"TextEdit"}}'
python3 ~/agent-control/cli.py call cua.stop

# End of day
python3 ~/agent-control/cli.py down

# Continuous SOC (background)
# python3 ~/agent-soc/cli.py watch --interval 30
# optional: --auto-respond-high  (FREEZE only unless AGENT_SOC_AUTO_DISARM=1)
```

## Direct leash CLIs

Use only for debug when agent-control is wrong; prefer host for agent work.

## Claim

Session CUA + stack lifecycle + agent-plane SOC — **not** ambient unlimited OS control / enterprise SOC / auto-post.
