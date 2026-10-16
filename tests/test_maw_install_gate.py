"""Bridge: Maw install-gate honors INSTALL_BLOCK (agent_control_pytest)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

MAW = Path.home() / "maw"
sys.path.insert(0, str(MAW))

from maw.cli import main  # noqa: E402
from maw.install_gate import FLAG, check_argv, clear_flag  # noqa: E402


def _set() -> None:
    FLAG.parent.mkdir(parents=True, exist_ok=True)
    FLAG.write_text(
        json.dumps({"reason": "test", "run_id": "bridge"}) + "\n",
        encoding="utf-8",
    )


def _clear() -> None:
    if FLAG.exists():
        FLAG.unlink()


def test_install_blocked_under_flag():
    try:
        _set()
        out = check_argv(["install", "pkg"])
        assert out["refuse"] is True
        assert out["code"] == "INSTALL_BLOCKED"
        assert main(["install-gate", "check", "--", "publish"]) == 75
    finally:
        _clear()


def test_clear_and_allow():
    try:
        _set()
        assert clear_flag(operator_confirm=True)["ok"]
        out = check_argv(["install", "pkg"])
        assert out["refuse"] is False
        assert main(["install-gate", "status"]) == 0
    finally:
        _clear()
