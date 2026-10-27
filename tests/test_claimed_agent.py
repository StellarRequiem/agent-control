"""Self-declared `_agent` name: stripped, report-only, side-logged."""

import json

import pytest

import mcp_http


@pytest.fixture
def env(tmp_path, monkeypatch):
    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps({"agents": {
        "nicodemus": {"status": "certified", "match": [{"plane": "agent-control", "actor": "nicodemus"}]},
        "sentinel-demi": {"status": "certified", "match": [{"plane": "agent-control", "actor": "sentinel_demi"}]},
        "gone": {"status": "revoked", "match": []},
    }}))
    monkeypatch.setattr(mcp_http, "AGENT_REGISTRY", reg)
    monkeypatch.setattr(mcp_http, "CLAIMS_LOG", tmp_path / "claims" / "claimed-agents.jsonl")
    seen = {}

    class FakeHost:
        actor = "grok"

        def call(self, name, args):
            seen["name"], seen["args"] = name, dict(args)
            return {"executed": True, "verdict": {"decision": "ALLOW", "receipt_id": "r1", "receipt_hash": "h"}}

    monkeypatch.setattr(mcp_http, "host", lambda: FakeHost())
    mcp_http._req.agent_name = None
    return tmp_path, seen


def _log(tmp):
    p = tmp / "claims" / "claimed-agents.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


def test_classify(env):
    assert mcp_http.classify_claim("nicodemus") == "nicodemus"
    assert mcp_http.classify_claim("sentinel_demi") == "sentinel-demi"
    assert mcp_http.classify_claim("Sentinel-Demi") == "sentinel-demi"
    assert mcp_http.classify_claim("gone") == "invalid:gone"
    assert mcp_http.classify_claim("x/../y;rm") == "invalid:xyrm"
    assert mcp_http.classify_claim(None) is None


def test_arg_stripped_and_decision_unchanged(env):
    tmp, seen = env
    out = mcp_http._call_plane("plane.status", {"_agent": "nicodemus", "k": 1})
    assert seen["args"] == {"k": 1}
    assert out["verdict"]["decision"] == "ALLOW"
    row = _log(tmp)[0]
    assert (row["claimed_agent"], row["actor"], row["receipt_id"], row["via"]) == ("nicodemus", "grok", "r1", "arg")


def test_bogus_name_flagged_not_denied(env):
    tmp, seen = env
    out = mcp_http._call_plane("plane.status", {"_agent": "mallory"})
    assert out["verdict"]["decision"] == "ALLOW" and seen["args"] == {}
    assert _log(tmp)[0]["claimed_agent"] == "invalid:mallory"


def test_no_name_no_log(env):
    tmp, seen = env
    mcp_http._call_plane("plane.status", {})
    assert _log(tmp) == []


def test_header_claim(env):
    tmp, _ = env
    mcp_http._req.agent_name = "sentinel_demi"
    mcp_http._call_plane("plane.status", {})
    mcp_http._req.agent_name = None
    assert _log(tmp)[0]["claimed_agent"] == "sentinel-demi" and _log(tmp)[0]["via"] == "header"


def test_rpc_strips_for_first_class_and_plane_call(env):
    tmp, seen = env
    mcp_http.handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                         "params": {"name": "plane_status", "arguments": {"_agent": "nicodemus"}}})
    assert "_agent" not in seen["args"]
    mcp_http.handle_rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "plane_call",
                         "arguments": {"tool": "browser.tabs", "arguments_json": json.dumps({"_agent": "nicodemus"}),
                                       "_agent": "sentinel_demi"}}})
    assert "_agent" not in seen["args"]
    assert [r["claimed_agent"] for r in _log(tmp)] == ["nicodemus", "sentinel-demi"]


def test_claims_log_outside_receipts_dir():
    assert "receipts" not in mcp_http.CLAIMS_LOG.parts
