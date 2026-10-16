"""host_code surface (GAP_BRIDGE G3) — no live bridges required."""

from __future__ import annotations

from host.plane_host import detect_mediated_shell_config, host_code_surface


def test_host_code_has_pack_version():
    h = host_code_surface()
    assert h.get("pack_path")
    assert h.get("pack_version") is not None
    assert int(h["pack_version"]) >= 12
    assert h.get("pack_tool_count", 0) > 20
    assert "claude-control" in str(h.get("claude_actor") or "")


def test_detect_mediated_returns_config_path():
    m = detect_mediated_shell_config()
    assert "native_bash_deny_configured" in m
    assert "agent_control_mcp_configured" in m
    assert "config" in m
