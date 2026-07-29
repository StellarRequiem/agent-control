"""Plane router — classify work onto the right control surface.

This is architecture, not NLP magic: keyword/heuristic map agents use before
calling a plane tool. Prefer shell for code; browser-leash for Chrome;
desktop-leash for other GUI; mcp-assure for policy; claim-gate for public copy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Route:
    plane: str
    reason: str
    preferred_tools: tuple[str, ...]
    avoid: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "plane": self.plane,
            "reason": self.reason,
            "preferred_tools": list(self.preferred_tools),
            "avoid": list(self.avoid),
        }


def route_task(task: str) -> Route:
    t = (task or "").strip().lower()
    if not t:
        return Route("shell", "empty task — stay on shell", ("plane.status",))

    # Public claims
    if any(k in t for k in ("claim", "win-rate", "accuracy %", "homepage copy", "tweet copy", "postable")):
        if any(k in t for k in ("x.com", "twitter", "compose", "draft post", "publish")):
            return Route(
                "browser",
                "public post path still uses browser-leash + human confirm",
                ("browser.x_draft", "browser.x_post"),
                ("desktop.type", "desktop.press"),
            )
        return Route(
            "claim-gate",
            "public wording — run claim cards before publish",
            ("plane.route",),
            ("browser.x_post",),
        )

    # Browser / X / web
    if any(
        k in t
        for k in (
            "chrome",
            "browser",
            "x.com",
            "twitter",
            "github.com",
            "pypi",
            "xclusivexo",
            "navigate",
            "draft on x",
            "post on x",
            "linkedin",
        )
    ):
        return Route(
            "browser",
            "Chrome/web session → browser-leash",
            ("browser.navigate", "browser.snapshot", "browser.x_draft", "browser.x_post"),
            ("desktop.click", "desktop.type"),
        )

    # Desktop GUI outside Chrome
    if any(
        k in t
        for k in (
            "screenshot desktop",
            "desktop",
            "textedit",
            "finder",
            "notes app",
            "click at",
            "frontmost",
            "quit app",
            "accessibility",
            "other gui",
        )
    ):
        return Route(
            "desktop",
            "non-Chrome GUI → desktop-leash",
            ("desktop.screenshot", "desktop.focus", "desktop.type", "desktop.press"),
            ("browser.navigate",),
        )

    # Tool policy / assurance
    if any(k in t for k in ("mcp-assure", "adaptivegate", "tool gate", "purple", "campaign freeze")):
        return Route(
            "mcp-assure",
            "policy / AdaptiveGate surface",
            ("plane.status",),
            (),
        )

    # Code / filesystem default
    if any(
        k in t
        for k in (
            "git ",
            "pytest",
            "pip ",
            "edit file",
            "commit",
            "refactor",
            "shell",
            "test ",
            "read file",
            "write file",
        )
    ):
        return Route(
            "shell",
            "files/tests/git → host-gated shell.exec / shell.run (NOT native shell)",
            (),
            ("desktop.type", "browser.type"),
        )

    return Route(
        "shell",
        "default: shell first; escalate to browser/desktop only if GUI needed",
        ("plane.status", "plane.route"),
        (),
    )
