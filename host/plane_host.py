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
from host.shell_handlers import ShellHandlers  # noqa: E402
from host.cua_loop import CuaController  # noqa: E402
from host.profile_mode import profile_summary  # noqa: E402

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

        self.receipts_path = receipts_path
        freeze_allow = frozenset(
            {
                "plane.status",
                "plane.route",
                "browser.status",
                "desktop.status",
                "shell.roots",
                "plane.unfreeze",  # recovery without native bash
                "plane.receipts_status",
                "plane.receipts_rotate",
            }
        )
        chain_repair = frozenset(
            {
                "plane.receipts_status",
                "plane.receipts_rotate",
            }
        )
        # chain_repair_allow needs mcp-assure with claim-ladder receipts work;
        # tolerate older PyPI installs in CI until that release is published.
        try:
            engine = AssureEngine(
                load_local_pack(),
                receipts_path=str(receipts_path),
                freeze_path=str(freeze_path),
                freeze_allow=freeze_allow,
                chain_repair_allow=chain_repair,
            )
        except TypeError:
            engine = AssureEngine(
                load_local_pack(),
                receipts_path=str(receipts_path),
                freeze_path=str(freeze_path),
                freeze_allow=freeze_allow,
            )

        self.browser = BrowserHandlers(browser_base)
        self.desktop = DesktopHandlers(desktop_base)
        self.shell = ShellHandlers()
        self.browser_base = browser_base
        self.desktop_base = desktop_base
        # CuaController bound after dispatcher exists — methods use self.cua
        self.cua: CuaController | None = None

        handlers = {
            "plane.status": self._plane_status,
            "plane.route": self._plane_route,
            "plane.unfreeze": self._plane_unfreeze,
            "plane.receipts_status": self._plane_receipts_status,
            "plane.receipts_rotate": self._plane_receipts_rotate,
            "browser.status": self.browser.status,
            "browser.navigate": self.browser.navigate,
            "browser.tabs": self.browser.tabs,
            "browser.tab_create": self.browser.tab_create,
            "browser.tab_close": self.browser.tab_close,
            "browser.tab_activate": self.browser.tab_activate,
            "browser.snapshot": self.browser.snapshot,
            "browser.screenshot": self.browser.screenshot,
            "browser.click": self.browser.click,
            "browser.type": self.browser.type,
            "browser.scroll": self.browser.scroll,
            "browser.wait": self.browser.wait,
            "browser.find": self.browser.find,
            "browser.links": self.browser.links,
            "browser.back": self.browser.back,
            "browser.forward": self.browser.forward,
            "browser.reload": self.browser.reload,
            "browser.x_article_read": self.browser.x_article_read,
            "browser.x_article_search": self.browser.x_article_search,
            "browser.x_article_curate": self.browser.x_article_curate,
            "browser.x_draft": self.browser.x_draft,
            "browser.x_post": self.browser.x_post,
            "desktop.status": self.desktop.status,
            "desktop.apps": self.desktop.apps,
            "desktop.windows": self.desktop.windows,
            "desktop.ax": self.desktop.ax,
            "desktop.ax_click": self.desktop.ax_click,
            "desktop.region_screenshot": self.desktop.region_screenshot,
            "desktop.cua_observe": self.desktop.cua_observe,
            "desktop.layout": self.desktop.layout,
            "desktop.screenshot_window": self.desktop.screenshot_window,
            "desktop.click_window": self.desktop.click_window,
            "desktop.d4_session": self.desktop.d4_session,
            "desktop.screenshot": self.desktop.screenshot,
            "desktop.focus": self.desktop.focus,
            "desktop.click": self.desktop.click,
            "desktop.type": self.desktop.type,
            "desktop.press": self.desktop.press,
            "desktop.scroll": self.desktop.scroll,
            "desktop.quit": self.desktop.quit,
            "desktop.confirm": self.desktop.confirm,
            "shell.roots": self.shell.roots_list,
            "shell.list_dir": self.shell.list_dir,
            "shell.read_file": self.shell.read_file,
            "shell.stat": self.shell.stat,
            "shell.run": self.shell.run,
            "shell.exec": self.shell.exec,
            "cua.start": self._cua_start,
            "cua.stop": self._cua_stop,
            "cua.status": self._cua_status,
            "cua.observe": self._cua_observe,
            "cua.step": self._cua_step,
        }

        self._dispatcher = AssuredToolDispatcher(
            engine,
            handlers,
            source="agent-control",
            actor="grok",
            adaptive=adaptive,
            auto_freeze=True,
        )
        self.cua = CuaController(self.call)

    def _cua_start(self, a: dict[str, Any] | None = None) -> dict[str, Any]:
        a = a or {}
        assert self.cua is not None
        from host.cua_loop import DEFAULT_MAX_SECONDS, DEFAULT_MAX_STEPS

        return self.cua.start(
            max_steps=int(a.get("max_steps") or DEFAULT_MAX_STEPS),
            max_seconds=float(a.get("max_seconds") or DEFAULT_MAX_SECONDS),
        )

    def _cua_stop(self, a: dict[str, Any] | None = None) -> dict[str, Any]:
        assert self.cua is not None
        return self.cua.stop(str((a or {}).get("reason") or "operator_stop"))

    def _cua_status(self, _a: dict[str, Any] | None = None) -> dict[str, Any]:
        assert self.cua is not None
        return self.cua.status()

    def _cua_observe(self, a: dict[str, Any] | None = None) -> dict[str, Any]:
        assert self.cua is not None
        return self.cua.observe(a)

    def _cua_step(self, a: dict[str, Any] | None = None) -> dict[str, Any]:
        assert self.cua is not None
        return self.cua.step(a or {})

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._dispatcher.call_tool({"name": name, "arguments": arguments or {}})

    def authorize_only(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._dispatcher.authorize_only({"name": name, "arguments": arguments or {}})

    def _plane_unfreeze(self, _args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Clear FREEZE files (allowed during freeze for recovery without native shell)."""
        cleared: list[str] = []
        for p in (
            ROOT / "FREEZE",
            Path.home() / "mcp-assure" / "FREEZE",
            Path.home() / "agent-control" / "FREEZE",
        ):
            try:
                if p.is_file():
                    p.unlink()
                    cleared.append(str(p))
            except OSError:
                continue
        return {
            "ok": True,
            "code": "UNFROZEN",
            "cleared": sorted(set(cleared)),
            "detail": "FREEZE files removed; re-arm leashes if needed",
        }

    def _plane_receipts_status(self, _args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Diagnose receipt chain (works even when chain is broken)."""
        from mcp_assure.receipts import ReceiptChain

        path = str(self.receipts_path)
        if not Path(path).is_file():
            return {
                "ok": True,
                "code": "EMPTY_OR_NEW",
                "path": path,
                "intact": True,
                "detail": "no receipt file yet",
            }
        ok, msg = ReceiptChain.verify_file(path)
        size = Path(path).stat().st_size if Path(path).is_file() else 0
        return {
            "ok": True,
            "code": "INTACT" if ok else "BROKEN",
            "path": path,
            "intact": bool(ok),
            "detail": msg,
            "bytes": size,
            "claim_ladder": str(ROOT / "docs" / "CLAIM_LADDER.md"),
        }

    def _plane_receipts_rotate(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Archive broken (or force) receipt chain and start empty — recovery path."""
        from mcp_assure.receipts import ReceiptChain

        force = bool((args or {}).get("force"))
        out = ReceiptChain.rotate_if_broken(str(self.receipts_path), force=force)
        out["claim"] = (
            "rotates host receipt log only; does not erase leash history or SOC incidents"
        )
        return out

    def _detect_mediated_shell_config(self) -> dict[str, Any]:
        """Best-effort: Grok config denies Bash + agent_control MCP enabled."""
        cfg = Path.home() / ".grok" / "config.toml"
        text = ""
        try:
            text = cfg.read_text(encoding="utf-8")
        except OSError:
            return {"native_bash_deny_configured": False, "agent_control_mcp_configured": False}
        low = text.lower()
        bash_deny = (
            "bash(*)" in low
            or '"bash"' in low
            or "bash" in low
            and "[permission]" in low
            and "deny" in low
        )
        # more precise
        bash_deny = any(
            s in text
            for s in (
                '"Bash(*)"',
                "'Bash(*)'",
                '"Bash"',
                "Bash(*)",
                'tool = "bash"',
                'tool = "Bash"',
            )
        )
        mcp_on = "mcp_servers.agent_control" in text and "enabled = true" in text
        # if agent_control block has enabled = false later, rough check
        if "mcp_servers.agent_control" in text:
            # slice block
            idx = text.find("[mcp_servers.agent_control]")
            chunk = text[idx : idx + 400] if idx >= 0 else ""
            mcp_on = "enabled = true" in chunk and "enabled = false" not in chunk
        return {
            "native_bash_deny_configured": bash_deny,
            "agent_control_mcp_configured": mcp_on,
            "config": str(cfg),
        }

    def _plane_status(self, _args: dict[str, Any] | None = None) -> dict[str, Any]:
        b = http_json(self.browser_base, "/v1/status")
        d = http_json(self.desktop_base, "/v1/status")
        med = self._detect_mediated_shell_config()
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
            "mediated_deployment": med,
            "claim_ceiling": {
                "every_grok_tool_gated": False,  # file edits still native
                "plane_tools_gated": True,
                "shell_subset_gated": True,
                "gated_shell_exec": True,
                "ambient_shell_exec": False,
                # True only when Grok deny Bash + MCP agent_control configured
                "native_runtime_shell_gated": bool(
                    med.get("native_bash_deny_configured")
                    and med.get("agent_control_mcp_configured")
                ),
                "native_shell_gate_mechanism": "grok_permission_deny+mcp_agent_control",
                "file_edit_tools_native": True,
                "auto_post": False,
                "session_cua": True,
                "full_cua_unlimited": False,
                "agent_plane_soc": True,
                "enterprise_soc": False,
            },
            "cua": self.cua.status() if self.cua else {"active": False},
            "profiles": profile_summary(),
            "default_path_doc": str(ROOT / "docs" / "GROK_DEFAULT_PATH.md"),
            "shell": {
                "roots": [str(r) for r in self.shell.roots],
                "named_commands": sorted(
                    __import__("host.shell_handlers", fromlist=["ALLOW_COMMANDS"]).ALLOW_COMMANDS.keys()
                ),
            },
            "soc": {
                "cli": str(Path.home() / "agent-soc" / "cli.py"),
                "watch": "python3 ~/agent-soc/cli.py watch --interval 30",
            },
            "claim_ladder": str(ROOT / "docs" / "CLAIM_LADDER.md"),
            "receipts_path": str(self.receipts_path),
        }

    def _plane_route(self, args: dict[str, Any]) -> dict[str, Any]:
        r = route_task(str(args.get("task") or ""))
        return {"ok": True, **r.as_dict()}


def build_host(**kwargs: Any) -> AssuredPlaneHost:
    return AssuredPlaneHost(**kwargs)
