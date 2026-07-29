"""Assured plane host — cannot-bypass path to browser-leash + desktop-leash.

Architecture goal:
  Agent proposes plane tool call → mcp-assure AdaptiveGate → handler → leash.
  Handlers are not a public free map for off-band execution.

This is the real host wire for *control-plane tools*. Native Grok shell tools
remain separate until a future host integration; do not claim "every Grok tool".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# mcp-assure from repo venv or editable install
_MCP = Path.home() / "mcp-assure"
if str(_MCP) not in sys.path:
    sys.path.insert(0, str(_MCP))

from mcp_assure import AssureEngine  # noqa: E402
from mcp_assure.integrations import AssuredToolDispatcher  # noqa: E402
from mcp_assure.policy import ToolPolicyRegistry  # noqa: E402

from host.browser_handlers import BrowserHandlers  # noqa: E402
from host.desktop_handlers import DesktopHandlers  # noqa: E402
from host.http_util import http_json  # noqa: E402
from host.router import route_task  # noqa: E402

PACK_PATH = ROOT / "packs" / "local_planes.json"
RECEIPTS = ROOT / "receipts" / "plane-host.jsonl"
FREEZE = ROOT / "FREEZE"
BROWSER = "http://127.0.0.1:8756"
DESKTOP = "http://127.0.0.1:8757"


def load_local_pack(path: Path = PACK_PATH) -> ToolPolicyRegistry:
    data = json.loads(path.read_text(encoding="utf-8"))
    return ToolPolicyRegistry.from_mapping(data)


class AssuredPlaneHost:
    """Single choke point for plane tool calls."""

    def __init__(
        self,
        *,
        receipts_path: Path | str | None = RECEIPTS,
        freeze_path: Path | str | None = FREEZE,
        adaptive: bool = True,
        browser_base: str = BROWSER,
        desktop_base: str = DESKTOP,
    ) -> None:
        receipts_path = Path(receipts_path or RECEIPTS)
        receipts_path.parent.mkdir(parents=True, exist_ok=True)
        freeze_path = Path(freeze_path or FREEZE)

        engine = AssureEngine(
            load_local_pack(),
            receipts_path=str(receipts_path),
            freeze_path=str(freeze_path),
            freeze_allow=frozenset({"plane.status", "plane.route", "browser.status", "desktop.status"}),
        )

        self.browser = BrowserHandlers(browser_base)
        self.desktop = DesktopHandlers(desktop_base)
        self.browser_base = browser_base
        self.desktop_base = desktop_base

        handlers = {
            "plane.status": self._plane_status,
            "plane.route": self._plane_route,
            "browser.status": self.browser.status,
            "browser.navigate": self.browser.navigate,
            "browser.snapshot": self.browser.snapshot,
            "browser.screenshot": self.browser.screenshot,
            "browser.click": self.browser.click,
            "browser.type": self.browser.type,
            "browser.scroll": self.browser.scroll,
            "browser.x_draft": self.browser.x_draft,
            "browser.x_post": self.browser.x_post,
            "desktop.status": self.desktop.status,
            "desktop.apps": self.desktop.apps,
            "desktop.windows": self.desktop.windows,
            "desktop.screenshot": self.desktop.screenshot,
            "desktop.focus": self.desktop.focus,
            "desktop.click": self.desktop.click,
            "desktop.type": self.desktop.type,
            "desktop.press": self.desktop.press,
            "desktop.scroll": self.desktop.scroll,
            "desktop.quit": self.desktop.quit,
            "desktop.confirm": self.desktop.confirm,
        }

        self._dispatcher = AssuredToolDispatcher(
            engine,
            handlers,
            source="agent-control",
            actor="grok",
            adaptive=adaptive,
            auto_freeze=True,
        )

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._dispatcher.call_tool({"name": name, "arguments": arguments or {}})

    def authorize_only(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._dispatcher.authorize_only({"name": name, "arguments": arguments or {}})

    def _plane_status(self, _args: dict[str, Any] | None = None) -> dict[str, Any]:
        b = http_json(self.browser_base, "/v1/status")
        d = http_json(self.desktop_base, "/v1/status")
        return {
            "ok": True,
            "host": "agent-control",
            "architecture": "AssuredToolDispatcher+AdaptiveGate → leash handlers",
            "browser_leash": {
                "up": b.get("ok") is True or b.get("bridge") == "up",
                "armed": b.get("armed"),
                "extension": (b.get("extension") or {}).get("version"),
                "require_post_confirm": b.get("require_post_confirm"),
                "code": b.get("code"),
            },
            "desktop_leash": {
                "up": d.get("ok") is True or d.get("bridge") == "up",
                "armed": d.get("armed"),
                "version": d.get("version"),
                "phase": d.get("phase"),
                "require_d4_confirm": d.get("require_d4_confirm"),
                "code": d.get("code"),
            },
            "claim_ceiling": {
                "every_grok_tool_gated": False,
                "plane_tools_gated": True,
                "auto_post": False,
                "full_cua_unlimited": False,
                "full_soc": False,
            },
        }

    def _plane_route(self, args: dict[str, Any]) -> dict[str, Any]:
        r = route_task(str(args.get("task") or ""))
        return {"ok": True, **r.as_dict()}


def build_host(**kwargs: Any) -> AssuredPlaneHost:
    return AssuredPlaneHost(**kwargs)
