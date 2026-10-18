#!/usr/bin/env python3
"""MCP server: expose AssuredPlaneHost tools over stdio (mediated ambient path).

All tool calls go through AdaptiveGate → handlers → leashes/shell.
Native run_terminal_cmd remains a *runtime* concern — deny it via Grok
permissions (see docs/MEDIATED_AMBIENT.md) so the model must use these MCP tools.

The process actor is fixed at startup and stamped on every receipt. Default
is grok. Codex (and any other launcher) passes ``--actor``; see
docs/STDIO_ACTOR.md. A JSON ``actor`` field on a tool call is ignored.

Run (stdio)::

    ~/mcp-assure/.venv/bin/python ~/agent-control/mcp_server.py
    ~/mcp-assure/.venv/bin/python ~/agent-control/mcp_server.py --actor codex

Config (~/.grok/config.toml) — omit ``--actor`` to keep grok::

    [mcp_servers.agent_control]
    command = "/Users/llm01/mcp-assure/.venv/bin/python"
    args = ["/Users/llm01/agent-control/mcp_server.py"]
    enabled = true
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path.home() / "mcp-assure"))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from host.plane_host import AssuredPlaneHost  # noqa: E402
from host.stdio_actor import resolve_stdio_actor  # noqa: E402

mcp = FastMCP(
    "agent-control",
    instructions=(
        "Mediated control plane for this host. Prefer these tools over native shell. "
        "High-blast actions (x_post, quit, Return) require operator_confirm=true only "
        "when the human explicitly approved this turn. FREEZE may block non-status tools."
    ),
)

_host: AssuredPlaneHost | None = None
# Replaced in main() before the stdio transport starts. Tool handlers are lazy.
_process_actor = "grok"


def host() -> AssuredPlaneHost:
    global _host
    if _host is None:
        _host = AssuredPlaneHost(actor=_process_actor)
    return _host


def _call(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    out = host().call(name, arguments or {})
    # Compact for MCP clients
    return {
        "executed": out.get("executed"),
        "verdict": out.get("verdict"),
        "result": out.get("result"),
        "error": out.get("error"),
        "campaign": out.get("campaign"),
    }


@mcp.tool()
def plane_status() -> dict[str, Any]:
    """Aggregate status: browser-leash, desktop-leash, claim ceiling, CUA session."""
    return _call("plane.status")


@mcp.tool()
def plane_route(task: str) -> dict[str, Any]:
    """Classify a task string into shell | browser | desktop | claim-gate."""
    return _call("plane.route", {"task": task})


@mcp.tool()
def plane_call(tool: str, arguments_json: str = "{}") -> dict[str, Any]:
    """Call any pack tool through AssuredPlaneHost (deny-by-default).

    tool: e.g. browser.navigate, desktop.apps, shell.exec, cua.start
    arguments_json: JSON object of tool arguments
    """
    try:
        args = json.loads(arguments_json or "{}")
    except json.JSONDecodeError as e:
        return {"ok": False, "code": "BAD_JSON", "detail": str(e)}
    if not isinstance(args, dict):
        return {"ok": False, "code": "BAD_ARGS", "detail": "arguments_json must be object"}
    return _call(tool, args)


@mcp.tool()
def shell_exec(argv_json: str, cwd: str = "") -> dict[str, Any]:
    """Gated read-only shell.exec (validated argv, no interpreters, path-confined).

    argv_json: JSON array e.g. [\"git\",\"status\"]
    Prefer this over native Bash / run_terminal_command.
    """
    try:
        argv = json.loads(argv_json)
    except json.JSONDecodeError as e:
        return {"ok": False, "code": "BAD_JSON", "detail": str(e)}
    body: dict[str, Any] = {"argv": argv}
    if cwd:
        body["cwd"] = cwd
    return _call("shell.exec", body)


@mcp.tool()
def shell_run(name: str) -> dict[str, Any]:
    """Run a named allowlisted command (git_status, mcp_assure_check, …)."""
    return _call("shell.run", {"name": name})


@mcp.tool()
def shell_list_dir(path: str) -> dict[str, Any]:
    """List a directory under allowed roots."""
    return _call("shell.list_dir", {"path": path})


@mcp.tool()
def shell_read_file(path: str) -> dict[str, Any]:
    """Read a file under allowed roots (size-capped)."""
    return _call("shell.read_file", {"path": path})


@mcp.tool()
def shell_write_file(path: str, content: str, mode: str = "overwrite") -> dict[str, Any]:
    """Write a file under allowed roots (mediated edit path; blocked under FREEZE)."""
    return _call("shell.write_file", {"path": path, "content": content, "mode": mode})


@mcp.tool()
def shell_apply_patch(
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> dict[str, Any]:
    """Exact str replace under allowed roots (mediated StrReplace; blocked under FREEZE)."""
    return _call(
        "shell.apply_patch",
        {
            "path": path,
            "old_string": old_string,
            "new_string": new_string,
            "replace_all": replace_all,
        },
    )


@mcp.tool()
def browser_navigate(url: str, tab_id: int = 0) -> dict[str, Any]:
    """Navigate Chrome (host allowlist + ARM required). Optional tab_id for multi-tab."""
    body: dict[str, Any] = {"url": url}
    if tab_id:
        body["tabId"] = int(tab_id)
    return _call("browser.navigate", body)


@mcp.tool()
def browser_snapshot(tab_id: int = 0) -> dict[str, Any]:
    """Tab text snapshot (ARM required). Optional tab_id reads that tab without guessing."""
    body: dict[str, Any] = {}
    if tab_id:
        body["tabId"] = int(tab_id)
    return _call("browser.snapshot", body)


@mcp.tool()
def browser_tabs() -> dict[str, Any]:
    """List Chrome tabs (ARM required)."""
    return _call("browser.tabs")


@mcp.tool()
def browser_workspace(match: str = "", tab_id: int = 0, snapshot: bool = True) -> dict[str, Any]:
    """Multi-tab orient: list tabs + optional page.info + snapshot preview (ARM required)."""
    body: dict[str, Any] = {"snapshot": bool(snapshot)}
    if match:
        body["match"] = match
    if tab_id:
        body["tabId"] = int(tab_id)
    return _call("browser.workspace", body)


@mcp.tool()
def browser_screenshot(out: str = "", tab_id: int = 0) -> dict[str, Any]:
    """Capture visible Chrome tab PNG (ARM). Prefer out under ~/ops or /tmp — path returned, not huge dataUrl."""
    body: dict[str, Any] = {}
    if out:
        body["out"] = out
    if tab_id:
        body["tabId"] = int(tab_id)
    return _call("browser.screenshot", body)


@mcp.tool()
def browser_click(selector: str, tab_id: int = 0) -> dict[str, Any]:
    """Click CSS selector in Chrome (ARM). Optional tab_id for multi-tab."""
    body: dict[str, Any] = {"selector": selector}
    if tab_id:
        body["tabId"] = int(tab_id)
    return _call("browser.click", body)


@mcp.tool()
def browser_type(text: str, selector: str = "", tab_id: int = 0) -> dict[str, Any]:
    """Type into element (ARM). Optional selector; optional tab_id."""
    body: dict[str, Any] = {"text": text}
    if selector:
        body["selector"] = selector
    if tab_id:
        body["tabId"] = int(tab_id)
    return _call("browser.type", body)


@mcp.tool()
def browser_scroll(dy: int = 600, dx: int = 0, tab_id: int = 0) -> dict[str, Any]:
    """Scroll page (ARM). Optional tab_id."""
    body: dict[str, Any] = {"dy": int(dy), "dx": int(dx)}
    if tab_id:
        body["tabId"] = int(tab_id)
    return _call("browser.scroll", body)


@mcp.tool()
def browser_wait(ms: int = 1000, tab_id: int = 0) -> dict[str, Any]:
    """Wait ms (or use plane_call browser.wait with mode=load). ARM required for page waits."""
    body: dict[str, Any] = {"ms": int(ms)}
    if tab_id:
        body["tabId"] = int(tab_id)
    return _call("browser.wait", body)


@mcp.tool()
def desktop_apps() -> dict[str, Any]:
    """List desktop apps (ARM required)."""
    return _call("desktop.apps")


@mcp.tool()
def desktop_layout() -> dict[str, Any]:
    """Window layout frames (ARM required). Prefer before clicks."""
    return _call("desktop.layout")


@mcp.tool()
def desktop_screenshot(out: str = "") -> dict[str, Any]:
    """Full desktop screenshot (ARM + Screen Recording). out path recommended under ~/ops."""
    body: dict[str, Any] = {}
    if out:
        body["out"] = out
    return _call("desktop.screenshot", body)


@mcp.tool()
def desktop_focus(app: str) -> dict[str, Any]:
    """Focus allowlisted app (ARM). Prefer browser_* for Chrome."""
    return _call("desktop.focus", {"app": app})


@mcp.tool()
def desktop_screenshot_window(app: str, out: str = "") -> dict[str, Any]:
    """Screenshot one app window frame (ARM + Screen Recording)."""
    body: dict[str, Any] = {"app": app}
    if out:
        # desktop-leash uses `path` for window shots
        body["path"] = out
    return _call("desktop.screenshot_window", body)


@mcp.tool()
def cua_start(max_steps: int = 40, max_seconds: float = 1800.0) -> dict[str, Any]:
    """Start budgeted CUA session."""
    return _call("cua.start", {"max_steps": max_steps, "max_seconds": max_seconds})


@mcp.tool()
def cua_observe() -> dict[str, Any]:
    """Multi-plane CUA observe (includes layout)."""
    return _call("cua.observe")


@mcp.tool()
def cua_step(tool: str, arguments_json: str = "{}") -> dict[str, Any]:
    """One gated CUA step (tool + JSON arguments)."""
    try:
        args = json.loads(arguments_json or "{}")
    except json.JSONDecodeError as e:
        return {"ok": False, "code": "BAD_JSON", "detail": str(e)}
    return _call("cua.step", {"tool": tool, "arguments": args if isinstance(args, dict) else {}})


@mcp.tool()
def lockdown_status() -> dict[str, Any]:
    """Abhorrent lockdown / freeze status.

    Returns the full plane status, whose ``freeze`` block names every engaged marker
    with the reason and timestamp that froze it, plus the tools that still execute
    while frozen.

    This used to be a bare alias for ``plane.status``, and ``plane.status`` did not
    look at the freeze markers at all — so the tool whose one job is reporting a
    lockdown reported leashes as armed and said nothing about the freeze. A caller
    checking before acting was told the opposite of the truth, and the only way to
    discover a freeze was to trip it. The fix is in ``plane.status`` rather than here,
    so every caller of either gets it.

    Still restricted to ``plane.status`` on purpose: it is on the freeze allowlist,
    which is what lets this answer at all while frozen.
    """
    return _call("plane.status")


@mcp.tool()
def plane_unfreeze() -> dict[str, Any]:
    """Clear FREEZE files (works even while frozen — recovery without native bash)."""
    return _call("plane.unfreeze")


@mcp.tool()
def plane_receipts_status() -> dict[str, Any]:
    """Verify receipt chain (works when chain is broken — diagnose only)."""
    return _call("plane.receipts_status")


@mcp.tool()
def plane_receipts_rotate(force: bool = False) -> dict[str, Any]:
    """Archive broken receipt chain and start empty (recovery without native bash)."""
    return _call("plane.receipts_rotate", {"force": force})


def main(argv: list[str] | None = None) -> None:
    global _process_actor
    # Resolve before the transport so an unknown actor exits and never serves.
    _process_actor = resolve_stdio_actor(argv)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
