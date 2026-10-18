"""Bridge test: Maw Watch T0 scaffold under ~/maw (presence-only, no remediation).

Lives here so agent_control_pytest (already allowlisted) can execute it
without reloading named-command tables after adding a dedicated maw_watch_pytest.
"""

from __future__ import annotations

import sys
from pathlib import Path

MAW = Path.home() / "maw"
assert MAW.is_dir(), f"expected Maw checkout at {MAW}"
sys.path.insert(0, str(MAW))

from maw.cli import main  # noqa: E402
from maw.watch import (  # noqa: E402
    DEFAULT_POLICY_PATH,
    default_policy,
    load_policy,
    policy_gaps,
    run_once,
)


def test_default_policy_present():
    assert DEFAULT_POLICY_PATH.is_file()
    data, path = load_policy(DEFAULT_POLICY_PATH)
    assert path == DEFAULT_POLICY_PATH
    assert data["meta"]["tier"] == "T0"
    assert data["lifecycle"]["deny_by_default"] is True
    assert policy_gaps(data) == []
    assert len(data["package_name_watch"]) >= 10


def test_run_once_contract(tmp_path: Path):
    home = tmp_path / "h"
    home.mkdir()
    rep = run_once(home, policy=default_policy())
    assert rep["ok"] is True
    assert rep["schema"] == "maw.watch.v1"
    assert rep["tier"] == "T0"
    assert rep["read_only"] is True
    assert rep["remediation"] is False
    assert rep["status_line"] in ("clean", "attention", "policy_gap")
    kinds = {e["kind"] for e in rep["events"]}
    assert "lifecycle.denied" in kinds
    assert "agent_config.path_status" in kinds
    assert "token.long_lived_present" in kinds
    assert "package.baseline" in kinds


def test_cli_watch_status(tmp_path: Path):
    home = tmp_path / "h"
    home.mkdir()
    code = main(["watch", "status", "--home", str(home), "--json"])
    assert code == 0


def test_cli_watch_run_once_aliases(tmp_path: Path):
    home = tmp_path / "h"
    home.mkdir()
    assert main(["watch", "run-once", "--home", str(home)]) == 0
    assert main(["watch", "run", "once", "--home", str(home), "--json"]) == 0


def test_cli_watch_init():
    assert main(["watch", "init"]) == 0


def test_deferred_tiers_still_not_in_slice():
    assert main(["contain"]) == 2
    assert main(["freeze"]) == 2
