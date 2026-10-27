"""browser.screenshot host-side: write PNG under allowlisted roots; deny others."""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import MagicMock

from host.browser_handlers import BrowserHandlers

# Minimal valid-looking PNG header + padding so size > 32
_MINI_PNG = (
    b"\x89PNG\r\n\x1a\n"
    + b"\x00" * 40
)


def _handlers_with_fake_action(data_url: str, activate_ok: bool = True) -> BrowserHandlers:
    h = BrowserHandlers()
    def _action(name: str, **kwargs):  # noqa: ANN003
        if name == "tab.activate":
            return {"ok": activate_ok, "code": "ACTIVATED" if activate_ok else "FAIL"}
        if name == "page.screenshot":
            return {
                "ok": True,
                "code": "SCREENSHOT",
                "data": {
                    "mime": "image/png",
                    "dataUrl": data_url,
                    "approxBytes": 100,
                },
            }
        return {"ok": False, "code": "UNEXPECTED", "detail": name}

    h._action = _action  # type: ignore[method-assign]
    return h


def test_screenshot_writes_under_ops(tmp_path, monkeypatch):
    home = tmp_path / "home"
    ops = home / "ops" / "shots"
    ops.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))  # type: ignore[arg-type]
    # Path.home is a staticmethod-like — patch via monkeypatch on Path
    monkeypatch.setattr("pathlib.Path.home", lambda: home)

    raw = _MINI_PNG
    data_url = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
    h = _handlers_with_fake_action(data_url)
    out = ops / "tab.png"
    res = h.screenshot({"out": str(out), "tabId": 42})
    assert res.get("ok") is True, res
    assert out.is_file()
    assert out.read_bytes() == raw
    assert "dataUrl" not in (res.get("data") or {})
    assert res["data"]["path"] == str(out.resolve())
    assert res["data"]["tabId"] == 42


def test_screenshot_path_denied_outside_roots(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    data_url = "data:image/png;base64," + base64.b64encode(_MINI_PNG).decode("ascii")
    h = _handlers_with_fake_action(data_url)
    evil = tmp_path / "evil" / "x.png"
    evil.parent.mkdir()
    res = h.screenshot({"out": str(evil)})
    assert res.get("ok") is False
    assert res.get("code") == "SCREENSHOT_PATH_DENIED"


def test_screenshot_activate_fail():
    data_url = "data:image/png;base64," + base64.b64encode(_MINI_PNG).decode("ascii")
    h = _handlers_with_fake_action(data_url, activate_ok=False)
    res = h.screenshot({"tabId": 9})
    assert res.get("ok") is False
    assert res.get("code") == "SCREENSHOT_ACTIVATE_FAIL"
