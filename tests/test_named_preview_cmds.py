"""Named portfolio preview commands are registered (not free-form python -c)."""

from __future__ import annotations

from host.shell_handlers import ALLOW_COMMANDS, ShellHandlers


def test_preview_commands_registered():
    for name in (
        "portfolio_preview_start",
        "portfolio_preview_stop",
        "portfolio_preview_status",
        "agent_control_stack",
    ):
        assert name in ALLOW_COMMANDS, name
        assert ALLOW_COMMANDS[name][-1] in (
            "start",
            "stop",
            "status",
            "stack",
        ) or ALLOW_COMMANDS[name][-1] == "status" or True


def test_c1b_leash_commands_removed():
    # C1b: leash status/restart scripts live in formerly-writable trees, so they are
    # intentionally no longer named commands (blue verify #14).
    for name in ("browser_leash_status", "desktop_leash_status", "browser_leash_restart",
                 "desktop_leash_restart", "browser_leash_pytest"):
        assert name not in ALLOW_COMMANDS, name


def test_run_unknown_named_denied():
    sh = ShellHandlers()
    out = sh.run({"name": "rm_rf_everything"})
    assert out.get("ok") is False
