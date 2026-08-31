"""Bearer token → actor passports (blue-team identity, not a SOC).

Fixture tokens only. Do not commit live mcp-http.token values.
"""

from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from host.passports import (
    DEFAULT_ROSTER,
    load_passports,
    resolve_authorization,
    roster_public,
    token_prefix,
    write_passport,
)
from host.plane_host import AssuredPlaneHost

# Obvious fixtures — not live operator secrets.
GROK_TOKEN = "fixture-grok-passport-token-aaaaaaaa"
CLAUDE_TOKEN = "fixture-claude-passport-token-bbbbbbbb"
CODEX_TOKEN = "fixture-codex-passport-token-cccccccc"
WRONG_TOKEN = "fixture-wrong-passport-token-zzzzzzzz"


def _write_fixtures(tmp_path: Path) -> Path:
    (tmp_path / "mcp-http.token").write_text(GROK_TOKEN + "\n", encoding="utf-8")
    (tmp_path / "mcp-http.claude.token").write_text(CLAUDE_TOKEN + "\n", encoding="utf-8")
    (tmp_path / "mcp-http.codex.token").write_text(CODEX_TOKEN + "\n", encoding="utf-8")
    return tmp_path


def _host(tmp_path: Path) -> AssuredPlaneHost:
    return AssuredPlaneHost(
        receipts_path=tmp_path / "plane-host.jsonl",
        freeze_path=tmp_path / "FREEZE",
        passports_dir=tmp_path,
        adaptive=True,
    )


def _last_receipt(path: Path) -> dict:
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines, "expected a receipt line"
    return json.loads(lines[-1])


def _receipt_actors(path: Path) -> list[str]:
    if not path.is_file():
        return []
    out = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        out.append(json.loads(ln)["actor"])
    return out


# ---- passport map ----------------------------------------------------------

def test_legacy_mcp_http_token_is_grok(tmp_path):
    _write_fixtures(tmp_path)
    table = load_passports(tmp_path)
    assert table.resolve(GROK_TOKEN) == "grok"
    assert table.resolve(CLAUDE_TOKEN) == "claude"
    assert table.resolve(CODEX_TOKEN) == "codex"
    assert table.resolve(WRONG_TOKEN) is None
    assert table.resolve("") is None


def test_bearer_header_maps_to_actor(tmp_path):
    _write_fixtures(tmp_path)
    assert resolve_authorization(f"Bearer {GROK_TOKEN}", receipts_dir=tmp_path) == "grok"
    assert resolve_authorization(f"Bearer {CLAUDE_TOKEN}", receipts_dir=tmp_path) == "claude"
    assert resolve_authorization(f"bearer {CLAUDE_TOKEN}", receipts_dir=tmp_path) == "claude"
    assert resolve_authorization(f"Bearer {WRONG_TOKEN}", receipts_dir=tmp_path) is None
    assert resolve_authorization(None, receipts_dir=tmp_path) is None
    assert resolve_authorization("Basic abc", receipts_dir=tmp_path) is None


def test_token_prefix_never_equals_secret():
    assert token_prefix(GROK_TOKEN) != GROK_TOKEN
    assert GROK_TOKEN.startswith(token_prefix(GROK_TOKEN).rstrip("…"))
    assert "…" in token_prefix(GROK_TOKEN)


def test_roster_public_has_no_secrets(tmp_path):
    _write_fixtures(tmp_path)
    status = roster_public(tmp_path)
    blob = json.dumps(status)
    assert GROK_TOKEN not in blob
    assert CLAUDE_TOKEN not in blob
    assert set(status["roster"]) == set(DEFAULT_ROSTER)
    assert status["binding"] == "mcp_http_bearer"
    assert "X-Actor" in status["spoofable_ignored"]
    assert "present" in status and "grok" in status["present"] and "claude" in status["present"]


def test_mint_refuses_overwrite(tmp_path):
    write_passport("claude", CLAUDE_TOKEN, receipts_dir=tmp_path)
    with pytest.raises(FileExistsError):
        write_passport("claude", "other", receipts_dir=tmp_path)


# ---- host stamps actor on receipts ----------------------------------------

def test_same_tool_call_stamps_different_actor(tmp_path):
    host = _host(tmp_path)
    receipts = tmp_path / "plane-host.jsonl"
    grok = host.call("plane.route", {"task": "open github.com in chrome"}, actor="grok")
    claude = host.call("plane.route", {"task": "open github.com in chrome"}, actor="claude")
    assert grok.get("executed") is True
    assert claude.get("executed") is True
    actors = _receipt_actors(receipts)
    assert actors[-2:] == ["grok", "claude"]


def test_unknown_tool_denial_stamps_passport_actor(tmp_path):
    host = _host(tmp_path)
    out = host.call("not.a.real.tool", {}, actor="claude")
    assert out.get("executed") is False
    assert (out.get("verdict") or {}).get("code") == "UNKNOWN_TOOL"
    rec = _last_receipt(tmp_path / "plane-host.jsonl")
    assert rec["actor"] == "claude"
    assert rec["code"] == "UNKNOWN_TOOL"
    assert rec["decision"] == "DENY"


def test_plane_status_actors_block_lists_roster_without_secrets(tmp_path):
    _write_fixtures(tmp_path)
    host = _host(tmp_path)
    out = host.call("plane.status", {}, actor="grok")
    assert out.get("executed") is True
    actors = (out.get("result") or {}).get("actors") or {}
    blob = json.dumps(out)
    assert GROK_TOKEN not in blob and CLAUDE_TOKEN not in blob
    assert actors.get("roster") == list(DEFAULT_ROSTER)
    assert actors.get("internal") == list(DEFAULT_ROSTER)
    assert actors.get("binding") == "mcp_http_bearer"


def test_default_cli_actor_remains_grok(tmp_path):
    host = _host(tmp_path)
    host.call("plane.route", {"task": "git status"})
    assert _last_receipt(tmp_path / "plane-host.jsonl")["actor"] == "grok"


# ---- HTTP: 401 / spoof headers / fixture tokens ---------------------------

def _start_http(tmp_path: Path):
    from mcp_http import HttpContext, make_handler

    _write_fixtures(tmp_path)
    host = _host(tmp_path)
    ctx = HttpContext(receipts_dir=tmp_path, host=host)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(ctx))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    return httpd, f"http://127.0.0.1:{port}", tmp_path / "plane-host.jsonl"


def _post(url: str, body: dict, *, token: str | None, extra_headers: dict | None = None) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if extra_headers:
        headers.update(extra_headers)
    req = Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    try:
        with urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"raw": raw}
        return e.code, payload


def test_http_grok_vs_claude_same_call(tmp_path):
    httpd, base, receipts = _start_http(tmp_path)
    try:
        call = {"name": "plane.route", "arguments": {"task": "open github.com in chrome"}}
        g_code, g_body = _post(base + "/v1/call", call, token=GROK_TOKEN)
        c_code, c_body = _post(base + "/v1/call", call, token=CLAUDE_TOKEN)
        assert g_code == 200 and c_code == 200
        assert g_body.get("actor") == "grok"
        assert c_body.get("actor") == "claude"
        assert g_body.get("executed") is True and c_body.get("executed") is True
        assert _receipt_actors(receipts)[-2:] == ["grok", "claude"]
    finally:
        httpd.shutdown()


def test_http_wrong_token_is_401_and_writes_no_receipt(tmp_path):
    httpd, base, receipts = _start_http(tmp_path)
    try:
        before = receipts.read_text(encoding="utf-8") if receipts.is_file() else ""
        code, body = _post(
            base + "/v1/call",
            {"name": "plane.route", "arguments": {"task": "x"}},
            token=WRONG_TOKEN,
        )
        assert code == 401
        assert body.get("code") == "UNAUTHORIZED"
        assert "actor" not in body
        after = receipts.read_text(encoding="utf-8") if receipts.is_file() else ""
        assert after == before
    finally:
        httpd.shutdown()


def test_http_missing_bearer_is_401(tmp_path):
    httpd, base, receipts = _start_http(tmp_path)
    try:
        code, body = _post(
            base + "/v1/call",
            {"name": "plane.status", "arguments": {}, "actor": "claude"},
            token=None,
        )
        assert code == 401
        assert body.get("code") == "UNAUTHORIZED"
        if receipts.is_file():
            assert "claude" not in receipts.read_text(encoding="utf-8")
    finally:
        httpd.shutdown()


def test_http_x_actor_header_cannot_become_claude(tmp_path):
    httpd, base, receipts = _start_http(tmp_path)
    try:
        code, body = _post(
            base + "/v1/call",
            {"name": "plane.route", "arguments": {"task": "open github.com in chrome"}},
            token=GROK_TOKEN,
            extra_headers={"X-Actor": "claude", "User-Agent": "Claude-User/1.0"},
        )
        assert code == 200
        assert body.get("actor") == "grok"
        assert _last_receipt(receipts)["actor"] == "grok"
    finally:
        httpd.shutdown()


def test_http_json_actor_field_cannot_become_claude(tmp_path):
    httpd, base, receipts = _start_http(tmp_path)
    try:
        code, body = _post(
            base + "/v1/call",
            {
                "name": "plane.route",
                "actor": "claude",
                "arguments": {"task": "open github.com in chrome", "actor": "claude"},
            },
            token=GROK_TOKEN,
        )
        assert code == 200
        assert body.get("actor") == "grok"
        assert _last_receipt(receipts)["actor"] == "grok"
    finally:
        httpd.shutdown()


def test_http_unknown_tool_stamps_claude(tmp_path):
    httpd, base, receipts = _start_http(tmp_path)
    try:
        code, body = _post(
            base + "/v1/call",
            {"name": "worm.spray", "arguments": {}},
            token=CLAUDE_TOKEN,
        )
        assert code == 200
        assert body.get("actor") == "claude"
        assert (body.get("verdict") or {}).get("code") == "UNKNOWN_TOOL"
        rec = _last_receipt(receipts)
        assert rec["actor"] == "claude"
        assert rec["code"] == "UNKNOWN_TOOL"
    finally:
        httpd.shutdown()
