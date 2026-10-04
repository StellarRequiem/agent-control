"""Stdio process actor: startup roster, receipt stamp, no JSON override.

The name comes from `--actor` or AGENT_CONTROL_ACTOR (default grok) and is
fixed for the process. These tests build the host the same way mcp_server.main
does after resolve_stdio_actor returns. They do not import mcp_server: that
module loads the MCP SDK, which CI does not install.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from host.plane_host import AssuredPlaneHost
from host.stdio_actor import resolve_stdio_actor

ROOT = Path(__file__).resolve().parent.parent


def _host(tmp_path: Path, actor: str | None = None) -> AssuredPlaneHost:
    kwargs: dict = {
        "receipts_path": tmp_path / "plane-host.jsonl",
        "freeze_path": tmp_path / "FREEZE",
        "roster_dir": tmp_path,
        "adaptive": True,
    }
    if actor is not None:
        kwargs["actor"] = actor
    return AssuredPlaneHost(**kwargs)


def _receipts(path: Path) -> list[dict]:
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines]


def test_default_actor_is_grok(tmp_path):
    assert resolve_stdio_actor([], {}, receipts_dir=tmp_path) == "grok"
    host = _host(tmp_path)
    out = host.call("plane.route", {"task": "git status"})
    assert out["executed"] is True
    assert _receipts(tmp_path / "plane-host.jsonl")[-1]["actor"] == "grok"


def test_actor_codex_stamps_call_and_unknown_tool(tmp_path):
    actor = resolve_stdio_actor(["--actor", "codex"], {}, receipts_dir=tmp_path)
    assert actor == "codex"
    assert resolve_stdio_actor(["--actor", "Codex"], {}, receipts_dir=tmp_path) == "codex"
    host = _host(tmp_path, actor)
    ok = host.call("plane.route", {"task": "git status"})
    assert ok["executed"] is True
    denied = host.call("not.a.real.tool", {})
    assert denied["executed"] is False
    assert (denied.get("verdict") or {})["code"] == "UNKNOWN_TOOL"
    recs = _receipts(tmp_path / "plane-host.jsonl")
    assert [r["actor"] for r in recs] == ["codex", "codex"]
    assert recs[-1]["code"] == "UNKNOWN_TOOL"
    assert recs[-1]["decision"] == "DENY"


def test_unknown_actor_fails_startup(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        resolve_stdio_actor(["--actor", "worm"], {}, receipts_dir=tmp_path)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "worm" in err
    assert "Refusing to start" in err
    assert not (tmp_path / "plane-host.jsonl").exists()


def test_blank_actor_flag_refuses(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        resolve_stdio_actor(["--actor", ""], {}, receipts_dir=tmp_path)
    assert exc.value.code == 2
    assert "Refusing to start" in capsys.readouterr().err


def test_host_rejects_unknown_actor(tmp_path):
    from host.stdio_actor import UnknownActorError

    with pytest.raises(UnknownActorError):
        _host(tmp_path, "worm")


def test_unknown_env_actor_fails_startup(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        resolve_stdio_actor([], {"AGENT_CONTROL_ACTOR": "worm"}, receipts_dir=tmp_path)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "worm" in err
    assert "Refusing to start" in err
    assert not (tmp_path / "plane-host.jsonl").exists()


def test_env_fallback_and_flag_wins(tmp_path):
    assert (
        resolve_stdio_actor([], {"AGENT_CONTROL_ACTOR": "claude"}, receipts_dir=tmp_path)
        == "claude"
    )
    assert (
        resolve_stdio_actor(
            ["--actor", "codex"],
            {"AGENT_CONTROL_ACTOR": "claude"},
            receipts_dir=tmp_path,
        )
        == "codex"
    )
    assert resolve_stdio_actor([], {"AGENT_CONTROL_ACTOR": "  "}, receipts_dir=tmp_path) == "grok"


def test_json_actor_cannot_override(tmp_path):
    host = _host(tmp_path, resolve_stdio_actor(["--actor", "codex"], {}, receipts_dir=tmp_path))
    out = host.call(
        "plane.route",
        {
            "task": "git status",
            "actor": "grok",
            "agent": "claude",
            "agent_id": "grok",
        },
    )
    assert out["executed"] is True
    rec = _receipts(tmp_path / "plane-host.jsonl")[-1]
    assert rec["actor"] == "codex"
    assert "actor" not in (rec.get("metadata") or {}).get("arg_keys", [])


def test_plane_status_reports_actor(tmp_path):
    host = _host(tmp_path, "codex")
    out = host.call("plane.status", {})
    assert out["executed"] is True
    actors = (out.get("result") or {}).get("actors") or {}
    assert actors.get("current") == "codex"
    assert actors.get("binding") == "stdio_process"
    assert actors.get("roster")[:3] == ["grok", "claude", "codex"]
    rec = _receipts(tmp_path / "plane-host.jsonl")[-1]
    assert rec["actor"] == "codex"
    assert rec["tool"] == "plane.status"


def test_host_default_does_not_read_env(tmp_path, monkeypatch):
    """AGENT_CONTROL_ACTOR is the stdio CLI fallback, not a host-wide switch."""
    monkeypatch.setenv("AGENT_CONTROL_ACTOR", "codex")
    host = _host(tmp_path)
    host.call("plane.route", {"task": "git status"})
    assert _receipts(tmp_path / "plane-host.jsonl")[-1]["actor"] == "grok"


def test_operator_roster_file_admits_extra_actor(tmp_path):
    (tmp_path / "stdio-actors").write_text("# local\nops-bot\n", encoding="utf-8")
    assert resolve_stdio_actor(["--actor", "ops-bot"], {}, receipts_dir=tmp_path) == "ops-bot"
    host = _host(tmp_path, "ops-bot")
    out = host.call("plane.status", {})
    assert (out.get("result") or {})["actors"]["current"] == "ops-bot"
    assert "ops-bot" in (out.get("result") or {})["actors"]["roster"]


def test_passport_filename_extends_roster_without_reading_secret(tmp_path, capsys):
    secret = "live-token-should-not-leak"
    (tmp_path / "mcp-http.ops.token").write_text(secret + "\n", encoding="utf-8")
    assert resolve_stdio_actor(["--actor", "ops"], {}, receipts_dir=tmp_path) == "ops"
    with pytest.raises(SystemExit):
        resolve_stdio_actor(["--actor", "nope"], {}, receipts_dir=tmp_path)
    assert secret not in capsys.readouterr().err


def test_mcp_server_resolves_actor_before_stdio_run():
    text = (ROOT / "mcp_server.py").read_text(encoding="utf-8")
    assert "AssuredPlaneHost(actor=_process_actor)" in text
    body = text.split("def main(", 1)[1].split("\ndef ", 1)[0]
    assert body.index("resolve_stdio_actor") < body.index("mcp.run")
