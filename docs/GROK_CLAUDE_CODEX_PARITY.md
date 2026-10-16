# Grok ↔ Claude ↔ Codex control-plane parity

**Updated:** 2026-08-05  
**Claim ceiling:** session-scoped mediated control under arm — **not** unlimited CUA / enterprise RPA.

We do **not** clone Anthropic/OpenAI native messaging hosts. We **do** match the *work surface* agents need day-to-day: navigate, observe, click/type, screenshot, multi-tab, gated shell, local preview.

## Capability matrix (honest)

| Work | Claude | Codex | Grok via agent-control (this host) |
|------|--------|-------|-------------------------------------|
| Chrome navigate / tabs | native ext | native ext | **browser-leash** ARM + host allowlist |
| Page text snapshot | yes | yes | `browser.snapshot` / `browser_snapshot` |
| Click / type / scroll / wait | yes | yes | **first-class MCP** + `plane_call` |
| Page screenshot | yes | yes | **0.5.1** `captureVisibleTab` + write `out` path |
| X draft/post | session tools | session tools | `browser.x_*` + human post confirm |
| Desktop AX / screenshots | Computer Use | computer-use | **desktop-leash** ARM + Screen Recording |
| Shell / tests | product shell | product shell | `shell.exec` (read) + **named** `shell.run` |
| Local site preview | open file/server | open | **portfolio_preview_*** named cmds → `127.0.0.1:8765` |
| Deny-by-default + receipts | product | product | **mcp-assure AdaptiveGate** (stronger local policy) |
| Native messaging host | Anthropic | OpenAI | HTTP poll bridge (simpler; good enough) |

## Friction we closed (2026-08-05)

| Pain | Fix |
|------|-----|
| `browser.screenshot` → activeTab error | Extension **0.5.1**: activate tab, `windowId`, host perm `<all_urls>` |
| Screenshot returned huge dataUrl, no file | Host writes PNG under `~/ops`, `/tmp`, … and **strips** dataUrl |
| `screencapture` FileNotFound under thin PATH | Absolute `/usr/sbin/screencapture` via `screencap_util` |
| No local WIP preview without native python server | Named `portfolio_preview_start/stop/status` |
| Only `plane_call` for click/shot | MCP: `browser_screenshot`, `browser_click`, `browser_type`, `browser_scroll`, `browser_wait`, `desktop_screenshot`, `desktop_focus`, `desktop_screenshot_window` |
| Agent forgets stack health | Named `browser_leash_status`, `desktop_leash_status`, `agent_control_stack` |

## Operator one-time steps (required for green screenshots)

1. **Chrome** → `chrome://extensions` → Browser Leash → **Reload** until popup **0.5.1** → **ARM**  
2. **System Settings** → Privacy → **Screen Recording** → allow the process that hosts desktop-leash (Terminal / python)  
3. **Accessibility** for desktop focus/click (same host process)  
4. **Grok: restart MCP `agent_control`** once after this tune-up (loads pack v15, new MCP tools, named cmds). Later disk-only handler edits: `plane_call plane.reload_handlers` without full restart.  
5. Optional: restart browser-leash bridge so status expects **0.5.1** (`cli.py down` / `up` or launchd recycle)

## Daily agent path (parity SOP)

```text
plane_status                          # both leashes armed + versions
shell_run portfolio_preview_start     # optional local WIP
browser_navigate http://127.0.0.1:8765/   # or live https://xclusivexo.com/
browser_wait 800
browser_snapshot
browser_screenshot out=~/ops/awareness/audits/shot.png
browser_scroll 700
# multi-tab: browser_workspace → pin tab_id on actions
# non-Chrome GUI: desktop_layout → desktop_focus → desktop_screenshot
```

Avoid TOOL_SPRAY: reuse ≤3–4 browser tools per burst; wait between.

## Still not parity (by design or open)

| Gap | Status |
|-----|--------|
| Native Chrome messaging host | Out — HTTP poll is intentional |
| Unlimited ambient CUA | Out — session budget |
| Auto-post / invent confirm | Out — human gate |
| Native Grok Write/StrReplace gated | Open (G1) — plane write exists; native still works |
| `file://` navigate | Denied — use portfolio preview |
| Screen Recording grant | Operator OS setting |

## Prove checklist

```bash
python3 ~/agent-control/cli.py stack
python3 ~/agent-control/cli.py call shell.run --args-json '{"name":"portfolio_preview_start"}'
# Reload extension → 0.5.1 + ARM
python3 ~/agent-control/cli.py call browser.screenshot \
  --args-json '{"out":"/Users/llm01/ops/awareness/audits/parity-shot.png"}'
python3 ~/agent-control/cli.py call desktop.screenshot \
  --args-json '{"out":"/Users/llm01/ops/awareness/audits/desktop-shot.png"}'
# pytest (named)
python3 ~/agent-control/cli.py call shell.run --args-json '{"name":"agent_control_pytest"}'
```

## Related

- `docs/GROK_DEFAULT_PATH.md` — operating loop  
- `docs/MULTI_SURFACE_NAVIGATION.md` — multi-tab / multi-window  
- `docs/GAP_BRIDGE.md` — G1 file-edit residual  
- `~/browser-leash/docs/CAPABILITY_GAP.md` — historical X fill notes  
- `docs/SHELL_GATING.md` — why no free-form interpreters  
