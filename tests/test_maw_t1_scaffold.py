"""Bridge test: Maw Detect T1 scaffold under ~/maw (read-only).

Lives here so agent_control_pytest (already allowlisted) can execute it
without reloading named-command tables after adding maw_pytest.
"""

from __future__ import annotations

import sys
from pathlib import Path

MAW = Path.home() / "maw"
assert MAW.is_dir(), f"expected Maw checkout at {MAW}"
sys.path.insert(0, str(MAW))

from maw.cli import main, _exit_for_report  # noqa: E402
from maw.detect import load_ioc_pack, SHAPE_IOC, run_detect  # noqa: E402
from maw.report import Finding, build_report, format_summary  # noqa: E402


def test_shape_ioc():
    data, path = load_ioc_pack(SHAPE_IOC)
    assert path == SHAPE_IOC
    assert data["meta"]["id"] == "maw_t1_shape"


def test_report_contract():
    rep = build_report(
        roots=["/tmp"],
        ioc_pack_id="t",
        ioc_version=1,
        findings=[
            Finding(
                rule="r",
                path="/p",
                detail="d",
                severity="high",
                confidence="high",
            )
        ],
        mode="quick",
    )
    assert rep["read_only"] is True
    assert rep["remediation"] is False
    assert rep["schema"] == "maw.detect.v1"
    assert "Maw Detect" in format_summary(rep)
    assert _exit_for_report(rep) == 1
    assert _exit_for_report(build_report(
        roots=["."], ioc_pack_id="t", ioc_version=1, findings=[], mode="quick"
    )) == 0


def test_cli_deferred_tiers():
    assert main(["freeze"]) == 2
    assert main(["contain"]) == 2
    # watch is T0 (implemented); bare `maw watch` without subcommand is usage, not TIER_NOT_IN_SLICE
    assert main(["watch", "init"]) == 0
    assert main(["watch"]) == 2
    # Finsec F0 ships alongside Detect; deferred tiers stay deferred
    assert main(["ledger", "status"]) == 0


def test_detect_on_maw_tree():
    code = main(
        [
            "detect",
            "--root",
            str(MAW),
            "--ioc",
            str(SHAPE_IOC),
            "--summary",
        ]
    )
    assert code in (0, 1)


def test_run_detect_returns_schema():
    rep = run_detect(roots=[MAW], mode="quick", ioc_path=SHAPE_IOC)
    assert rep["ok"] is True
    assert rep["tier"] == "T1"
    assert rep["read_only"] is True
