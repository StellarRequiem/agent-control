"""desktop-leash handlers + app profiles — only via AssuredPlaneHost."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from host.http_util import http_json

DESKTOP = "http://127.0.0.1:8757"
PROFILES = Path(__file__).resolve().parent.parent / "profiles" / "desktop_apps.json"


class DesktopHandlers:
    def __init__(self, base: str = DESKTOP, profiles_path: Path | None = None) -> None:
        self.base = base
        self.profiles_path = profiles_path or PROFILES
        self._profiles = self._load_profiles()
        self._input_counts: dict[str, int] = {}

    def _load_profiles(self) -> dict[str, Any]:
        if not self.profiles_path.is_file():
            return {"default": {}, "profiles": {}, "denylist_hard": []}
        return json.loads(self.profiles_path.read_text(encoding="utf-8"))

    def profile_for(self, app: str) -> dict[str, Any]:
        hard = set(self._profiles.get("denylist_hard") or [])
        if app in hard:
            return {"denied": True, "reason": "profile denylist_hard"}
        prof = dict(self._profiles.get("default") or {})
        prof.update((self._profiles.get("profiles") or {}).get(app) or {})
        prof["app"] = app
        prof["denied"] = False
        return prof

    def _action(self, action: str, **extra: Any) -> dict[str, Any]:
        body = {"action": action, **extra}
        return http_json(self.base, "/v1/action", body)

    def _gate_app_input(self, app: str | None, kind: str) -> dict[str, Any] | None:
        """Host-side profile gate before leash (leash still enforces allowlist)."""
        if not app:
            return None
        prof = self.profile_for(app)
        if prof.get("denied"):
            return {
                "ok": False,
                "code": "PROFILE_DENIED",
                "detail": prof.get("reason") or f"{app} hard-denied by profile",
            }
        key = f"allow_{kind}"
        if kind in ("type", "click", "press", "quit") and prof.get(key) is False:
            return {
                "ok": False,
                "code": "PROFILE_ACTION_DENIED",
                "detail": f"profile for {app} has {key}=false — prefer shell/browser-leash",
                "profile": prof,
            }
        max_n = int(prof.get("max_input_per_session") or 80)
        n = self._input_counts.get(app, 0)
        if n >= max_n:
            return {
                "ok": False,
                "code": "PROFILE_VELOCITY",
                "detail": f"{app} input {n}/{max_n} this host session",
                "profile": prof,
            }
        self._input_counts[app] = n + 1
        return None

    def status(self, _args: dict[str, Any] | None = None) -> dict[str, Any]:
        return http_json(self.base, "/v1/status")

    def apps(self, _args: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._action("desktop.apps")

    def windows(self, _args: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._action("desktop.windows")

    def ax(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        return self._action("desktop.ax", max=int(args.get("max") or 40))

    def ax_click(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        return self._action(
            "desktop.ax_click",
            role=str(args.get("role") or ""),
            title=str(args.get("title") or ""),
            description=str(args.get("description") or ""),
            index=int(args.get("index") or 1),
        )

    def region_screenshot(self, args: dict[str, Any]) -> dict[str, Any]:
        body = {
            "action": "desktop.region_screenshot",
            "x": int(args["x"]),
            "y": int(args["y"]),
            "w": int(args["w"]),
            "h": int(args["h"]),
        }
        if args.get("path"):
            body["path"] = args["path"]
        return http_json(self.base, "/v1/action", body)

    def cua_observe(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        body: dict[str, Any] = {"action": "desktop.cua_observe"}
        if args.get("out_dir"):
            body["out_dir"] = args["out_dir"]
        return http_json(self.base, "/v1/action", body)

    def d4_session(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        open_session = bool(args.get("open"))
        if args.get("close"):
            open_session = False
        body: dict[str, Any] = {"open": open_session}
        if args.get("ttl") is not None:
            body["ttl"] = int(args["ttl"])
        return http_json(self.base, "/v1/d4-session", body)

    def screenshot(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        body: dict[str, Any] = {"action": "desktop.screenshot"}
        if args.get("out"):
            body["out"] = args["out"]
        return http_json(self.base, "/v1/action", body)

    def focus(self, args: dict[str, Any]) -> dict[str, Any]:
        app = args["app"]
        prof = self.profile_for(app)
        if prof.get("denied"):
            return {
                "ok": False,
                "code": "PROFILE_DENIED",
                "detail": prof.get("reason"),
            }
        res = self._action("desktop.focus", app=app)
        res["profile"] = {k: prof[k] for k in prof if k in ("allow_type", "allow_press", "allow_quit", "notes")}
        return res

    def click(self, args: dict[str, Any]) -> dict[str, Any]:
        # frontmost unknown here — leash gates; profile best-effort via optional app
        return self._action("desktop.click", x=int(args["x"]), y=int(args["y"]))

    def type(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._action("desktop.type", text=args["text"])

    def press(self, args: dict[str, Any]) -> dict[str, Any]:
        key = str(args.get("key") or "return").lower()
        # High-blast keys: require operator_confirm at host before leash
        if key in ("return", "enter"):
            confirm = args.get("operator_confirm")
            if confirm is not True and confirm != "true" and confirm != 1:
                return {
                    "ok": False,
                    "code": "HUMAN_CONFIRM_REQUIRED",
                    "detail": "desktop.press return/enter requires operator_confirm=true",
                    "key": key,
                }
        return self._action("desktop.press", key=key)

    def scroll(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        return self._action("desktop.scroll", dy=int(args.get("dy", 400)))

    def quit(self, args: dict[str, Any]) -> dict[str, Any]:
        app = args["app"]
        confirm = args.get("operator_confirm")
        if confirm is not True and confirm != "true" and confirm != 1:
            return {
                "ok": False,
                "code": "HUMAN_CONFIRM_REQUIRED",
                "detail": "desktop.quit requires operator_confirm=true",
            }
        blocked = self._gate_app_input(app, "quit")
        if blocked:
            return blocked
        return self._action("desktop.quit", app=app)

    def confirm(self, args: dict[str, Any]) -> dict[str, Any]:
        approve = args.get("approve")
        yes = approve is True or approve == "true" or approve == 1 or approve == "yes"
        # desktop-leash POST /v1/confirm {id, ok: true|false}
        return http_json(self.base, "/v1/confirm", {"id": args["id"], "ok": bool(yes)})
