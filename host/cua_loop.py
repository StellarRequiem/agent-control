"""CUA session loop — observe → step → verify under AssuredPlaneHost.

This is "full CUA" for our architecture: multi-step computer use with budgets,
not ambient unlimited OS control. Session state is persisted so CLI processes share it.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

STATE_PATH = Path.home() / "agent-control" / "receipts" / "cua-session.json"


# V1 work-session defaults (still budgeted — not unlimited ambient RPA)
DEFAULT_MAX_STEPS = 40
DEFAULT_MAX_SECONDS = 1800.0


@dataclass
class CuaSession:
    session_id: str
    max_steps: int = DEFAULT_MAX_STEPS
    max_seconds: float = DEFAULT_MAX_SECONDS
    steps: int = 0
    started: float = field(default_factory=time.time)
    history: list[dict[str, Any]] = field(default_factory=list)
    closed: bool = False
    close_reason: str = ""

    def remaining(self) -> dict[str, Any]:
        elapsed = time.time() - self.started
        return {
            "steps_left": max(0, self.max_steps - self.steps),
            "seconds_left": max(0.0, self.max_seconds - elapsed),
            "elapsed": elapsed,
        }

    def budget_ok(self) -> tuple[bool, str]:
        if self.closed:
            return False, self.close_reason or "SESSION_CLOSED"
        if self.steps >= self.max_steps:
            return False, "MAX_STEPS"
        if time.time() - self.started >= self.max_seconds:
            return False, "MAX_SECONDS"
        return True, "OK"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CuaSession":
        return cls(
            session_id=str(d.get("session_id") or "cua"),
            max_steps=int(d.get("max_steps") or 20),
            max_seconds=float(d.get("max_seconds") or 600),
            steps=int(d.get("steps") or 0),
            started=float(d.get("started") or time.time()),
            history=list(d.get("history") or []),
            closed=bool(d.get("closed")),
            close_reason=str(d.get("close_reason") or ""),
        )


class CuaController:
    """Stateful CUA over a call(name, args) function (AssuredPlaneHost.call)."""

    def __init__(
        self,
        call_fn: Callable[[str, dict[str, Any] | None], dict[str, Any]],
        state_path: Path | None = None,
    ) -> None:
        self._call = call_fn
        self._state_path = Path(state_path or STATE_PATH)
        self._session: CuaSession | None = self._load()

    def _load(self) -> CuaSession | None:
        if not self._state_path.is_file():
            return None
        try:
            d = json.loads(self._state_path.read_text(encoding="utf-8"))
            if not isinstance(d, dict):
                return None
            s = CuaSession.from_dict(d)
            if s.closed:
                return None
            ok, _ = s.budget_ok()
            if not ok:
                return None
            return s
        except Exception:
            return None

    def _save(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        if self._session is None:
            if self._state_path.is_file():
                try:
                    self._state_path.unlink()
                except OSError:
                    pass
            return
        self._state_path.write_text(
            json.dumps(self._session.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )

    def start(
        self,
        *,
        max_steps: int = DEFAULT_MAX_STEPS,
        max_seconds: float = DEFAULT_MAX_SECONDS,
    ) -> dict[str, Any]:
        sid = f"cua-{int(time.time())}"
        self._session = CuaSession(
            session_id=sid,
            max_steps=max(1, min(int(max_steps), 200)),
            max_seconds=max(30.0, min(float(max_seconds), 7200.0)),
        )
        self._save()
        return {
            "ok": True,
            "code": "CUA_STARTED",
            "session_id": sid,
            "budget": self._session.remaining(),
            "claim": "session CUA under arm/allowlist — not ambient unlimited OS control",
            "v1": "ambient_under_leash",
        }

    def stop(self, reason: str = "operator_stop") -> dict[str, Any]:
        if not self._session:
            self._session = self._load()
        if not self._session:
            return {"ok": False, "code": "NO_SESSION"}
        self._session.closed = True
        self._session.close_reason = reason
        out = {
            "ok": True,
            "code": "CUA_STOPPED",
            "session_id": self._session.session_id,
            "steps": self._session.steps,
            "history_len": len(self._session.history),
        }
        self._session = None
        self._save()
        return out

    def status(self) -> dict[str, Any]:
        if not self._session:
            self._session = self._load()
        if not self._session:
            return {"ok": True, "active": False}
        s = self._session
        return {
            "ok": True,
            "active": not s.closed,
            "session_id": s.session_id,
            "steps": s.steps,
            "budget": s.remaining(),
            "closed": s.closed,
            "close_reason": s.close_reason,
            "history_tail": s.history[-5:],
        }

    def observe(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Multi-plane observe: desktop CUA bundle + browser status."""
        args = args or {}
        if not self._session:
            self._session = self._load()
        if self._session:
            ok, code = self._session.budget_ok()
            if not ok and code != "OK":
                return {"ok": False, "code": code, "detail": "CUA budget exhausted"}

        desktop = self._call("desktop.cua_observe" if self._has_desktop_cua() else "desktop.screenshot", {})
        if not self._tool_executed_ok(desktop):
            desktop = {
                "frontmost": self._call("desktop.status", {}),
                "apps": self._call("desktop.apps", {}),
                "ax": self._call("desktop.ax", {"max": 30}),
                "screenshot": self._call("desktop.screenshot", {}),
            }
        # V1: layout-first — window geometry always in observe (no blind full-screen coords)
        layout = self._call("desktop.layout", {})
        browser = self._call("browser.status", {})
        plane = self._call("plane.status", {})
        out = {
            "ok": True,
            "code": "CUA_OBSERVE",
            "desktop": self._unwrap(desktop),
            "layout": self._unwrap(layout),
            "browser": self._unwrap(browser),
            "plane": self._unwrap(plane),
            "gui_hint": "prefer desktop.click_window (rel) or browser.* for Chrome; never guess full-screen coords",
            "session": self.status(),
        }
        if self._session:
            self._session.history.append({"kind": "observe", "ts": time.time()})
            self._save()
        return out

    # GUI tools that must never run without fresh window geometry
    _LAYOUT_FIRST_TOOLS = frozenset(
        {
            "desktop.click",
            "desktop.click_window",
            "desktop.ax_click",
            "desktop.screenshot_window",
            "desktop.region_screenshot",
        }
    )

    def step(self, args: dict[str, Any]) -> dict[str, Any]:
        """Execute one plane tool as a CUA step (gated by host pack)."""
        if not self._session:
            self._session = self._load()
        if not self._session:
            return {"ok": False, "code": "NO_SESSION", "detail": "call cua.start first"}
        ok, code = self._session.budget_ok()
        if not ok:
            return {"ok": False, "code": code, "detail": "CUA budget exhausted"}

        tool = str(args.get("tool") or "").strip()
        tool_args = args.get("arguments") if isinstance(args.get("arguments"), dict) else {}
        if not tool:
            return {"ok": False, "code": "TOOL_REQUIRED"}

        if tool in ("shell_exec",) or tool.startswith("shell_exec"):
            return {"ok": False, "code": "CUA_BLOCKED", "detail": "ambient shell_exec not in CUA"}

        # V1 ambient: layout-first for GUI clicks/shots (does not consume an extra budget step)
        layout_snapshot: Any = None
        if tool in self._LAYOUT_FIRST_TOOLS:
            layout_out = self._call("desktop.layout", {})
            layout_snapshot = self._unwrap(layout_out)
            # Prefer window-local click when agent still used absolute desktop.click
            if tool == "desktop.click" and tool_args.get("app"):
                # rewrite to click_window when app provided alongside coords
                if tool_args.get("rel_x") is not None or tool_args.get("local_x") is not None:
                    tool = "desktop.click_window"
                    tool_args = {
                        k: v
                        for k, v in tool_args.items()
                        if k
                        in (
                            "app",
                            "title",
                            "rel_x",
                            "rel_y",
                            "local_x",
                            "local_y",
                            "focus",
                        )
                    }

        result = self._call(tool, tool_args)
        self._session.steps += 1
        entry = {
            "kind": "step",
            "ts": time.time(),
            "tool": tool,
            "executed": result.get("executed"),
            "verdict": (result.get("verdict") or {}).get("decision"),
            "code": ((result.get("result") or {}) if isinstance(result.get("result"), dict) else {}).get("code")
            or (result.get("verdict") or {}).get("code"),
            "layout_first": layout_snapshot is not None,
        }
        self._session.history.append(entry)
        self._save()
        out: dict[str, Any] = {
            "ok": True,
            "code": "CUA_STEP",
            "step": self._session.steps,
            "budget": self._session.remaining(),
            "result": result,
        }
        if layout_snapshot is not None:
            out["layout"] = layout_snapshot
            out["gui_hint"] = (
                "layout refreshed before this step — prefer click_window rel coords; "
                "avoid full-screen desktop.click when multi-window"
            )
        return out

    def _has_desktop_cua(self) -> bool:
        # pack may list desktop.cua_observe
        return True

    def _tool_executed_ok(self, out: dict[str, Any]) -> bool:
        if not isinstance(out, dict):
            return False
        if out.get("executed") is False:
            return False
        r = out.get("result")
        if isinstance(r, dict) and r.get("ok") is False:
            return False
        return out.get("executed") is True or "verdict" not in out

    def _unwrap(self, out: dict[str, Any]) -> Any:
        if isinstance(out, dict) and "result" in out:
            return out.get("result")
        return out
