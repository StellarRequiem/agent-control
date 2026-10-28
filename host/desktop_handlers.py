"""desktop-leash handlers + app profiles — only via AssuredPlaneHost."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

from host.desktop_signing import SignedDesktopClient
from host.iphone_mirror import (
    annotate_apps,
    annotate_ax,
    annotate_click,
    annotate_layout,
    annotate_screenshot_window,
    annotate_windows,
)
from host.screenshot_image import enrich_screenshot

DESKTOP = "http://127.0.0.1:8757"
PROFILES = Path(__file__).resolve().parent.parent / "profiles" / "desktop_apps.json"

# Inline PNG ceiling for screenshot tool results. The leash still writes the
# full file, and the existing path/bytes fields stay. 8_000_000 raw bytes is
# about 10.7 million base64 characters: enough for a typical single-display
# screencapture, and under common MCP message ceilings. A larger file sets
# data.image_omitted and leaves the bytes on disk at data.path.
MAX_INLINE_PNG_BYTES = 8_000_000

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _png_path(result: dict[str, Any]) -> str:
    data = result.get("data")
    if isinstance(data, dict):
        path = data.get("path")
        if isinstance(path, str) and path.strip():
            return path.strip()
    path = result.get("path")
    if isinstance(path, str) and path.strip():
        return path.strip()
    return ""


def _png_dimensions(header: bytes) -> tuple[int, int] | None:
    """Width and height from a PNG IHDR, or None if the header is not a PNG."""
    if len(header) < 24 or not header.startswith(_PNG_MAGIC) or header[12:16] != b"IHDR":
        return None
    width = int.from_bytes(header[16:20], "big")
    height = int.from_bytes(header[20:24], "big")
    if width <= 0 or height <= 0:
        return None
    return width, height


def attach_inline_png(
    result: dict[str, Any],
    *,
    max_bytes: int = MAX_INLINE_PNG_BYTES,
) -> dict[str, Any]:
    """Copy a successful screenshot result and add base64 PNG bytes.

    Reads the PNG the leash already saved (``data.path``, or a top-level
    ``path``). Does not remove or rewrite that file. A non-success result, or
    one with no path, is returned unchanged. Over ``max_bytes``,
    ``data.image_omitted`` names the cap and the bytes stay on disk.
    """
    if not isinstance(result, dict) or result.get("ok") is not True:
        return result
    path = _png_path(result)
    if not path:
        return result

    out = dict(result)
    raw_data = result.get("data")
    data = dict(raw_data) if isinstance(raw_data, dict) else {}
    out["data"] = data
    file = Path(path)

    try:
        size = file.stat().st_size
    except OSError as exc:
        data["image_error"] = f"png read failed: {exc}"
        return out
    if not file.is_file():
        data["image_error"] = "png read failed: not a regular file"
        return out

    try:
        with file.open("rb") as fh:
            if size > max_bytes:
                header = fh.read(24)
                raw: bytes | None = None
            else:
                raw = fh.read()
                header = raw[:24]
    except OSError as exc:
        data["image_error"] = f"png read failed: {exc}"
        return out

    dims = _png_dimensions(header)
    if dims is None:
        data["image_error"] = "saved file is not a PNG"
        return out
    if data.get("width") is None:
        data["width"] = dims[0]
    if data.get("height") is None:
        data["height"] = dims[1]

    if raw is None or len(raw) > max_bytes:
        reported = size if raw is None else len(raw)
        data["image_omitted"] = (
            f"png is {reported} bytes; inline base64 cap is {max_bytes} bytes "
            f"(about {max_bytes * 4 // 3} base64 characters). "
            "The file remains at data.path."
        )
        return out

    if not data.get("mime"):
        data["mime"] = "image/png"
    data["image_png_base64"] = base64.b64encode(raw).decode("ascii")
    return out


class DesktopHandlers:
    def __init__(
        self,
        base: str = DESKTOP,
        profiles_path: Path | None = None,
        *,
        actor: str | None = None,
        client: SignedDesktopClient | None = None,
    ) -> None:
        self.base = base
        # Actor comes from the stdio --actor roster (PR #2 sets AGENT_CONTROL_ACTOR); default grok.
        self.actor = actor or os.environ.get("AGENT_CONTROL_ACTOR") or "grok"
        self.client = client or SignedDesktopClient(base, self.actor)
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
        return self._post("/v1/action", body)

    def _get(self, path: str) -> dict[str, Any]:
        return self.client.call(path)

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self.client.call(path, body)

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
        return self._get("/v1/status")

    def apps(self, _args: dict[str, Any] | None = None) -> dict[str, Any]:
        return annotate_apps(self._action("desktop.apps"))

    def windows(self, _args: dict[str, Any] | None = None) -> dict[str, Any]:
        return annotate_windows(self._action("desktop.windows"))

    def ax(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        # Frontmost window only. iPhone Mirroring's phone UI is one empty AXGroup;
        # annotate_ax records that and does not add nodes.
        return annotate_ax(self._action("desktop.ax", max=int(args.get("max") or 40)))

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
        return enrich_screenshot(self._post("/v1/action", body))

    def cua_observe(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        body: dict[str, Any] = {"action": "desktop.cua_observe"}
        if args.get("out_dir"):
            body["out_dir"] = args["out_dir"]
        return self._post("/v1/action", body)

    def layout(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        body: dict[str, Any] = {"action": "desktop.layout"}
        if args.get("path"):
            body["path"] = args["path"]
        return annotate_layout(self._post("/v1/action", body))

    def screenshot_window(self, args: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "action": "desktop.screenshot_window",
            "app": args["app"],
            "title": args.get("title") or "",
        }
        if args.get("path"):
            body["path"] = args["path"]
        return annotate_screenshot_window(enrich_screenshot(self._post("/v1/action", body)))

    def click_window(self, args: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "action": "desktop.click_window",
            "app": args["app"],
            "title": args.get("title") or "",
            "focus": args.get("focus", True),
        }
        for k in ("rel_x", "rel_y", "local_x", "local_y"):
            if args.get(k) is not None:
                body[k] = args[k]
        return annotate_click(self._post("/v1/action", body))

    def d4_session(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        open_session = bool(args.get("open"))
        if args.get("close"):
            open_session = False
        body: dict[str, Any] = {"open": open_session}
        if args.get("ttl") is not None:
            body["ttl"] = int(args["ttl"])
        return self._post("/v1/d4-session", body)

    def screenshot(self, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        body: dict[str, Any] = {"action": "desktop.screenshot"}
        if args.get("out"):
            body["out"] = args["out"]
        return enrich_screenshot(self._post("/v1/action", body))

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
        return self._post("/v1/confirm", {"id": args["id"], "ok": bool(yes)})
