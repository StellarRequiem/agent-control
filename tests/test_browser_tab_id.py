"""Unit tests: multi-tab tabId coercion + workspace shape (no live bridge)."""

from __future__ import annotations

from host.browser_handlers import BrowserHandlers, _coerce_tab_id


def test_coerce_tab_id_aliases():
    assert _coerce_tab_id({"tabId": 42}) == 42
    assert _coerce_tab_id({"tab_id": "99"}) == 99
    assert _coerce_tab_id({"id": 7}) == 7
    assert _coerce_tab_id(None) is None
    assert _coerce_tab_id({}) is None


def test_coerce_tab_id_does_not_steal_selector_id():
    # click/type may use CSS id-ish fields; with selector present, bare id is not tabId
    assert _coerce_tab_id({"selector": "#foo", "id": "not-a-tab"}) is None
    # tabId still wins when explicit
    assert _coerce_tab_id({"selector": "#foo", "tabId": 3}) == 3


def test_with_tab_injects_tabId(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_http(base, path, body, timeout=90.0):
        calls.append((path, dict(body)))
        return {"ok": True, "code": "OK", "data": {}}

    monkeypatch.setattr("host.browser_handlers.http_json", fake_http)
    bh = BrowserHandlers(base="http://test")

    bh.snapshot({"tabId": 11})
    assert calls[-1][1].get("tabId") == 11
    assert calls[-1][1].get("action") == "page.snapshot"

    bh.click({"selector": "a.x", "tabId": 12})
    assert calls[-1][1].get("tabId") == 12
    assert calls[-1][1].get("selector") == "a.x"

    bh.scroll({"dy": 400, "tab_id": 13})
    assert calls[-1][1].get("tabId") == 13
    assert calls[-1][1].get("dy") == 400

    bh.navigate({"url": "https://x.com/", "tabId": 14})
    assert calls[-1][1].get("tabId") == 14
    assert calls[-1][1].get("url") == "https://x.com/"


def test_workspace_lists_tabs_and_match(monkeypatch):
    def fake_http(base, path, body, timeout=90.0):
        action = body.get("action")
        if action == "tab.list":
            return {
                "ok": True,
                "code": "TABS",
                "data": {
                    "tabs": [
                        {"id": 1, "url": "https://x.com/i/grok", "title": "Grok", "active": True},
                        {
                            "id": 2,
                            "url": "https://github.com/StellarRequiem/mcp-assure",
                            "title": "mcp-assure",
                            "active": False,
                        },
                    ]
                },
            }
        if action == "page.info":
            return {"ok": True, "code": "INFO", "data": {"url": "https://github.com/…", "title": "mcp-assure"}}
        if action == "page.snapshot":
            return {"ok": True, "code": "SNAP", "data": {"text": "hello workspace " * 50}}
        return {"ok": True, "code": "OK", "data": {}}

    monkeypatch.setattr("host.browser_handlers.http_json", fake_http)
    bh = BrowserHandlers(base="http://test")
    out = bh.workspace({"match": "github.com", "snapshot": True, "snapshot_chars": 40})
    assert out["ok"] is True
    assert out["code"] == "WORKSPACE"
    assert out["tab_count"] == 2
    assert out["focus"]["tabId"] == 2
    assert out["snapshot"]["ok"] is True
    assert len(out["snapshot"]["text_preview"]) <= 40


def test_screenshot_activates_tab_first(monkeypatch):
    actions: list[str] = []

    def fake_http(base, path, body, timeout=90.0):
        actions.append(body.get("action") or path)
        if body.get("action") == "tab.activate":
            return {"ok": True, "code": "ACTIVATED"}
        if body.get("action") == "page.screenshot":
            return {"ok": True, "code": "SCREENSHOT", "data": {"dataUrl": "data:image/png;base64,xx"}}
        return {"ok": True, "data": {}}

    monkeypatch.setattr("host.browser_handlers.http_json", fake_http)
    bh = BrowserHandlers(base="http://test")
    out = bh.screenshot({"tabId": 55})
    assert out["ok"] is True
    assert "tab.activate" in actions
    assert "page.screenshot" in actions
    assert out["data"]["tabId"] == 55
