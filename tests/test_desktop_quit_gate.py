"""The desktop profile and quit gate must not silently empty out.

PR #4 replaced profiles/desktop_apps.json with an empty denylist, empty
per-app profiles, default allow_quit true, and mode operator-proxy. On that
tree profile_for stopped returning PROFILE_DENIED, and desktop.quit treated
a caller-supplied operator_confirm boolean as the human gate.

Current main still has the protective profile. These tests lock that file
and the quit path: a denylisted app is denied, operator_confirm=true alone
is not a D4 grant, and an allowlisted app still reaches the leash action
only after an operator-signed D4 grant.
"""
from __future__ import annotations

import json

import pytest

from host.desktop_handlers import PROFILES, DesktopHandlers

# Apps the hard denylist must keep. Extra names are fine; dropping one is not.
REQUIRED_DENYLIST = (
    "1Password",
    "1Password 7",
    "Authy",
    "Bitwarden",
    "Coinbase",
    "Keychain Access",
    "Ledger Live",
    "Mail",
    "Messages",
    "Microsoft Authenticator",
    "Passwords",
    "Wallet",
)

# TextEdit is the demo editor and the only shipped profile with allow_quit true.
ALLOW_QUIT_EXCEPTION = "TextEdit"


def _shipped() -> dict:
    return json.loads(PROFILES.read_text(encoding="utf-8"))


def _handlers() -> DesktopHandlers:
    return DesktopHandlers()


def _capture_action(monkeypatch, handler: DesktopHandlers) -> list[tuple]:
    calls: list[tuple] = []

    def fake(action: str, **extra):
        calls.append((action, extra))
        return {"ok": True, "action": action, **extra}

    monkeypatch.setattr(handler, "_action", fake)
    return calls


def test_shipped_denylist_and_default_quit_cannot_empty():
    data = _shipped()
    hard = data.get("denylist_hard")
    assert isinstance(hard, list) and hard, "denylist_hard emptied"
    missing = [name for name in REQUIRED_DENYLIST if name not in hard]
    assert missing == [], f"denylist dropped {missing}"
    assert data.get("profiles"), "per-app profiles emptied"
    assert data.get("mode") != "operator-proxy"
    default = data.get("default") or {}
    assert default.get("allow_quit") is False


def test_shipped_per_app_allow_quit_stays_false():
    profiles = _shipped()["profiles"]
    assert ALLOW_QUIT_EXCEPTION in profiles
    assert profiles[ALLOW_QUIT_EXCEPTION]["allow_quit"] is True
    for app, prof in profiles.items():
        if app == ALLOW_QUIT_EXCEPTION:
            continue
        assert prof.get("allow_quit") is False, app


def test_profile_for_denies_every_hard_denylist_app():
    handler = _handlers()
    for app in REQUIRED_DENYLIST:
        prof = handler.profile_for(app)
        assert prof.get("denied") is True, app
        assert "denylist_hard" in str(prof.get("reason"))


def test_focus_denylisted_app_does_not_reach_the_leash(monkeypatch):
    handler = _handlers()
    calls = _capture_action(monkeypatch, handler)
    out = handler.focus({"app": "1Password"})
    assert out["ok"] is False and out["code"] == "PROFILE_DENIED"
    assert calls == []


@pytest.mark.parametrize("app", REQUIRED_DENYLIST)
def test_quit_denied_for_denylisted_app(monkeypatch, app):
    handler = _handlers()
    calls = _capture_action(monkeypatch, handler)
    out = handler.quit({"app": app, "operator_confirm": True})
    assert out["ok"] is False and out["code"] == "PROFILE_DENIED"
    assert calls == []


def test_quit_denylist_wins_over_an_operator_d4_grant(monkeypatch):
    handler = _handlers()
    monkeypatch.setattr(handler, "_operator_d4_granted", lambda app: True)
    calls = _capture_action(monkeypatch, handler)
    out = handler.quit({"app": "Mail", "operator_confirm": True})
    assert out["code"] == "PROFILE_DENIED"
    assert calls == []


@pytest.mark.parametrize("confirm", [True, "true", 1])
def test_quit_denied_with_only_operator_confirm_and_no_human_gate(monkeypatch, confirm):
    handler = _handlers()
    calls = _capture_action(monkeypatch, handler)
    out = handler.quit({"app": "TextEdit", "operator_confirm": confirm})
    assert out["ok"] is False
    assert out["code"] == "OPERATOR_SIGNATURE_REQUIRED"
    assert "operator_confirm" in out["detail"]
    assert calls == []


def test_quit_without_confirm_is_unchanged_for_allowlisted_app(monkeypatch):
    handler = _handlers()
    calls = _capture_action(monkeypatch, handler)
    out = handler.quit({"app": "TextEdit", "operator_confirm": False})
    assert out["ok"] is False and out["code"] == "HUMAN_CONFIRM_REQUIRED"
    assert calls == []


def test_quit_allowlisted_app_still_posts_the_same_action_once_d4_is_granted(monkeypatch):
    """Aside from the human gate, TextEdit quit is still desktop.quit to the leash."""
    handler = _handlers()
    monkeypatch.setattr(handler, "_operator_d4_granted", lambda app: app == "TextEdit")
    calls = _capture_action(monkeypatch, handler)
    out = handler.quit({"app": "TextEdit", "operator_confirm": True})
    assert out["ok"] is True
    assert calls == [("desktop.quit", {"app": "TextEdit"})]


def test_allow_quit_false_still_denies_an_allowlisted_profile(monkeypatch):
    handler = _handlers()
    monkeypatch.setattr(handler, "_operator_d4_granted", lambda app: True)
    calls = _capture_action(monkeypatch, handler)
    out = handler.quit({"app": "Notes", "operator_confirm": True})
    assert out["ok"] is False and out["code"] == "PROFILE_ACTION_DENIED"
    assert calls == []


def test_default_allow_quit_false_denies_apps_without_a_profile(monkeypatch):
    handler = _handlers()
    monkeypatch.setattr(handler, "_operator_d4_granted", lambda app: True)
    calls = _capture_action(monkeypatch, handler)
    out = handler.quit({"app": "Calculator", "operator_confirm": True})
    assert out["code"] == "PROFILE_ACTION_DENIED"
    assert calls == []


def test_operator_d4_grant_fails_closed_without_a_signer():
    """No caller argument can satisfy the grant. Signing identity is not here."""
    handler = _handlers()
    assert handler._operator_d4_granted("TextEdit") is False
    assert handler._operator_d4_granted("1Password") is False
