"""Assured plane host — cannot-bypass path to browser-leash + desktop-leash.

Architecture goal:
  Agent proposes plane tool call → mcp-assure AdaptiveGate → handler → leash.
  Handlers are not a public free map for off-band execution.

This is the real host wire for *control-plane tools*. Native Grok shell tools
remain separate until a future host integration; do not claim "every Grok tool".
"""

from __future__ import annotations

import importlib
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
from mcp_assure.policy import ToolCall, ToolPolicyRegistry  # noqa: E402

from host.browser_handlers import BrowserHandlers  # noqa: E402
from host.desktop_handlers import DesktopHandlers  # noqa: E402
from host.http_util import http_json  # noqa: E402
from host.router import route_task  # noqa: E402
from host.shell_handlers import ShellHandlers  # noqa: E402
from host.stdio_actor import (  # noqa: E402
    load_stdio_roster,
    strip_spoofable_actor_fields,
    validate_actor,
)
from host.cua_loop import CuaController  # noqa: E402
from host.profile_mode import profile_summary  # noqa: E402

PACK_PATH = ROOT / "packs" / "local_planes.json"
RECEIPTS = ROOT / "receipts" / "plane-host.jsonl"
FREEZE = ROOT / "FREEZE"
#: Every marker `plane.unfreeze` clears, so status and unfreeze can never disagree
#: about what "frozen" means. They used to: unfreeze knew all three paths and status
#: knew none, which is how a frozen plane reported itself clear.
#: Deduplicated because ROOT is usually ~/agent-control, so the literal list carried
#: the same path twice. `unfreeze` hid that behind a set() on its output; a status
#: surface has no such cover and would report one marker as two.
FREEZE_PATHS: tuple[Path, ...] = tuple(
    dict.fromkeys(
        (
            ROOT / "FREEZE",
            Path.home() / "mcp-assure" / "FREEZE",
            Path.home() / "agent-control" / "FREEZE",
        )
    )
)


#: Tools that still execute under freeze. Reported by `freeze_surface` so a caller
#: learns what remains possible at the same moment it learns it is frozen.
FREEZE_ALLOW = frozenset(
    {
        "plane.status",
        "plane.route",
        "browser.status",
        "desktop.status",
        "shell.roots",
        "shell.read_file",
        "shell.list_dir",
        "shell.stat",
        "plane.unfreeze",  # recovery without native bash
        "plane.receipts_status",
        "plane.receipts_rotate",
    }
)


def freeze_surface() -> dict[str, Any]:
    """Which freeze markers exist, and what they say.

    A freeze was invisible from every status surface. `plane.status` reported leash
    arm state and never looked at the markers, and `lockdown_status` — whose entire
    job is this — was an alias for `plane.status`. So a pre-flight check returned
    "armed, no freeze field" while the plane was frozen, and the only way to discover
    it was to trip it with a tool call that then got denied. A status tool that cannot
    report the one condition it is named for makes checking first actively misleading:
    it does not fail to help, it tells you the opposite of the truth.

    Pure filesystem reads, deliberately. This has to answer while frozen, and
    `plane.status` is on the freeze allowlist precisely so it can — calling anything
    that is not would reintroduce the blindspot the moment it mattered.
    """
    markers: list[dict[str, Any]] = []
    for path in FREEZE_PATHS:
        try:
            if not path.is_file():
                continue
            raw = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError as exc:
            markers.append({"path": str(path), "unreadable": str(exc)})
            continue
        entry: dict[str, Any] = {"path": str(path)}
        for line in raw.splitlines():
            key, _, value = line.partition("=")
            if value and key in ("reason", "ts"):
                entry[key] = value.strip()
            elif not entry.get("source"):
                entry["source"] = line.strip()
        markers.append(entry)

    engaged = bool(markers)
    return {
        "engaged": engaged,
        "markers": markers,
        # Named so a reader knows what still works rather than having to guess.
        "allowed_while_frozen": sorted(FREEZE_ALLOW),
        "detail": (
            "FREEZE engaged — only allowed_while_frozen tools will execute; "
            "clear with plane.unfreeze"
            if engaged else "no freeze markers present"
        ),
    }
BROWSER = "http://127.0.0.1:8756"
DESKTOP = "http://127.0.0.1:8757"


def load_local_pack(path: Path = PACK_PATH) -> ToolPolicyRegistry:
    data = json.loads(path.read_text(encoding="utf-8"))
    return ToolPolicyRegistry.from_mapping(data)


def _git_short_sha(repo: Path) -> str | None:
    """Read short HEAD without shell (works when native bash is denied)."""
    head = repo / ".git" / "HEAD"
    try:
        if not head.is_file():
            return None
        ref = head.read_text(encoding="utf-8").strip()
        if ref.startswith("ref:"):
            ref_path = repo / ".git" / ref.split(" ", 1)[1].strip()
            if ref_path.is_file():
                return ref_path.read_text(encoding="utf-8").strip()[:7]
            return None
        return ref[:7] if len(ref) >= 7 else ref
    except OSError:
        return None


def host_code_surface() -> dict[str, Any]:
    """Pack version + host git tip for session preflight (GAP_BRIDGE G3)."""
    pack_ver: int | str | None = None
    pack_id = None
    try:
        raw = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        meta = raw.get("meta") if isinstance(raw, dict) else {}
        if isinstance(meta, dict):
            pack_ver = meta.get("version")
            pack_id = meta.get("id")
        tool_count = len((raw or {}).get("tools") or {})
    except (OSError, json.JSONDecodeError, TypeError):
        tool_count = 0
    try:
        mtime = float(PACK_PATH.stat().st_mtime)
    except OSError:
        mtime = None
    return {
        "pack_id": pack_id,
        "pack_version": pack_ver,
        "pack_tool_count": tool_count,
        "pack_path": str(PACK_PATH),
        "pack_mtime": mtime,
        "host_git_sha": _git_short_sha(ROOT),
        "claude_actor": str(Path.home() / "claude-control"),
        "multi_surface_doc": str(ROOT / "docs" / "MULTI_SURFACE_NAVIGATION.md"),
    }


def detect_mediated_shell_config() -> dict[str, Any]:
    """Shared by plane.status + session surface (honest native_runtime_shell_gated)."""
    cfg = Path.home() / ".grok" / "config.toml"
    if not cfg.is_file():
        return {
            "native_bash_deny_configured": False,
            "agent_control_mcp_configured": False,
            "config": str(cfg),
        }
    try:
        text = cfg.read_text(encoding="utf-8")
    except OSError:
        return {
            "native_bash_deny_configured": False,
            "agent_control_mcp_configured": False,
            "config": str(cfg),
        }
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
    mcp_on = False
    if "mcp_servers.agent_control" in text:
        idx = text.find("[mcp_servers.agent_control]")
        chunk = text[idx : idx + 400] if idx >= 0 else ""
        mcp_on = "enabled = true" in chunk and "enabled = false" not in chunk
    return {
        "native_bash_deny_configured": bash_deny,
        "agent_control_mcp_configured": mcp_on,
        "config": str(cfg),
    }


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
        actor: str | None = None,
        roster_dir: Path | str | None = None,
    ) -> None:
        receipts_path = Path(receipts_path or RECEIPTS)
        receipts_path.parent.mkdir(parents=True, exist_ok=True)
        freeze_path = Path(freeze_path or FREEZE)

        self.receipts_path = receipts_path
        # Process actor. None keeps the historical default (grok).
        # AGENT_CONTROL_ACTOR is read only by resolve_stdio_actor (the stdio CLI).
        # An explicit name that is off the roster raises UnknownActorError.
        self.roster_dir = Path(roster_dir) if roster_dir else (ROOT / "receipts")
        self.roster = load_stdio_roster(self.roster_dir)
        self.actor = validate_actor(
            "grok" if actor is None else actor,
            receipts_dir=self.roster_dir,
        )
        freeze_allow = FREEZE_ALLOW
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
        # Pack hot-reload: long-lived MCP host must pick up local_planes.json edits
        try:
            self._pack_mtime = float(PACK_PATH.stat().st_mtime)
        except OSError:
            self._pack_mtime = 0.0
        # CuaController bound after dispatcher exists — methods use self.cua
        self.cua: CuaController | None = None

        handlers = {
            "plane.status": self._plane_status,
            "plane.route": self._plane_route,
            "plane.unfreeze": self._plane_unfreeze,
            "plane.receipts_status": self._plane_receipts_status,
            "plane.receipts_rotate": self._plane_receipts_rotate,
            "plane.reload_handlers": self._plane_reload_handlers,
            "browser.status": self.browser.status,
            "browser.navigate": self.browser.navigate,
            "browser.tabs": self.browser.tabs,
            "browser.tab_create": self.browser.tab_create,
            "browser.tab_close": self.browser.tab_close,
            "browser.tab_activate": self.browser.tab_activate,
            # page_info / workspace are named here and still have no method on
            # BrowserHandlers. That AttributeError crashed host init on main
            # (CI). Bind them only when the method exists.
            "browser.page_info": getattr(self.browser, "page_info", None),
            "browser.workspace": getattr(self.browser, "workspace", None),
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
            "shell.write_file": self.shell.write_file,
            "shell.apply_patch": getattr(self.shell, "apply_patch", None),
            "shell.stat": self.shell.stat,
            "shell.run": self.shell.run,
            "shell.exec": self.shell.exec,
            "cua.start": self._cua_start,
            "cua.stop": self._cua_stop,
            "cua.status": self._cua_status,
            "cua.observe": self._cua_observe,
            "cua.step": self._cua_step,
        }
        handlers = {k: v for k, v in handlers.items() if v is not None}

        self._dispatcher = AssuredToolDispatcher(
            engine,
            handlers,
            source="agent-control",
            actor=self.actor,
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

    def _maybe_reload_pack(self) -> None:
        """Reload policy pack when local_planes.json mtime changes (no MCP restart)."""
        try:
            mtime = float(PACK_PATH.stat().st_mtime)
        except OSError:
            return
        if mtime <= getattr(self, "_pack_mtime", 0.0):
            return
        try:
            new_reg = load_local_pack()
        except Exception:
            return
        # Swap catalog in place; handlers already registered for new tool names
        self._dispatcher.engine.registry = new_reg
        self._pack_mtime = mtime

    def _plane_reload_handlers(self, _args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Re-import shell/browser/desktop handlers after disk edits (no full Grok restart).

        Pack policy still hot-reloads on mtime; this rebinds *Python* handler modules
        so new named shell.run commands and screenshot write logic take effect.
        """
        import host.browser_handlers as bh
        import host.desktop_handlers as dh
        import host.shell_handlers as sh

        importlib.reload(sh)
        importlib.reload(bh)
        importlib.reload(dh)

        self.shell = sh.ShellHandlers()
        self.browser = bh.BrowserHandlers(self.browser_base)
        self.desktop = dh.DesktopHandlers(self.desktop_base)

        # Rebind tools that close over handler methods (AssuredRunner.handlers)
        try:
            d = self._dispatcher.runner.handlers
        except Exception:  # noqa: BLE001
            d = None
        if not isinstance(d, dict):
            return {
                "ok": False,
                "code": "NO_HANDLER_MAP",
                "detail": "dispatcher has no rebindable handlers dict; restart MCP",
            }
        rebinds = {
            "browser.status": self.browser.status,
            "browser.navigate": self.browser.navigate,
            "browser.tabs": self.browser.tabs,
            "browser.tab_create": self.browser.tab_create,
            "browser.tab_close": self.browser.tab_close,
            "browser.tab_activate": self.browser.tab_activate,
            # page_info / workspace are named here and still have no method on
            # BrowserHandlers. That AttributeError crashed host init on main
            # (CI). Bind them only when the method exists.
            "browser.page_info": getattr(self.browser, "page_info", None),
            "browser.workspace": getattr(self.browser, "workspace", None),
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
            "shell.write_file": self.shell.write_file,
            "shell.apply_patch": getattr(self.shell, "apply_patch", None),
            "shell.stat": self.shell.stat,
            "shell.run": self.shell.run,
            "shell.exec": self.shell.exec,
        }
        for k, fn in rebinds.items():
            if fn is None:
                continue
            if k in d:
                d[k] = fn
        # Always ensure reload tool points at this method
        d["plane.reload_handlers"] = self._plane_reload_handlers
        named = sorted(sh.ALLOW_COMMANDS.keys())
        return {
            "ok": True,
            "code": "HANDLERS_RELOADED",
            "named_commands": named,
            "named_count": len(named),
            "note": "MCP tool *schemas* still need Grok session restart for new first-class tools",
        }

    def _bound_call(self, name: str, arguments: dict[str, Any] | None) -> ToolCall:
        """ToolCall bound to the process actor.

        There is no per-call actor argument. JSON `actor` / `agent` / `agent_id`
        keys are removed so they cannot enter the pack or the receipt.
        """
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise TypeError("arguments must be an object")
        return ToolCall(
            tool=str(name),
            arguments=strip_spoofable_actor_fields(arguments),
            actor=self.actor,
            source=self._dispatcher.source,
        )

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        self._maybe_reload_pack()
        return self._dispatcher.call_tool(self._bound_call(name, arguments))

    def authorize_only(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        self._maybe_reload_pack()
        return self._dispatcher.authorize_only(self._bound_call(name, arguments))

    def _plane_unfreeze(self, _args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Clear FREEZE files (allowed during freeze for recovery without native shell)."""
        cleared: list[str] = []
        for p in FREEZE_PATHS:
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
        return detect_mediated_shell_config()

    def _plane_status(self, _args: dict[str, Any] | None = None) -> dict[str, Any]:
        b = http_json(self.browser_base, "/v1/status")
        d = http_json(self.desktop_base, "/v1/status")
        med = detect_mediated_shell_config()
        shell_gated = bool(
            med.get("native_bash_deny_configured") and med.get("agent_control_mcp_configured")
        )
        return {
            "ok": True,
            "host": "agent-control",
            "architecture": "AssuredToolDispatcher+AdaptiveGate → leash handlers",
            # First, because it decides whether anything else in this payload is
            # actionable. A frozen plane that reports "armed" reads as ready.
            "freeze": freeze_surface(),
            "host_code": host_code_surface(),
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
                "native_runtime_shell_gated": shell_gated,
                "native_shell_gate_mechanism": "grok_permission_deny+mcp_agent_control",
                # Native Write/StrReplace still exist until Grok permission deny lands
                "file_edit_tools_native": True,
                # Mediated write plane available (shell.write_file / apply_patch)
                "file_edit_plane_available": True,
                "file_edit_plane_tools": ["shell.write_file", "shell.apply_patch"],
                "auto_post": False,
                "session_cua": True,
                "full_cua_unlimited": False,
                "agent_plane_soc": True,
                "enterprise_soc": False,
                "claude_actor_observe": True,
            },
            "actors": {
                # Process actor for this host. Stdio sets it once at startup.
                "current": self.actor,
                "binding": "stdio_process",
                "roster": list(self.roster),
                "spoofable_ignored": ["actor", "agent", "agent_id"],
                "grok": "agent-control MCP (this host)",
                "claude": "claude-control PreToolUse + optional same MCP",
                "gate": "mcp-assure",
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
