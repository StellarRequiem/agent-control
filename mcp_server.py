#!/usr/bin/env python3
"""MCP server: expose AssuredPlaneHost tools to Grok (mediated ambient path).

All tool calls go through AdaptiveGate → handlers → leashes/shell.
Native run_terminal_cmd remains a *runtime* concern — deny it via Grok
permissions (see docs/MEDIATED_AMBIENT.md) so the model must use these MCP tools.

Run (stdio)::

    ~/mcp-assure/.venv/bin/python ~/agent-control/mcp_server.py

Config (~/.grok/config.toml)::

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

mcp = FastMCP(
    "agent-control",
    instructions=(
        "Mediated control plane for this host. Prefer these tools over native shell. "
        "High-blast actions (x_post, quit, Return) require operator_confirm=true only "
        "when the human explicitly approved this turn. FREEZE may block non-status tools."
    ),
)

_host: AssuredPlaneHost | None = None


def host() -> AssuredPlaneHost:
    global _host
    if _host is None:
        _host = AssuredPlaneHost()
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
def browser_navigate(url: str) -> dict[str, Any]:
    """Navigate Chrome (host allowlist + ARM required)."""
    return _call("browser.navigate", {"url": url})


@mcp.tool()
def browser_snapshot() -> dict[str, Any]:
    """Active tab text snapshot (ARM required)."""
    return _call("browser.snapshot")


@mcp.tool()
def browser_tabs() -> dict[str, Any]:
    """List Chrome tabs (ARM required)."""
    return _call("browser.tabs")


@mcp.tool()
def desktop_apps() -> dict[str, Any]:
    """List desktop apps (ARM required)."""
    return _call("desktop.apps")


@mcp.tool()
def desktop_layout() -> dict[str, Any]:
    """Window layout frames (ARM required). Prefer before clicks."""
    return _call("desktop.layout")


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
    """Abhorrent lockdown / freeze status (via plane status + freezes)."""
    # Keep inside host freeze allow when frozen: plane.status only
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


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
