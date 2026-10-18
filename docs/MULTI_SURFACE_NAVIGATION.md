# Multi-surface navigation (tabs · pages · screens)

**Audience:** Grok / agents operating through `agent-control`  
**Constraint:** ARM + host allowlist + AdaptiveGate — no ambient multi-display OS control  
**Claim:** session multi-tab / multi-window assist under leash — **not** unlimited CUA

---

## Three surfaces

| Surface | Plane | Primary tools |
|---------|--------|----------------|
| **Multi-tab** (Chrome tabs) | browser-leash | `browser.tabs`, `browser.workspace`, `tabId` on actions |
| **Multi-page** (history / SPA / research trail) | browser-leash | `navigate`, `back`, `forward`, `reload`, `wait`, `links` |
| **Multi-screen / multi-window** (desktop geometry) | desktop-leash | `desktop.layout`, `desktop.windows`, `click_window` |

Use **browser** for anything inside Chrome. Use **desktop** only when the target is not Chrome (or you need window frames).

---

## Multi-tab (parallel research)

### Orient first

```bash
# List tabs + focus hint (no heavy snapshot)
python3 ~/agent-control/cli.py call browser.workspace --args-json '{"snapshot":false}'

# Or MCP: browser_workspace
# Match a tab by URL/title substring:
python3 ~/agent-control/cli.py call browser.workspace \
  --args-json '{"match":"github.com","snapshot":true}'
```

### Patterns

1. **Split research:** keep Grok history on tab A; open docs on tab B  
   - `browser.tab_create` with `url` + `active:false` so you do not lose focus  
   - Work on B with `tabId` on every action  
2. **Never guess “the” page** after create — call `browser.tabs` or `workspace` and pin `tabId`  
3. **Snapshot non-active tabs:** `browser.snapshot` with `{"tabId": N}` (extension supports it)  
4. **Screenshot** is active-window only — host activates `tabId` first when provided  
5. **Close carefully:** only `tab_close` when you opened the tab this session (or operator agrees)

### tabId on actions (host → leash)

| Tool | tabId |
|------|-------|
| `browser.navigate` | yes |
| `browser.snapshot` / `find` / `links` / `click` / `type` / `scroll` / `wait` | yes |
| `browser.back` / `forward` / `reload` / `page_info` | yes |
| `browser.screenshot` | activates then captures |
| `browser.x_*` | uses X compose tab path (special) |

Aliases accepted: `tabId`, `tab_id`; bare `id` only when no `selector` is present (so click `id` attributes are not mistaken for tab ids).

### Anti-patterns

- Spray unique tools (find + links + click + scroll) → AdaptiveGate **TOOL_SPRAY**  
  Prefer: `navigate` → `wait` → `snapshot` (reuse ≤3–4 tools)  
- Navigate without `tabId` when multiple tabs open → overwrites active research  
- Scroll immediately after escalate risk — cool with waits only  

---

## Multi-page (within one tab)

| Goal | Sequence |
|------|----------|
| Load then read | `navigate` → `wait mode=load` → `snapshot` |
| Read more of long page | `scroll dy=700` → `snapshot` (reuse tools) |
| Follow in-page link | `find`/`links` → `click` selector **or** `navigate` to href |
| Undo navigation | `back` (same `tabId`) |
| Stale SPA | `reload` then `wait` |
| Parallel destinations | **new tab** (`tab_create`), not overwrite |

### History-panel mining (Grok / X)

1. One tab dedicated to `x.com/i/grok`  
2. Open Chat history → `browser.links` for `conversation=` IDs  
3. Open deep threads **in the same tab** or a **second research tab**  
4. Do not open 10 unique tool types in one burst  

---

## Multi-screen / multi-window (desktop)

| Goal | Sequence |
|------|----------|
| See window frames | `desktop.layout` (or `cua.observe` which includes layout + workspace) |
| Click inside a window | `desktop.click_window` with `app` + relative coords — **never** full-screen guess |
| Chrome + another app | browser tools for Chrome; desktop for the other app only |
| Two Chrome windows | still `browser.tabs`; layout only if you need OS-level focus |

`cua.observe` now returns:

- `layout` — window geometry  
- `workspace` — Chrome tab inventory (`snapshot:false` by default)  
- `gui_hint` — multi-tab / multi-screen reminder  

---

## Recommended agent SOP

```
1. plane.status / cua.observe     → armed? layout? tabs?
2. browser.workspace              → pin tabId(s)
3. For each research page:
     tab_create OR navigate(tabId)
     wait(load)
     snapshot(tabId)
     (optional) scroll + snapshot — same tools only
4. Desktop only if target is non-Chrome
5. High-blast still needs operator_confirm
```

---

## MCP convenience tools

| MCP tool | Maps to |
|----------|---------|
| `browser_tabs` | `browser.tabs` |
| `browser_workspace` | `browser.workspace` |
| `browser_navigate(url, tab_id?)` | `browser.navigate` |
| `browser_snapshot(tab_id?)` | `browser.snapshot` |
| `cua_observe` | includes `workspace` + `layout` |

---

## Related

- `browser-leash/docs/FORM_FILL_AND_MULTI_TAB.md` — form-fill patterns  
- `docs/HYBRID_PATH.md` — stock browser plugins vs leash  
- `docs/GROK_DEFAULT_PATH.md` — session routing  
- desktop: `desktop-leash/docs/INTEGRATION.md`  
