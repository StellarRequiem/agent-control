"""Bridge test: Maw Finsec F0 paper spend envelopes under ~/maw.

Runs via agent_control_pytest (allowlisted). No real money APIs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

MAW = Path.home() / "maw"
assert MAW.is_dir(), f"expected Maw checkout at {MAW}"
sys.path.insert(0, str(MAW))

from maw.cli import main  # noqa: E402
from maw.ledger import (  # noqa: E402
    DEFAULT_POLICY,
    SCHEMA,
    STATUS_SCHEMA,
    PolicyError,
    load_policy,
    status_report,
)


def test_policy_default_exists_and_loads():
    assert DEFAULT_POLICY.is_file()
    data, path = load_policy()
    assert path == DEFAULT_POLICY
    assert data["schema"] == SCHEMA
    assert data["transfer"]["default_action"] == "deny"
    assert data["claims"]["payment_product"] is False
    assert data["claims"]["real_money_apis"] is False


def test_status_report_paper_contract():
    rep = status_report()
    assert rep["ok"] is True
    assert rep["schema"] == STATUS_SCHEMA
    assert rep["tier"] == "F0"
    assert rep["payment_product"] is False
    assert rep["real_money_apis"] is False
    assert rep["real_transfers"] is False
    assert rep["transfer"]["executable_in_f0"] is False
    assert rep["agent_spend_gate"]["enforced_in_f0"] is False
    assert rep["envelopes"]["llm_daily_ceiling"] == 25.0
    assert rep["envelopes"]["spent_today"]["source"] == "policy_placeholder"


def test_cli_ledger_and_finsec_status():
    assert main(["ledger", "status"]) == 0
    assert main(["finsec", "status"]) == 0


def test_cli_detect_and_watch_unaffected():
    """Finsec wiring must not break detect path or Watch T0."""
    # bare watch without subcommand → usage exit 2
    assert main(["watch"]) == 2
    assert main(["contain"]) == 2
    # Watch T0 status works (clean empty-ish home may still be 0/1)
    assert main(["watch", "init"]) == 0
    code = main(
        [
            "detect",
            "--root",
            str(MAW),
            "--ioc",
            str(MAW / "iocs" / "pack_t1_shape.json"),
            "--summary",
        ]
    )
    assert code in (0, 1)


def test_custom_policy_remaining(tmp_path):
    custom = {
        "schema": SCHEMA,
        "version": 1,
        "meta": {"id": "bridge.custom"},
        "claims": {
            "payment_product": False,
            "real_money_apis": False,
            "real_transfers": False,
        },
        "envelopes": {
            "currency": "USD",
            "llm_daily_ceiling": 10.0,
            "cloud_daily_ceiling": 20.0,
            "agent_spend_daily_ceiling": 3.0,
        },
        "transfer": {"default_action": "deny", "allowed_destinations": []},
        "agent_spend_gate": {"enabled": True, "require_operator_confirm_above": 1.0},
        "status": {"spent_today": {"llm": 4.0, "cloud": 0.0, "agent": 0.0}},
    }
    p = tmp_path / "spend.json"
    p.write_text(json.dumps(custom), encoding="utf-8")
    rep = status_report(p)
    assert rep["envelopes"]["llm_remaining"] == 6.0
    assert main(["ledger", "status", "--policy", str(p)]) == 0


def test_missing_policy_errors(tmp_path):
    try:
        load_policy(tmp_path / "missing.json")
        assert False, "expected PolicyError"
    except PolicyError:
        pass
    assert main(["ledger", "status", "--policy", str(tmp_path / "missing.json")]) == 2
