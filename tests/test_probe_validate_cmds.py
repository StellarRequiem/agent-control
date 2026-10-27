"""10.10 probe rail: named commands registered and validator process-proven."""

from __future__ import annotations

from pathlib import Path

from host.shell_handlers import ALLOW_COMMANDS, ShellHandlers

PROBES = Path.home() / "ops" / "probes"
VENV_PY = Path.home() / "mcp-assure" / ".venv" / "bin" / "python"


PROBE_REMOVED = ("probe_validate", "probe_validate_ok", "probe_validate_bad", "probe_selftest")


def test_probe_commands_registered():
    # C1b: probe_* executed scripts under ~/ops (formerly writable) and were removed
    # from the named-command allowlist (blue verify #14). Read-only rails remain.
    for name in PROBE_REMOVED:
        assert name not in ALLOW_COMMANDS, name
    for name in ("blue_apex_tail", "soc_latest"):
        assert name in ALLOW_COMMANDS, name
    assert ALLOW_COMMANDS["blue_apex_tail"][:3] == ["tail", "-n", "5"]
    assert ALLOW_COMMANDS["soc_latest"][:2] == ["ls", "-1"]


def test_removed_probe_commands_denied():
    for name in PROBE_REMOVED:
        out = ShellHandlers().run({"name": name})
        assert out.get("ok") is False and out.get("code") == "COMMAND_NOT_ALLOWLISTED", out


def test_live_collect_results_schema_valid_if_present():
    results = PROBES / "results"
    if not results.is_dir():
        return
    paths = sorted(results.glob("P-*.json"))
    if not paths:
        return
    import json
    import sys

    sys.path.insert(0, str(PROBES))
    from validate_result import validate

    for p in paths:
        errs = validate(json.loads(p.read_text(encoding="utf-8")))
        assert errs == [], (p.name, errs)


LOCKED_1000 = "a44275dfb5617c4a676b53dcd39947c0f1029050443c71573bfad11e633f7120"


def test_1000_pin_matches_lock():
    import hashlib

    digest = hashlib.sha256(
        (Path.home() / "ops" / "10.00-AGENT-INDEX.md").read_bytes()
    ).hexdigest()
    assert digest == LOCKED_1000


def test_lock_pins_writes_sha256():
    import importlib.util

    script = PROBES / "lock_pins.py"
    spec = importlib.util.spec_from_file_location("lock_pins", script)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    assert mod.main() == 0
    text = (PROBES / "results" / "LOCK.sha256").read_text(encoding="utf-8")
    assert "10.00-AGENT-INDEX.md" in text
    assert "10.10-PROBE-CARDS.md" in text
    for line in text.splitlines():
        hexpart, _, _path = line.partition("  ")
        assert len(hexpart) == 64
        int(hexpart, 16)


def test_probe_validate_latest_if_present():
    # C1b: probe_validate is no longer a named command; must be refused.
    out = ShellHandlers().run({"name": "probe_validate"})
    assert out.get("ok") is False and out.get("code") == "COMMAND_NOT_ALLOWLISTED", out
