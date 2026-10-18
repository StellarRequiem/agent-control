"""Plane desktop signing: per-actor keys, fail closed, gateway-compatible.

The signer is the host process actor (the same string stamped on receipts).
AGENT_CONTROL_ACTOR is not a second identity.
"""
from __future__ import annotations

import base64
import hmac
import json
import os
import sys
from pathlib import Path

import pytest

from host import desktop_signing as S
from host.desktop_handlers import DesktopHandlers
from host.plane_host import AssuredPlaneHost
from host.stdio_actor import resolve_stdio_actor


def _key(tmp: Path, name: str, mode: int = 0o600, data: bytes | None = None) -> Path:
    p = tmp / name
    p.write_bytes(os.urandom(32) if data is None else data)
    p.chmod(mode)
    return p


def _receipts(path: Path) -> list[dict]:
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines]


class FakeBridge:
    def __init__(self, verify=None):
        self.calls, self.verify = [], verify

    def __call__(self, method, url, data, headers, timeout):
        self.calls.append((method, url, data, headers))
        if url.endswith("/health"):
            return 200, json.dumps({"ok": True, "auth_protocol": S.VERSION, "epoch": "e" * 64}).encode()
        if "X-Assurance-Auth" not in headers:
            return 403, b'{"ok":false,"code":"AUTH_REQUIRED"}'
        env = json.loads(base64.b64decode(headers["X-Assurance-Auth"]))
        if self.verify:
            path = url.split("8757", 1)[1]
            body = {} if data is None else json.loads(data)
            return 200, json.dumps(self.verify(env, method, path, body)).encode()
        return 200, json.dumps({"ok": True, "key_id": env["message"]["key_id"]}).encode()


def test_key_id_mapping_never_codex():
    assert S.key_id_for("grok") == "grok"
    assert S.key_id_for("claude") == "claude"
    assert S.key_id_for("codex") == "codex-plane"
    with pytest.raises(S.SigningRefused):
        S.key_id_for("../x")


def test_resolution_order(tmp_path):
    m = tmp_path / "keys.json"
    m.write_text(json.dumps({"claude": "/k/claude"}))
    env = {"AGENT_CONTROL_DESKTOP_KEY_GROK": "/k/grok", "AGENT_CONTROL_DESKTOP_KEYS": str(m)}
    assert S.resolve_key_path("grok", env) == Path("/k/grok")
    assert S.resolve_key_path("claude", env) == Path("/k/claude")
    assert S.resolve_key_path("ollama", env).name == "plane-ollama-action-key"
    assert S.resolve_key_path("codex", {}).name == "plane-codex-plane-action-key"


def test_missing_key_fails_closed_without_network(tmp_path):
    fake = FakeBridge()
    c = S.SignedDesktopClient("http://127.0.0.1:8757", "grok",
                              env={"AGENT_CONTROL_DESKTOP_KEY_GROK": str(tmp_path / "nope")}, transport=fake)
    out = c.call("/v1/status")
    assert out["ok"] is False and out["code"] == "DESKTOP_KEY_MISSING"
    assert "mint" in out["detail"] and fake.calls == []


@pytest.mark.parametrize("mode,data,code", [(0o644, None, "DESKTOP_KEY_FILE_MODE"),
                                            (0o600, b"short", "DESKTOP_KEY_LENGTH")])
def test_bad_key_files_refused(tmp_path, mode, data, code):
    k = _key(tmp_path, "k", mode, data)
    fake = FakeBridge()
    c = S.SignedDesktopClient("http://127.0.0.1:8757", "grok", env={"AGENT_CONTROL_DESKTOP_KEY_GROK": str(k)},
                              transport=fake)
    assert c.call("/v1/status")["code"] == code and fake.calls == []


def test_codex_key_reuse_refused(tmp_path):
    k = _key(tmp_path, "codex-action-key")
    c = S.SignedDesktopClient("http://127.0.0.1:8757", "grok", env={"AGENT_CONTROL_DESKTOP_KEY_GROK": str(k)},
                              transport=FakeBridge())
    assert c.call("/v1/status")["code"] == "DESKTOP_KEY_CODEX_REUSE_REFUSED"


def test_operator_routes_not_signed(tmp_path):
    k = _key(tmp_path, "k")
    fake = FakeBridge()
    c = S.SignedDesktopClient("http://127.0.0.1:8757", "grok", env={"AGENT_CONTROL_DESKTOP_KEY_GROK": str(k)},
                              transport=fake)
    for p in ("/v1/arm", "/v1/confirm", "/v1/d4-session"):
        assert c.call(p, {"x": 1})["code"] == "OPERATOR_SIGNATURE_REQUIRED"
    assert fake.calls == []


def test_redirects_refused():
    with pytest.raises(S.SigningRefused, match="HTTP_REDIRECT_REFUSED"):
        S._NoRedirect().redirect_request(None, None, 302, "Found", {}, "http://127.0.0.1/elsewhere")


def test_handlers_sign_with_passed_actor(tmp_path, monkeypatch):
    """Actor is an argument. AGENT_CONTROL_ACTOR must not choose the signer."""
    k = _key(tmp_path, "k")
    monkeypatch.setenv("AGENT_CONTROL_ACTOR", "codex")
    monkeypatch.setenv("AGENT_CONTROL_DESKTOP_KEY_CLAUDE", str(k))
    fake = FakeBridge()
    dh = DesktopHandlers(profiles_path=tmp_path / "none.json", actor="claude")
    dh.client.transport = fake
    assert dh.actor == "claude"
    assert dh.client.key_id == "claude"
    assert dh.status()["key_id"] == "claude"
    assert dh.apps()["key_id"] == "claude"
    assert dh.d4_session({"open": True})["code"] == "OPERATOR_SIGNATURE_REQUIRED"
    assert dh.confirm({"id": "1", "approve": True})["code"] == "OPERATOR_SIGNATURE_REQUIRED"


def test_host_actor_signs_and_receipts_as_the_same_name(tmp_path, monkeypatch):
    """--actor claude signs as claude and receipts as claude.

    AGENT_CONTROL_ACTOR=codex, and a real codex desktop key, must not split
    the signature from the receipt. Handler reload keeps that same actor.
    """
    monkeypatch.setenv("AGENT_CONTROL_ACTOR", "codex")
    claude_key = os.urandom(32)
    codex_key = os.urandom(32)
    claude_path = _key(tmp_path, "claude-key", data=claude_key)
    _key(tmp_path, "codex-key", data=codex_key)
    monkeypatch.setenv("AGENT_CONTROL_DESKTOP_KEY_CLAUDE", str(claude_path))
    monkeypatch.setenv("AGENT_CONTROL_DESKTOP_KEY_CODEX", str(tmp_path / "codex-key"))

    actor = resolve_stdio_actor(["--actor", "claude"], receipts_dir=tmp_path)
    assert actor == "claude"

    receipts = tmp_path / "plane-host.jsonl"
    host = AssuredPlaneHost(
        receipts_path=receipts,
        freeze_path=tmp_path / "FREEZE",
        roster_dir=tmp_path,
        actor=actor,
    )
    fake = FakeBridge()
    host.desktop.client.transport = fake

    assert host.actor == "claude"
    assert host.desktop.actor == "claude"
    assert host.desktop.client.actor == "claude"
    assert host.desktop.client.key_id == "claude"
    assert host.desktop.client.key_path == claude_path

    out = host.call("desktop.status", {})
    assert out["executed"] is True
    assert (out.get("result") or {})["key_id"] == "claude"
    rec = _receipts(receipts)[-1]
    assert rec["actor"] == "claude"
    assert rec["tool"] == "desktop.status"

    signed = [call for call in fake.calls if call[3].get("X-Assurance-Auth")]
    assert signed
    env = json.loads(base64.b64decode(signed[-1][3]["X-Assurance-Auth"]))
    msg = S.canonical(env["message"])
    sig = base64.b64decode(env["signature"])
    assert hmac.compare_digest(hmac.digest(claude_key, msg, "sha256"), sig)
    assert not hmac.compare_digest(hmac.digest(codex_key, msg, "sha256"), sig)
    assert env["message"]["key_id"] == "claude"

    before = len(fake.calls)
    confirm = host.call("desktop.confirm", {"id": "abc", "approve": True})
    d4 = host.call("desktop.d4_session", {"open": True})
    assert confirm["executed"] is True
    assert d4["executed"] is True
    assert confirm["result"]["code"] == "OPERATOR_SIGNATURE_REQUIRED"
    assert confirm["result"]["actor"] == "claude"
    assert d4["result"]["code"] == "OPERATOR_SIGNATURE_REQUIRED"
    assert d4["result"]["actor"] == "claude"
    assert len(fake.calls) == before

    reloaded = host._plane_reload_handlers()
    assert reloaded["ok"] is True
    assert host.actor == "claude"
    assert host.desktop.actor == "claude"
    assert host.desktop.client.actor == "claude"
    assert host.desktop.client.key_id == "claude"
    assert host.desktop.client.key_path == claude_path
    host.desktop.client.transport = fake
    apps = host.call("desktop.apps", {})
    assert apps["executed"] is True
    assert apps["result"]["key_id"] == "claude"
    assert {row["actor"] for row in _receipts(receipts)} == {"claude"}


BRIDGE = Path(os.environ.get("DESKTOP_LEASH_BRIDGE", Path(__file__).resolve().parents[2] / "desktop-leash" / "bridge"))


@pytest.mark.skipif(not (BRIDGE / "desktop_auth.py").is_file(), reason="desktop-leash bridge not alongside")
def test_envelope_accepted_by_real_gateway_authenticator(tmp_path):
    pytest.importorskip("cryptography")
    sys.path.insert(0, str(BRIDGE))
    import desktop_auth as A
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization

    raw = os.urandom(32)
    k = _key(tmp_path, "k", data=raw)
    pub = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = A.Authenticator({"grok": raw, "codex": os.urandom(32)}, pub, epoch="e" * 64)

    def verify(env, method, path, body):
        return dict(auth.authorize(env, method, path, body), ok=True)

    c = S.SignedDesktopClient("http://127.0.0.1:8757", "grok", env={"AGENT_CONTROL_DESKTOP_KEY_GROK": str(k)},
                              transport=FakeBridge(verify))
    assert c.call("/v1/status")["key_id"] == "grok"
    out = c.call("/v1/action", {"action": "desktop.apps"})
    assert out["ok"] and out["role"] == "action"
    # A key not registered with the gateway is rejected by the real authenticator.
    k2 = _key(tmp_path, "k2")
    c2 = S.SignedDesktopClient("http://127.0.0.1:8757", "grok", env={"AGENT_CONTROL_DESKTOP_KEY_GROK": str(k2)},
                               transport=FakeBridge(verify))
    with pytest.raises(A.Refused, match="BAD_SIGNATURE"):
        c2.call("/v1/status")
