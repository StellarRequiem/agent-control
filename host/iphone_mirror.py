"""Identify Apple's iPhone Mirroring window without inventing accessibility nodes.

On this stack System Events reports the process and the window title as
"iPhone Mirroring". desktop.apps / desktop.windows / desktop.layout do not
return a bundle id. The published bundle id for that app is
com.apple.ScreenContinuity (Screen Continuity). Match the name and title
that the tools actually return; the bundle id is an extra pattern for callers
that already have it.

The mirrored phone is a remote framebuffer. After focus, desktop.ax returns
one AXGroup whose title and value are "missing value". That group is real —
it is the whole window — and it has no children. Do not synthesize buttons.
Drive the phone with desktop.click_window (rel_x/rel_y or local_x/local_y)
and read it with desktop.screenshot_window.
"""

from __future__ import annotations

from typing import Any

APP_NAME = "iPhone Mirroring"
WINDOW_TITLE = "iPhone Mirroring"
BUNDLE_ID = "com.apple.ScreenContinuity"

_APP_NAMES = frozenset({APP_NAME.casefold(), "screencontinuity", BUNDLE_ID.casefold()})
_TITLE_NEEDLES = (WINDOW_TITLE.casefold(),)
_EMPTY_TEXT = frozenset({"", "missing value", "null", "none"})
_EMPTY_ROLES = frozenset({"axgroup", "group", "?"})

AX_NOTE = (
    "iPhone Mirroring shows the phone as a Continuity framebuffer. "
    "Accessibility returns only an empty AXGroup (title and value 'missing value'); "
    "the mirrored UI is not in the tree. Do not invent AX nodes and do not use "
    "desktop.ax_click for phone controls. Focus the window, then desktop.click_window "
    "with rel_x/rel_y in 0..1 or local_x/local_y inside the frame from desktop.layout. "
    "Read the phone with desktop.screenshot_window (image_png_base64), not shell.read_file."
)

DRIVE = {
    "see": "desktop.screenshot_window",
    "click": "desktop.click_window",
    "type": "desktop.type",
    "focus": "desktop.focus",
    "coords": "rel_x/rel_y are 0..1 inside the window; local_x/local_y are points from the window origin",
    "focus_before_type": True,
}


def _fold(value: Any) -> str:
    return str(value or "").strip().casefold()


def is_iphone_mirror_app(name: Any) -> bool:
    return _fold(name) in _APP_NAMES


def is_iphone_mirror_title(title: Any) -> bool:
    folded = _fold(title)
    return any(needle in folded for needle in _TITLE_NEEDLES) if folded else False


def is_iphone_mirror_window(window: dict[str, Any] | None) -> bool:
    if not isinstance(window, dict):
        return False
    return is_iphone_mirror_app(window.get("app")) or (
        is_iphone_mirror_title(window.get("title")) and not window.get("app")
    )


def identity() -> dict[str, Any]:
    """Stable identification block. Patterns are the ones this stack returns."""
    return {
        "kind": "iphone_mirroring",
        "app": APP_NAME,
        "window_title": WINDOW_TITLE,
        "bundle_id": BUNDLE_ID,
        "bundle_id_source": (
            "Published bundle id for Apple iPhone Mirroring (Screen Continuity). "
            "desktop.apps on this stack returns the System Events name only."
        ),
        "match": {
            "app_names": [APP_NAME],
            "title_contains": [WINDOW_TITLE],
            "bundle_ids": [BUNDLE_ID],
        },
        "drive": dict(DRIVE),
    }


def ax_is_framebuffer(elements: Any) -> bool:
    """True when the tree is missing or is the single empty Continuity group."""
    if not isinstance(elements, list) or not elements:
        return True
    if len(elements) != 1 or not isinstance(elements[0], dict):
        return False
    el = elements[0]
    role = _fold(el.get("role"))
    title = _fold(el.get("title"))
    value = _fold(el.get("value"))
    return role in _EMPTY_ROLES and title in _EMPTY_TEXT and value in _EMPTY_TEXT


def point_inside_window(x: int, y: int, window: dict[str, Any]) -> bool:
    """Half-open window frame in the leash's top-left point space."""
    try:
        wx = int(window["x"])
        wy = int(window["y"])
        ww = int(window["w"])
        wh = int(window["h"])
    except (KeyError, TypeError, ValueError):
        return False
    if ww <= 0 or wh <= 0:
        return False
    return wx <= int(x) < wx + ww and wy <= int(y) < wy + wh


def _with_data(result: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    out = dict(result)
    out["data"] = data
    return out


def annotate_apps(result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict) or not result.get("ok"):
        return result
    data = result.get("data")
    if not isinstance(data, dict):
        return result
    data = dict(data)
    apps = [str(a) for a in (data.get("apps") or [])]
    present = next((a for a in apps if is_iphone_mirror_app(a)), None)
    block = identity()
    block["present"] = present is not None
    if present:
        block["app"] = present
    data["iphone_mirroring"] = block
    return _with_data(result, data)


def _mark_window(window: dict[str, Any]) -> dict[str, Any]:
    if not is_iphone_mirror_window(window):
        return window
    marked = dict(window)
    marked["iphone_mirroring"] = True
    return marked


def annotate_windows(result: dict[str, Any]) -> dict[str, Any]:
    """Tag matching windows. Used for desktop.windows and the layout window list."""
    if not isinstance(result, dict) or not result.get("ok"):
        return result
    data = result.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("windows"), list):
        return result
    data = dict(data)
    windows = [_mark_window(w) if isinstance(w, dict) else w for w in data["windows"]]
    data["windows"] = windows
    matched = [w for w in windows if isinstance(w, dict) and w.get("iphone_mirroring")]
    block = identity()
    block["present"] = bool(matched)
    if matched:
        block["windows"] = [
            {k: w.get(k) for k in ("app", "title", "x", "y", "w", "h", "valid_bounds")}
            for w in matched
        ]
    data["iphone_mirroring"] = block
    return _with_data(result, data)


def annotate_layout(result: dict[str, Any]) -> dict[str, Any]:
    result = annotate_windows(result)
    if not isinstance(result, dict) or not result.get("ok"):
        return result
    data = result.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("frames_by_app"), dict):
        return result
    frames = dict(data["frames_by_app"])
    for app, rows in list(frames.items()):
        if not is_iphone_mirror_app(app) or not isinstance(rows, list):
            continue
        frames[app] = [dict(row, iphone_mirroring=True) if isinstance(row, dict) else row for row in rows]
    data = dict(data)
    data["frames_by_app"] = frames
    return _with_data(result, data)


def annotate_ax(result: dict[str, Any]) -> dict[str, Any]:
    """Describe a framebuffer AX tree. The elements list is copied unchanged."""
    if not isinstance(result, dict) or not result.get("ok"):
        return result
    data = result.get("data")
    if not isinstance(data, dict):
        return result
    app = data.get("app")
    window = data.get("window")
    if not (is_iphone_mirror_app(app) or is_iphone_mirror_title(window)):
        return result
    elements = list(data.get("elements") or [])
    framebuffer = ax_is_framebuffer(elements)
    data = dict(data)
    data["elements"] = elements
    block = identity()
    block["present"] = True
    block["ax_usable"] = not framebuffer
    block["ax_note"] = AX_NOTE if framebuffer else (
        "iPhone Mirroring is frontmost. Any elements below are window chrome only; "
        "the phone framebuffer still has no per-control AX nodes. Prefer "
        "desktop.click_window with rel_x/rel_y."
    )
    data["iphone_mirroring"] = block
    return _with_data(result, data)


def annotate_screenshot_window(result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict) or not result.get("ok"):
        return result
    data = result.get("data")
    if not isinstance(data, dict):
        return result
    window = data.get("window") if isinstance(data.get("window"), dict) else None
    if not is_iphone_mirror_window(window):
        return result
    data = dict(data)
    block = identity()
    block["present"] = True
    block["ax_usable"] = False
    block["ax_note"] = AX_NOTE
    if window:
        block["window"] = {k: window.get(k) for k in ("app", "title", "x", "y", "w", "h")}
    data["iphone_mirroring"] = block
    return _with_data(result, data)


def annotate_click(result: dict[str, Any]) -> dict[str, Any]:
    """Record whether the resolved point sits inside the window the leash clicked."""
    if not isinstance(result, dict) or not result.get("ok"):
        return result
    data = result.get("data")
    if not isinstance(data, dict):
        return result
    resolved = data.get("resolved") if isinstance(data.get("resolved"), dict) else {}
    window = resolved.get("window") if isinstance(resolved.get("window"), dict) else None
    gx, gy = resolved.get("global_x"), resolved.get("global_y")
    data = dict(data)
    if window is not None and gx is not None and gy is not None:
        try:
            data["inside_window"] = point_inside_window(int(gx), int(gy), window)
        except (TypeError, ValueError):
            data["inside_window"] = False
    if is_iphone_mirror_window(window) or is_iphone_mirror_app(resolved.get("app")):
        block = identity()
        block["present"] = True
        block["ax_usable"] = False
        block["ax_note"] = AX_NOTE
        if "inside_window" in data:
            block["inside_window"] = data["inside_window"]
        data["iphone_mirroring"] = block
    elif "inside_window" not in data and not is_iphone_mirror_window(window):
        return result
    return _with_data(result, data)
